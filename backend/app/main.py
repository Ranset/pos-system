"""
POS System - FastAPI Backend
Arranca con: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import settings
from .database import Base, engine, SessionLocal
from .models import User, UserRole, CashRegister, Category, ClipPayment   # noqa: F401
from .routers import (
    auth_router, users_router, products_router, categories_router,
    sales_router, cash_router, reports_router, settings_router, admin_router,
    clip_router, clip_webhook_router,
)
from .services.auth import hash_password
from .services.clip_pinpad import ClipPinpadService


from sqlalchemy import text

# ── Startup ───────────────────────────────────────────────────────────────────

def _run_schema_migrations():
    """Aplica migraciones de schema que create_all no maneja.
    Estrategia: intentar el ALTER directamente; si la columna ya existe
    MySQL lanza error 1060 (Duplicate column name) que se ignora."""
    migrations = [
        {
            "name": "sales.cash_tendered",
            "sql":  "ALTER TABLE sales ADD COLUMN cash_tendered "
                    "DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER change_amount",
        },
        {
            # Paso 1: normalizar datos a minúsculas con UPDATE directo.
            # Funciona aunque el ENUM solo tenga valores en mayúsculas
            # porque MySQL almacena el valor real (no el enum label).
            "name": "sales.status datos a minúsculas",
            "sql":  ("UPDATE sales SET status = LOWER(status) "
                     "WHERE BINARY status != LOWER(status)"),
        },
        {
            # Paso 2: convertir columna de ENUM a VARCHAR(30).
            # Con datos ya normalizados, MySQL no rechazará la conversión.
            "name": "sales.status ENUM→VARCHAR",
            "sql":  "ALTER TABLE sales MODIFY COLUMN status VARCHAR(30) NOT NULL DEFAULT 'completed'",
        },
        {
            "name": "sales.commission_pct",
            "sql":  "ALTER TABLE sales ADD COLUMN commission_pct "
                    "FLOAT NOT NULL DEFAULT 0 AFTER cash_tendered",
        },
        {
            "name": "sales.commission_amount",
            "sql":  "ALTER TABLE sales ADD COLUMN commission_amount "
                    "DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER commission_pct",
        },
        {
            "name": "sale_returns table",
            "sql":  ("CREATE TABLE IF NOT EXISTS sale_returns ("
                     "id INT AUTO_INCREMENT PRIMARY KEY,"
                     "original_sale_id INT NOT NULL,"
                     "cashier_id INT NOT NULL,"
                     "supervisor_id INT NOT NULL,"
                     "reason VARCHAR(500),"
                     "total_returned DECIMAL(10,2) NOT NULL DEFAULT 0,"
                     "cash_returned DECIMAL(10,2) NOT NULL DEFAULT 0,"
                     "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                     "FOREIGN KEY (original_sale_id) REFERENCES sales(id),"
                     "FOREIGN KEY (cashier_id) REFERENCES users(id),"
                     "FOREIGN KEY (supervisor_id) REFERENCES users(id))"),
        },
        {
            "name": "sale_return_items table",
            "sql":  ("CREATE TABLE IF NOT EXISTS sale_return_items ("
                     "id INT AUTO_INCREMENT PRIMARY KEY,"
                     "return_id INT NOT NULL,"
                     "product_id INT,"
                     "product_name VARCHAR(150) NOT NULL,"
                     "quantity FLOAT NOT NULL,"
                     "unit_price DECIMAL(10,2) NOT NULL,"
                     "subtotal DECIMAL(10,2) NOT NULL,"
                     "FOREIGN KEY (return_id) REFERENCES sale_returns(id) ON DELETE CASCADE,"
                     "FOREIGN KEY (product_id) REFERENCES products(id))"),
        },
        {
            "name": "clip_terminals table",
            "sql":  ("CREATE TABLE IF NOT EXISTS clip_terminals ("
                     "id INT AUTO_INCREMENT PRIMARY KEY,"
                     "name VARCHAR(80) NOT NULL,"
                     "serial_number VARCHAR(50) NOT NULL UNIQUE,"
                     "is_active BOOLEAN DEFAULT TRUE,"
                     "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                     "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)"),
        },
        {
            "name": "cash_registers.clip_terminal_id",
            "sql":  ("ALTER TABLE cash_registers ADD COLUMN clip_terminal_id INT NULL, "
                     "ADD FOREIGN KEY (clip_terminal_id) REFERENCES clip_terminals(id)"),
        },
        {
            "name": "clip_payments table",
            "sql":  ("CREATE TABLE IF NOT EXISTS clip_payments ("
                     "id INT AUTO_INCREMENT PRIMARY KEY,"
                     "sale_id INT NULL, clip_terminal_id INT NOT NULL, cashier_id INT NOT NULL, session_id INT NULL,"
                     "reference VARCHAR(60) NOT NULL UNIQUE, pinpad_request_id VARCHAR(100), "
                     "transaction_id VARCHAR(100), merchant_id VARCHAR(100), receipt_number VARCHAR(50), "
                     "authorization_code VARCHAR(50), card_brand VARCHAR(30), card_type VARCHAR(30), "
                     "last4 VARCHAR(4), issuer VARCHAR(50), entry_mode VARCHAR(30), "
                     "amount DECIMAL(10,2) NOT NULL, tip_amount DECIMAL(10,2) DEFAULT 0.00, amount_paid DECIMAL(10,2), "
                     "status VARCHAR(20) DEFAULT 'pending', error_message TEXT, sale_payload TEXT, raw_response TEXT, "
                     "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                     "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
                     "approved_at DATETIME, last_synced_at DATETIME,"
                     "FOREIGN KEY (sale_id) REFERENCES sales(id), "
                     "FOREIGN KEY (clip_terminal_id) REFERENCES clip_terminals(id), "
                     "FOREIGN KEY (cashier_id) REFERENCES users(id), "
                     "FOREIGN KEY (session_id) REFERENCES cash_sessions(id))"),
        },
    ]
    with engine.connect() as conn:
        for m in migrations:
            try:
                conn.execute(text(m["sql"]))
                conn.commit()
                print(f"✅ Migración aplicada: {m['name']}")
            except Exception as e:
                err = str(e)
                if "1060" in err or "Duplicate column" in err or "already exists" in err:
                    print(f"   (ok) {m['name']} ya existe")
                else:
                    print(f"⚠️  Migración '{m['name']}': {e}")


async def _clip_reconciliation_loop():
    """Red de seguridad para cobros con Clip que se quedaron en 'pending' sin que
    el polling del frontend ni el webhook los hayan resuelto (ej. el cajero cerró
    la app, o el webhook nunca llegó por no ser el backend alcanzable desde
    internet). Nunca marca nada como aprobado por sí misma — solo reutiliza
    sync_payment, que siempre reconfirma con GET /payment antes de decidir."""
    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                cutoff = datetime.utcnow() - timedelta(seconds=5)
                pending_ids = [
                    p.id for p in db.query(ClipPayment.id)
                    .filter(ClipPayment.status == "pending", ClipPayment.created_at < cutoff)
                    .all()
                ]
                service = ClipPinpadService(db)
                for pid in pending_ids:
                    try:
                        await asyncio.to_thread(service.sync_payment, pid)
                    except Exception as exc:
                        print(f"⚠️  [clip-reconcile] error en pago {pid}: {exc}")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"⚠️  [clip-reconcile] error inesperado en el ciclo: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Con --workers 4, los procesos arrancan en paralelo y pueden pisarse al crear
    # tablas nuevas por primera vez; MySQL responde 1684 ("being modified by
    # concurrent DDL statement") al proceso que pierde la carrera — no es un error
    # real, la tabla la crea el otro worker. Se ignora igual que "ya existe".
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        if "1684" not in str(e):
            raise
        print("   (ok) create_all: tabla en creación por otro worker, se ignora")
    _run_schema_migrations()
    _seed_defaults()
    reconcile_task = asyncio.create_task(_clip_reconciliation_loop())
    yield
    reconcile_task.cancel()


def _seed_defaults():
    """Crea datos iniciales si no existen (idempotente)."""
    db = SessionLocal()
    try:
        # Usuario admin
        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                full_name="Administrador",
                email="admin@pos.local",
                hashed_password=hash_password("admin123"),
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(admin)
            db.commit()
            print("✅ Usuario admin creado: admin / admin123  (CAMBIAR EN PRODUCCION)")

        # Cajas registradoras
        if db.query(CashRegister).count() == 0:
            db.add_all([
                CashRegister(name="Caja Principal", location="Area de ventas", is_active=True),
                CashRegister(name="Caja 2",         location="Area de ventas 2", is_active=True),
            ])
            db.commit()
            print("✅ Cajas creadas: Caja Principal, Caja 2")

        # Categorias de productos
        if db.query(Category).count() == 0:
            db.add_all([
                Category(name="Alimentos",        color="#4CAF50"),
                Category(name="Bebidas",          color="#2196F3"),
                Category(name="Limpieza",         color="#9C27B0"),
                Category(name="Higiene personal", color="#FF9800"),
                Category(name="General",          color="#607D8B"),
            ])
            db.commit()
            print("✅ Categorias de productos creadas")

    except Exception as e:
        print(f"⚠️  Error en seed: {e}")
        db.rollback()
    finally:
        db.close()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="POS System API",
    version="1.0.0",
    description="API para Sistema de Punto de Venta",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Red local – ajustar en prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

# ── Routers ────────────────────────────────────────────────────────────────────

PREFIX = "/api"
app.include_router(auth_router, prefix=PREFIX)
app.include_router(users_router, prefix=PREFIX)
app.include_router(products_router, prefix=PREFIX)
app.include_router(categories_router, prefix=PREFIX)
app.include_router(sales_router, prefix=PREFIX)
app.include_router(cash_router, prefix=PREFIX)
app.include_router(reports_router, prefix=PREFIX)
app.include_router(settings_router, prefix=PREFIX)
app.include_router(admin_router, prefix=PREFIX)
app.include_router(clip_router, prefix=PREFIX)
app.include_router(clip_webhook_router, prefix=PREFIX)


@app.get("/")
def root():
    return {"status": "ok", "app": "POS System API", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
