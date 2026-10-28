"""Form Helper API: centers, services (checklists), users, uploads."""
import json, re, secrets, shutil, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import bcrypt, jwt
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, Boolean, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import selectinload, DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app import config  # loads .env (system environment variables take priority)

SECRET = config.JWT_SECRET
UPLOADS = config.UPLOAD_DIR; UPLOADS.mkdir(parents=True, exist_ok=True)
DEBUG = config.DEBUG
STARTER = json.loads((Path(__file__).parent / "starter_services.json").read_text(encoding="utf-8"))
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
RESERVED = {"api", "files", "admin", "assets", "login", "www", "static", "hub", "docs"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}$")
ALPH = "abcdefghjkmnpqrstuvwxyz23456789"
MAX_UPLOAD = 5 * 1024 * 1024


# ---------------------------------------------------------------- models
class Base(DeclarativeBase): pass

class Center(Base):
    __tablename__ = "centers"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    logo: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    services: Mapped[list["Service"]] = relationship(cascade="all, delete-orphan", order_by="Service.position, Service.id")
    users: Mapped[list["User"]] = relationship(back_populates="center", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    pw_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))  # "global" | "center"
    center_id: Mapped[Optional[int]] = mapped_column(ForeignKey("centers.id", ondelete="CASCADE"), nullable=True)
    center: Mapped[Optional[Center]] = relationship(back_populates="users")

class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    center_id: Mapped[int] = mapped_column(ForeignKey("centers.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    icon: Mapped[str] = mapped_column(String(8), default="📄")
    name: Mapped[dict] = mapped_column(JSONB)    # {"en": "...", "hi": "...", "te": "..."}
    procs: Mapped[dict] = mapped_column(JSONB)   # {"new": {fee, refs, docs}, "edit": {...}}


# ---------------------------------------------------------------- schemas
def _url(v: str) -> str:
    if v and not v.startswith(("/files/", "https://", "http://")):
        raise ValueError("link must start with /files/, https:// or http://")
    return v

class Ref(BaseModel):
    name: str = Field(max_length=120)
    type: Literal["image", "pdf"] = "image"
    src: str = Field(max_length=400)

    @field_validator("src")
    @classmethod
    def check_src(cls, v): return _url(v)

class Doc(BaseModel):
    t: list[str] = Field(min_length=3, max_length=3)
    i: list[str] = Field(default=["", "", ""], min_length=3, max_length=3)
    refs: list[Ref] = []

class Proc(BaseModel):
    fee: str = ""
    refs: list[Ref] = []
    docs: list[Doc] = []

class Procs(BaseModel):
    new: Proc = Proc()
    edit: Proc = Proc()

class ServiceIn(BaseModel):
    icon: str = Field("📄", max_length=8)
    name: dict[str, str]
    procs: Procs

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        if not v.get("en", "").strip(): raise ValueError("English name is required")
        return v

class CenterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field("", max_length=30)
    address: str = Field("", max_length=300)
    logo: str = Field("", max_length=300)

    @field_validator("logo")
    @classmethod
    def check_logo(cls, v): return _url(v)

class CenterNew(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = ""
    phone: str = ""
    address: str = ""
    starter: bool = True

class CenterPatch(BaseModel):
    active: Optional[bool] = None
    name: Optional[str] = None
    phone: Optional[str] = None

class LoginIn(BaseModel):
    username: str
    password: str

class PwIn(BaseModel):
    old: str
    new: str = Field(min_length=8, max_length=72)


# ---------------------------------------------------------------- helpers / auth
def hash_pw(p: str) -> str: return bcrypt.hashpw(p.encode()[:72], bcrypt.gensalt()).decode()
def check_pw(p: str, h: str) -> bool:
    try: return bcrypt.checkpw(p.encode()[:72], h.encode())
    except ValueError: return False
def gen_pw() -> str: return "".join(secrets.choice(ALPH) for _ in range(10))
def slugify(s: str) -> str: return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:29]

def get_db():
    with SessionLocal() as db:
        yield db

bearer = HTTPBearer(auto_error=False)

def current_user(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred: raise HTTPException(401, "Login required")
    try: uid = int(jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])["sub"])
    except Exception: raise HTTPException(401, "Session expired, please log in again")
    u = db.get(User, uid)
    if not u: raise HTTPException(401, "Account not found")
    return u

def optional_user(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer), db: Session = Depends(get_db)):
    try: return current_user(cred, db)
    except HTTPException: return None

