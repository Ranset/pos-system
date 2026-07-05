"""
POS System - FastAPI Backend
Arranca con: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import settings
from .database import Base, engine, SessionLocal
from .models import User, UserRole, CashRegister, Category   # noqa: F401
from .routers import (
    auth_router, users_router, products_router, categories_router,
    sales_router, cash_router, reports_router, settings_router, admin_router,
)
from .services.auth import hash_password


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _run_schema_migrations()
    _seed_defaults()
    yield


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


@app.get("/")
def root():
    return {"status": "ok", "app": "POS System API", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
