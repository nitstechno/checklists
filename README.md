# Checklists — document checklists for service centers (FastAPI + PostgreSQL)

Customers scan a QR code at a center and open **`https://checklists.domain.demo/<centerslug>`** to see, in English / हिन्दी / తెలుగు, the documents needed for each service (PAN, Passport, Ration Card, Scholarship…) — **Apply new** or **Modify / Correction** — with sample images/PDFs attached to each document.

## Run it

The **frontend** is one static file (`frontend/index.html`, no build step, no React). The **backend** is FastAPI + PostgreSQL and also serves that file when it finds `../frontend`, so **one process = the whole app on one port**.

Both ways below give the same result: **http://localhost:8000** (the app), **http://localhost:8000/api/docs** (interactive API docs for testing; `/docs` redirects there).

### A. Docker (database included)
```bash
cd backend
cp .env.example .env          # set JWT_SECRET and POSTGRES_PASSWORD
docker compose up -d --build  # starts PostgreSQL + API; mounts ../frontend; port 8000
```
One time only:
```bash
docker compose exec -it api python -m app.cli create-admin --username admin   # asks for a password
docker compose exec api python -m app.cli seed-demo                           # optional demo center at /demo
```
Edit `frontend/index.html` and refresh; no rebuild needed. Logs: `docker compose logs -f api`. Stop: `docker compose down` (add `-v` to wipe database and uploads).

### B. Manual (Python + your own PostgreSQL)
Needs Python 3.11+ and PostgreSQL running locally.
```bash
createdb checklists                      # or: sudo -u postgres createdb checklists
cd backend
cp .env.example .env                     # set JWT_SECRET, POSTGRES_PASSWORD (+ POSTGRES_USER / DB_HOST if different)
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app                            # API + frontend on http://127.0.0.1:8000  (auto-reload while DEBUG=1)
```
One time only (second terminal, venv active):
```bash
python -m app.cli create-admin --username admin
python -m app.cli seed-demo              # optional
```
To reach it from other devices on your network add `HOST=0.0.0.0` to `.env`.

### C. Production
Use `backend/.env.production.example` as the server's `.env` (API on `127.0.0.1:8100`, `FRONTEND_DIR=off`, `DEBUG=0`); nginx serves the frontend and proxies `/api`. Follow sections 6 and 7 once; afterwards every push to `main` deploys both parts. **One time only**, after the first deploy:
```bash
ssh fhdeploy@your-server && cd /opt/checklists/backend
docker compose exec -it api python -m app.cli create-admin --username <your-admin-name>
```

### Configuration: how settings are read
1. **Real environment variables** (shell, Docker, systemd) first.
2. Anything **missing or empty** is read from `backend/.env` (the backend reads the file itself; Docker Compose reads it too).
3. Defaults for the rest.

| Variable | Purpose | Default |
|---|---|---|
| `JWT_SECRET` | signs login tokens (**required**) | — |
| `DATABASE_URL` | full DB URL, or built from the next lines | built |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | DB credentials (password required) | `checklists` / — / `checklists` |
| `DB_HOST` / `DB_PORT` | DB location, manual run only | `localhost` / `5432` |
| `UPLOADS_HOST_DIR` (`UPLOAD_DIR`) | uploads: manual = folder (relative to `backend/`); Docker = volume name or host path | `uploads` |
| `FRONTEND_DIR` | folder with `index.html`; `off` = API only | `../frontend` |
| `DEBUG` | `1` = API docs (`/api/docs`, `/docs`) + auto-reload (manual) | off |
| `HOST` / `PORT` | manual run | `127.0.0.1` / `8000` |
| `BIND_ADDR` / `API_PORT` | Docker published address / port | `0.0.0.0` / `8000` |
| `FRONTEND_HOST_DIR` | Docker: host folder mounted as the frontend | `../frontend` |

### One-time commands (backend CLI) vs. the app

| Done once on the backend | Done afterwards inside the app |
|---|---|
| `create-admin` — first global admin (refuses to run again unless `--force`) | global admin creates / disables / deletes centers, resets center passwords |
| `seed-demo` — optional demo center (skip in production) | center admins manage services, documents, uploads, logo |
| `reset-admin-password` — only if the admin password is lost | everyone can change their own password (👤 → Manage) |

The API starts without any admin and logs a reminder until `create-admin` has been run.

## 1. Pages and who sees what

