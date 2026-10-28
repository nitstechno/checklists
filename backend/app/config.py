"""Settings. Real environment variables win; anything missing (or empty) there is read from a .env file.

.env lookup order: current folder, then backend/.  Docker Compose already passes its own variables,
so inside the container the environment is used as-is.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

BASE = Path(__file__).resolve().parent.parent  # backend/


def _load_env_file() -> None:
    for folder in (Path.cwd(), BASE):
        f = folder / ".env"
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip().removeprefix("export ").strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            elif " #" in val:
                val = val.split(" #", 1)[0].rstrip()
            if key and not os.environ.get(key):   # system env wins
                os.environ[key] = val
        return


_load_env_file()


def env(key: str, default=None):
    return os.environ.get(key) or default


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (BASE / p).resolve()


JWT_SECRET = env("JWT_SECRET")
if not JWT_SECRET:
    raise SystemExit("JWT_SECRET is not set. Add it to backend/.env or export it (openssl rand -hex 32).")

DATABASE_URL = env("DATABASE_URL")
if not DATABASE_URL:
    if not env("POSTGRES_PASSWORD"):
        raise SystemExit("Set DATABASE_URL, or POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB (+ DB_HOST, DB_PORT) in backend/.env")
    DATABASE_URL = "postgresql+psycopg://{}:{}@{}:{}/{}".format(
        env("POSTGRES_USER", "checklists"), quote_plus(env("POSTGRES_PASSWORD")),
        env("DB_HOST", "localhost"), env("DB_PORT", "5432"), env("POSTGRES_DB", "checklists"))

UPLOAD_DIR = _path(env("UPLOAD_DIR") or env("UPLOADS_HOST_DIR") or "uploads")
DEBUG = str(env("DEBUG", "")).lower() in ("1", "true", "yes", "on")
HOST, PORT = env("HOST", "127.0.0.1"), int(env("PORT", "8000"))


def _frontend() -> "Path | None":
    v = env("FRONTEND_DIR")
    if v and v.lower() in ("off", "none", "0", "false"):
        return None
    p = _path(v) if v else BASE.parent / "frontend"   # default: ../frontend next to backend/
    return p if (p / "index.html").is_file() else None


FRONTEND_DIR = _frontend()
