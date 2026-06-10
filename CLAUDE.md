# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

POS (Point of Sale) system for physical stores: a FastAPI backend (single MySQL server) and a Flet (Flutter/Python) desktop client, one client per cash register. See [README.md](README.md) for the full architecture diagram, role/permission matrix, and printer setup. Code comments and user-facing text are in Spanish — keep new comments/strings in Spanish for consistency.

## Running the system

### Backend (FastAPI)
```bash
cd backend
cp .env.example .env          # edit DB credentials / SECRET_KEY
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Swagger UI at `http://localhost:8000/docs`, ReDoc at `/redoc`.

### Frontend (Flet desktop client)
```bash
cd frontend
cp .env.example .env          # set API_BASE_URL to the backend's LAN IP
pip install -r requirements.txt
flet run main.py               # desktop mode
flet run --web --port 8080 main.py   # web mode
```
Note: `frontend/.posvenv/` is a checked-in virtualenv — don't treat its contents as project source when searching/grepping.

### Full stack via Docker
```bash
docker-compose up -d           # MySQL 8 + backend on :8000
```
`setup.sql` seeds cash registers/categories; tables themselves are created by SQLAlchemy (`Base.metadata.create_all`) on backend startup.

### Default login
`admin` / `admin123` (created automatically on first backend startup if no users exist — change in production).

## Backend architecture (`backend/app/`)

- `main.py` — FastAPI app, CORS/GZip middleware, router registration (all under `/api` prefix), and the `lifespan` startup sequence: `create_all` → `_run_schema_migrations()` → `_seed_defaults()`.
- `config.py` — `pydantic-settings` `Settings`, loaded from `.env` (DB credentials, JWT secret/algorithm/expiry, server host/port).
- `database.py` — SQLAlchemy engine/session (`SessionLocal`, `Base`, `get_db` dependency).
- `models/__init__.py` — **all** ORM models in one file: `User`, `Category`/`Product`/`Inventory`/`InventoryMovement`, `CashRegister`/`CashSession`/`CashMovement`, `Sale`/`SaleItem`, `SaleReturn`/`SaleReturnItem`, `AppConfig`. Enums (`UserRole`, `SaleStatus`, `PaymentMethod`, `SessionStatus`, `MovementType`) are defined here too.
  - `Sale.status` is a plain `String(30)` (not a SQL ENUM) to avoid MySQL case issues; valid values come from `SaleStatus` and are stored lowercase. A SQLAlchemy `load` event listener normalizes `status` to lowercase on read.
- `schemas/__init__.py` — all Pydantic request/response schemas in one file.
- `routers/` — one module per domain, each exporting an `APIRouter`, all mounted under `/api` in `main.py`:
  - `auth.py` (`/api/auth`) — login, PIN login, supervisor verification, `/me`.
  - `users.py` (`/api/users`)
  - `products.py` (`/api/products` and `/api/categories`, two routers in one file) — products, categories, and inventory adjustment endpoints.
  - `sales.py` (`/api/sales`) — sale registration, returns/cancellations.
  - `cash.py` (`/api/cash`) — registers, cash sessions (open/close/physical count), cash movements.
  - `reports.py` (`/api/reports`)
  - `settings.py` (`/api/settings`) — `AppConfig` key/value store.
  - `admin.py` (`/api/admin`) — destructive maintenance endpoints (force-migrate, wipe sales/sessions/inventory movements/all data) — admin-only, use with care.
- `services/auth.py` — JWT creation/validation, bcrypt password hashing, `get_current_user`, and the role→permission map (`ROLE_PERMISSIONS`) plus `require_admin`/`require_manager`/`require_cashier` dependencies. Roles: `admin`, `manager`, `cashier`.
- `services/reports.py` — report calculation logic used by `routers/reports.py`.

### Schema migrations
There is no Alembic migration chain in active use despite it being a dependency. Schema changes that `create_all` can't express (column additions/type changes on existing tables, new tables added after initial release) are applied idempotently in `main.py`'s `_run_schema_migrations()` — each migration catches "already applied" errors (MySQL 1060 / "already exists") and logs accordingly. When changing existing table schemas, add a migration step here rather than relying on `create_all`.

## Frontend architecture (`frontend/`)

- `main.py` — entry point. Builds the Flet `Page`, holds global `app_state` dict (`config`, `session_id`, `session_info`, `pos_active`), handles view routing via `VIEW_BUILDERS`, global keyboard shortcuts (Ctrl+1..7 to switch views — see README for the mapping), login/logout flow, and a backend-connectivity check on startup.
- `config.py` — UI color constants, app title/version, `API_BASE_URL` (from `.env`).
- `services/api.py` — `APIClient`, the single HTTP client (httpx) wrapping every backend endpoint; holds the auth token and `current_user`. All view code goes through the shared `api` instance imported from `services`. Raises `APIError` (with `status_code`) on non-2xx responses.
- `services/printer.py` — ESC/POS thermal printer + cash drawer integration (USB or network/TCP).
- `views/` — one module per nav section: `login`, `pos` (sales screen), `products`, `inventory`, `users`, `cash`, `reports`, `settings`. Each view builder takes `(page, app_state)`.
- `components/nav_rail.py` — left navigation rail, built per-role (visibility driven by `api.is_admin()` / `api.is_manager()`).

### Session/role conventions
- `app_state["session_id"]` / `app_state["session_info"]` track the active cash-register session for the logged-in user. Cashiers can only use a session they personally opened; managers/admins fall back to the first open session if they have none of their own (see `_load_session_info` in `main.py`).
- Permission checks on the frontend mirror `ROLE_PERMISSIONS` in the backend via `api.is_admin()` / `api.is_manager()` — there are three roles: `admin`, `manager`, `cashier`.