def require_global(u: User = Depends(current_user)) -> User:
    if u.role != "global": raise HTTPException(403, "Global admin only")
    return u

def get_center(db: Session, slug: str) -> Center:
    c = db.scalar(select(Center).where(Center.slug == slug.lower()))
    if not c: raise HTTPException(404, "Center not found")
    return c

def center_for(slug: str, u: User, db: Session) -> Center:
    c = get_center(db, slug)
    if u.role != "global" and u.center_id != c.id: raise HTTPException(403, "Not your center")
    return c

def user_out(u: User): return {"username": u.username, "role": u.role, "center_slug": u.center.slug if u.center else None}
def service_out(s: Service): return {"id": s.id, "icon": s.icon, "name": s.name, "procs": s.procs}
def center_out(c: Center):
    return {"slug": c.slug, "name": c.name, "phone": c.phone, "address": c.address, "logo": c.logo, "active": c.active,
            "services": [service_out(s) for s in c.services]}

def make_center(db: Session, name: str, slug: str, phone: str = "", starter: bool = True, address: str = ""):
    slug = slugify(slug or name)
    if not SLUG.match(slug) or slug in RESERVED: raise HTTPException(400, "Invalid or reserved slug (use a-z, 0-9, -; 2-29 chars)")
    if db.scalar(select(Center).where(Center.slug == slug)) or db.scalar(select(User).where(User.username == slug)):
        raise HTTPException(409, "Slug already in use")
    c = Center(slug=slug, name=name.strip(), phone=phone.strip(), address=address.strip())
    if starter:
        for i, s in enumerate(STARTER): c.services.append(Service(position=i, icon=s["icon"], name=s["name"], procs=s["procs"]))
    pw = gen_pw(); c.users.append(User(username=slug, pw_hash=hash_pw(pw), role="center"))
    db.add(c); db.commit()
    return c, pw


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as cx:  # tiny migration for databases created before the address column existed
        cx.execute(text("ALTER TABLE centers ADD COLUMN IF NOT EXISTS address VARCHAR(300) NOT NULL DEFAULT ''"))
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.role == "global")):
            print("[setup] No global admin yet. Run once: python -m app.cli create-admin --username admin   (Docker: docker compose exec -it api python -m app.cli create-admin --username admin)", flush=True)
    print(f"[frontend] serving {config.FRONTEND_DIR}" if config.FRONTEND_DIR else "[frontend] not found - API only (nginx serves the frontend)", flush=True)
    print(f"[uploads] {UPLOADS}", flush=True)
    yield

app = FastAPI(title="Form Helper API", lifespan=lifespan,
              docs_url="/api/docs" if DEBUG else None, redoc_url=None, openapi_url="/api/openapi.json" if DEBUG else None)

@app.get("/api/health")
def health(): return {"ok": True}

# --- auth
@app.post("/api/auth/login")
def login(b: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == b.username.strip().lower()))
    if not u or not check_pw(b.password, u.pw_hash): raise HTTPException(401, "Wrong username or password")
    exp = datetime.now(timezone.utc) + timedelta(hours=12)
    return {"token": jwt.encode({"sub": str(u.id), "exp": exp}, SECRET, algorithm="HS256"), "user": user_out(u)}

@app.get("/api/auth/me")
def me(u: User = Depends(current_user)): return user_out(u)