| Address | Visitor | What they see |
|---|---|---|
| `/` | everyone | **Directory** of all active centers: logo, name, address, phone (tap to call), service badges, search box, "Open checklist" link |
| `/<slug>` | customer | The center's page: services → documents for **Apply new** / **Modify**, sample images/PDFs. EN / हिन्दी / తెలుగు switch (customer pages only) |
| 👤 **Login** (top right, on `/` and on every `/<slug>`) | not logged in | Login form for both the global admin and center owners |
| after login | **center admin** (`username = slug`) | **Manage** screen for *their* center: name, phone, address, logo, services, documents, info lines, uploads, QR code, change password |
| after login | **global admin** | on `/`: **Manage centers** (create with name/slug/phone/address, enable/disable switch, reset password, delete); on any `/<slug>`: the same Manage screen for that center |

Admin screens are English only (no language switch). Changes are saved to the database immediately and are live on the next page load. The UI adapts from phones to wide laptop screens: service list side-panel on large screens, two-column Manage screen, light/dark mode follows the device.

## 2. Architecture

```
Browser ──https──> nginx (checklists.domain.demo)
                    ├─ /            static frontend  (/var/www/checklists/current)  single index.html, SPA routes /<slug>
                    ├─ /api/*       proxy → FastAPI container 127.0.0.1:8100 → PostgreSQL container
                    └─ /files/*     uploaded logos/images/PDFs (/srv/checklists/uploads/<slug>/<uuid>.<ext>)
```
Repo layout:
```
frontend/index.html            the whole UI (customer + center admin + global admin)
backend/app/main.py            FastAPI app (models, auth, endpoints, uploads)
backend/app/starter_services.json   starter checklists copied into every new center
backend/docker-compose.yml     db (postgres:16) + api; same file for local and production
backend/.env.example           local/test settings;  .env.production.example = server settings
nginx/checklists.conf          separate nginx server block
scripts/server-setup.sh        one-time server prep;  scripts/backup.sh  daily backup
.github/workflows/deploy.yml   GitHub Actions pipeline
```

## 3. Data model (PostgreSQL, tables auto-created at API start)

- `centers(id, slug UNIQUE, name, phone, address, logo, active, created_at)` (the `address` column is added automatically to older databases at startup)
- `users(id, username UNIQUE, pw_hash, role 'global'|'center', center_id → centers ON DELETE CASCADE)`
- `services(id, center_id → centers ON DELETE CASCADE, position, icon, name JSONB, procs JSONB)`

`name` = `{"en","hi","te"}`. `procs` = `{"new": P, "edit": P}` where `P = {"fee": "", "refs": [Ref], "docs": [{"t":[en,hi,te], "i":[en,hi,te info], "refs":[Ref]}]}` and `Ref = {"name","type":"image"|"pdf","src"}`. `src` is `/files/<slug>/<uuid>.<ext>` (uploads) or an `https://` link. A process with no documents is hidden from customers.

Files live on disk (`UPLOADS_HOST_DIR/<slug>/…`), not in the database. Deleting a center deletes its folder. Files replaced/removed inside a checklist stay on disk (orphans) until the center is deleted.

## 4. API (all under `/api`, JSON; `Authorization: Bearer <token>`)

| Method & path | Who | Purpose |
|---|---|---|
| `GET /centers` | public | active centers for the directory (slug, name, phone, address, logo, service names) |
| `GET /centers/{slug}` | public (inactive: admins only) | center + all services |
| `POST /auth/login` · `GET /auth/me` · `POST /auth/password` | any | login (12 h token), current user, change own password |
| `PUT /centers/{slug}` | own center admin / global | name, phone, address, logo |
| `POST /centers/{slug}/services` · `PUT/DELETE …/services/{id}` | own center admin / global | manage checklists |
| `POST /centers/{slug}/files` | own center admin / global | upload JPG/PNG/WEBP/PDF ≤ 5 MB (checked by file signature) → `{name,type,src}` |
| `GET/POST /admin/centers` | global | list / create (returns the new admin's username + one-time password) |
| `PATCH /admin/centers/{slug}` | global | enable/disable, rename |
| `POST /admin/centers/{slug}/reset-password` · `DELETE /admin/centers/{slug}` | global | new password (shown once) / delete everything of a center |

Interactive docs: set `DEBUG=1` → `/api/docs` (also `/docs`).

## 5. Day-to-day

**Create a center (global admin, inside the app):** log in at `https://checklists.domain.demo/` → 👤 → dashboard → name (+ optional slug, phone) → *Create center*. Copy the share message (link, username, password) and send it to the owner. The center is live immediately with the 4 starter services. Slug = URL = username, cannot be changed later (QR codes are printed) — delete and recreate if needed. Reserved slugs: `api files admin assets login www static hub docs`.

**Center admin:** open own link → 👤 → log in → *Manage*: edit details, add/edit services (3 languages, documents, info lines, attach images/PDFs), print the QR (Manage → QR code). Change the first password.

**Disable** hides the center (customers see "Center not found"; admins can still open it). **Reset password** gives a new one-time password. **Delete** asks you to type the slug and removes services, users and files.

## 6. First-time server setup (separate from your existing site)

1. **DNS:** `A  checklists.domain.demo → <server IP>` (no wildcard needed).
2. **Docker** + Compose plugin installed; nginx already present.
3. `sudo bash scripts/server-setup.sh` (creates user `fhdeploy`, `/var/www/checklists`, `/opt/checklists/backend`, `/srv/checklists/uploads` owned by uid 1001). Add the pipeline's SSH **public** key to `/home/fhdeploy/.ssh/authorized_keys`.
4. Create `/opt/checklists/backend/.env` (copy `backend/.env.production.example`): strong `POSTGRES_PASSWORD`, `JWT_SECRET` = `openssl rand -hex 32`; it already sets `UPLOADS_HOST_DIR`, `API_PORT=8100`, `FRONTEND_DIR=off`, `DEBUG=0`. The first global admin is **not** created from `.env`; run the one-time `create-admin` command after the first deploy (see "Run it → C").
5. **Certificate:** `sudo certbot certonly --webroot -w /var/www/letsencrypt -d checklists.domain.demo` (start with only the port-80 block enabled, then enable 443).
6. **nginx:** copy `nginx/checklists.conf` to `/etc/nginx/conf.d/`, replace the host name, `sudo nginx -t && sudo systemctl reload nginx`. It does not touch your existing server blocks.

## 7. GitHub pipeline

Secrets (Settings → Secrets and variables → Actions): `DEPLOY_HOST`, `DEPLOY_USER` (`fhdeploy`), `DEPLOY_SSH_KEY` (private key), `DEPLOY_PORT` (optional), `DEPLOY_BACK_PATH` (`/opt/checklists/backend`), `DEPLOY_FRONT_PATH` (`/var/www/checklists`).

On push to `main` (changes in `frontend/` or `backend/`): rsync backend (keeps server `.env`) → `docker compose up -d --build` → rsync frontend to `releases/<time>-<sha>` → atomically switch `current` symlink (last 5 kept). **Frontend rollback:** `ln -sfn /var/www/checklists/releases/<older> /var/www/checklists/current_tmp && mv -Tf /var/www/checklists/current_tmp /var/www/checklists/current`. **Backend rollback:** `git revert` and push.
Note: Docker-group membership is effectively root on that host; keep the deploy key private and branch-protect `main`.

## 8. Local development

See **Run it → A / B** at the top.

## 9. Backups & operations

`scripts/backup.sh` dumps Postgres and tars uploads into `/srv/checklists/backups` (14 days). Copy it to `/opt/checklists/backup.sh` and add a cron entry. Logs: `docker compose logs -f api`. Restore: `gunzip -c db-DATE.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB`.

## 10. Security notes

- Passwords are bcrypt-hashed; tokens are signed JWTs (12 h) kept in the browser's localStorage. Login is rate-limited by nginx (10/min per IP). Always serve over HTTPS.
- Uploads are validated by file signature (no SVG/HTML), served with `nosniff`; links in checklists must be `/files/…` or `http(s)://`.
- Rotating `JWT_SECRET` logs everyone out. The API trusts nginx for the client IP; keep port 8100 bound to 127.0.0.1.
- Schema changes later: tables are created automatically but not migrated; add Alembic before changing columns.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| 502 on `/api` | `docker compose ps`; `docker compose logs api` (usually bad `.env`) |
| "Center not found" | slug typo, center disabled, or deleted |
| Upload fails | file type/size; folder owned by uid 1001; nginx `client_max_body_size` |
| Images 404 | nginx `alias` path equals `UPLOADS_HOST_DIR` |
| Can't log in | center admins: username is the slug (lowercase), ask the global admin to reset the password. Lost global admin password: `python -m app.cli reset-admin-password --username <name>` |
| "No global admin yet" in logs | run `create-admin` once |