@app.post("/api/auth/password")
def change_pw(b: PwIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not check_pw(b.old, u.pw_hash): raise HTTPException(400, "Current password is wrong")
    u.pw_hash = hash_pw(b.new); db.commit(); return {"ok": True}

# --- public + center admin
@app.get("/api/centers")
def public_centers(db: Session = Depends(get_db)):
    q = select(Center).where(Center.active.is_(True)).options(selectinload(Center.services)).order_by(Center.name)
    return [{"slug": c.slug, "name": c.name, "phone": c.phone, "address": c.address, "logo": c.logo,
             "services": [s.name for s in c.services]} for c in db.scalars(q)]

@app.get("/api/centers/{slug}")
def read_center(slug: str, db: Session = Depends(get_db), u: Optional[User] = Depends(optional_user)):
    c = get_center(db, slug)
    if not c.active and not (u and (u.role == "global" or u.center_id == c.id)): raise HTTPException(404, "Center not found")
    return center_out(c)

@app.put("/api/centers/{slug}")
def update_center(slug: str, b: CenterIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = center_for(slug, u, db); c.name, c.phone, c.address, c.logo = b.name.strip(), b.phone.strip(), b.address.strip(), b.logo
    db.commit(); return center_out(c)

@app.post("/api/centers/{slug}/services")
def add_service(slug: str, b: ServiceIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = center_for(slug, u, db)
    pos = (max((s.position for s in c.services), default=-1)) + 1
    s = Service(center_id=c.id, position=pos, icon=b.icon, name=b.name, procs=b.procs.model_dump())
    db.add(s); db.commit(); return service_out(s)

def _svc(db, c, sid):
    s = db.get(Service, sid)
    if not s or s.center_id != c.id: raise HTTPException(404, "Service not found")
    return s

@app.put("/api/centers/{slug}/services/{sid}")
def edit_service(slug: str, sid: int, b: ServiceIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _svc(db, center_for(slug, u, db), sid)
    s.icon, s.name, s.procs = b.icon, b.name, b.procs.model_dump()
    db.commit(); return service_out(s)

@app.delete("/api/centers/{slug}/services/{sid}")
def delete_service(slug: str, sid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_svc(db, center_for(slug, u, db), sid)); db.commit(); return {"ok": True}

def _sniff(b: bytes):
    if b.startswith(b"\xff\xd8\xff"): return "image", ".jpg"
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image", ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image", ".webp"
    if b.startswith(b"%PDF-"): return "pdf", ".pdf"
    return None, None

@app.post("/api/centers/{slug}/files")
async def upload(slug: str, file: UploadFile = File(...), u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = center_for(slug, u, db)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD: raise HTTPException(413, "File too large (max 5 MB)")
    kind, ext = _sniff(data)
    if not kind: raise HTTPException(415, "Only JPG, PNG, WEBP or PDF files are allowed")
    folder = UPLOADS / c.slug; folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ext; (folder / name).write_bytes(data)
    return {"name": Path(file.filename or name).name[:80], "type": kind, "src": f"/files/{c.slug}/{name}"}

# --- global admin
@app.get("/api/admin/centers")
def list_centers(_: User = Depends(require_global), db: Session = Depends(get_db)):
    return [{"slug": c.slug, "name": c.name, "phone": c.phone, "address": c.address, "active": c.active, "services": len(c.services),
             "username": c.users[0].username if c.users else None, "created_at": c.created_at.isoformat()}
            for c in db.scalars(select(Center).order_by(Center.created_at.desc()))]

@app.post("/api/admin/centers")
def create_center(b: CenterNew, _: User = Depends(require_global), db: Session = Depends(get_db)):
    c, pw = make_center(db, b.name, b.slug, b.phone, b.starter, b.address)
    return {"slug": c.slug, "name": c.name, "username": c.slug, "password": pw}

@app.patch("/api/admin/centers/{slug}")
def patch_center(slug: str, b: CenterPatch, _: User = Depends(require_global), db: Session = Depends(get_db)):
    c = get_center(db, slug)
    if b.active is not None: c.active = b.active
    if b.name: c.name = b.name.strip()
    if b.phone is not None: c.phone = b.phone.strip()
    db.commit(); return {"ok": True}

@app.post("/api/admin/centers/{slug}/reset-password")
def reset_pw(slug: str, _: User = Depends(require_global), db: Session = Depends(get_db)):
    c = get_center(db, slug); pw = gen_pw()
    if c.users: c.users[0].pw_hash = hash_pw(pw)
    else: c.users.append(User(username=c.slug, pw_hash=hash_pw(pw), role="center"))
    db.commit(); return {"username": c.users[0].username, "password": pw}

@app.delete("/api/admin/centers/{slug}")
def delete_center(slug: str, _: User = Depends(require_global), db: Session = Depends(get_db)):
    c = get_center(db, slug); folder = UPLOADS / c.slug
    db.delete(c); db.commit()
    shutil.rmtree(folder, ignore_errors=True); return {"ok": True}

app.mount("/files", StaticFiles(directory=UPLOADS), name="files")

if DEBUG:  # test convenience: /docs -> interactive API docs
    @app.get("/docs", include_in_schema=False)
    def _docs(): return RedirectResponse("/api/docs")

# Serve the frontend when it is available (../frontend or FRONTEND_DIR). In production nginx does this instead.
if config.FRONTEND_DIR:
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "files/")) or path in ("api", "files"):
            raise HTTPException(404, "Not found")
        return FileResponse(config.FRONTEND_DIR / "index.html")
