"""
Router de administración de base de datos.
Operaciones destructivas — solo administradores.
"""
import os
import subprocess
import tempfile
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..database import get_db, engine
from ..models import Sale, SaleItem, CashSession, CashMovement, InventoryMovement
from ..services.auth import require_admin
from ..config import settings

router = APIRouter(prefix="/admin", tags=["Administración"])

# Tiempo máximo (segundos) para el respaldo/restauración vía mysqldump/mysql.
_DUMP_TIMEOUT = 300


@router.post("/force-migrate")
def force_migrate(_=Depends(require_admin)):
    """Aplica todas las migraciones de schema pendientes sin necesidad de reiniciar.
    Idempotente: si la columna ya existe, lo ignora."""
    MIGRATIONS = [
        {
            "name": "sales.cash_tendered",
            "sql":  "ALTER TABLE sales ADD COLUMN cash_tendered "
                    "DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER change_amount",
        },
        {
            "name": "sales.status → VARCHAR (fix case mismatch)",
            "sql":  "ALTER TABLE sales MODIFY COLUMN status VARCHAR(30) NOT NULL DEFAULT 'completed'",
        },
        {
            "name": "sales.status normalizar a minúsculas",
            "sql":  "UPDATE sales SET status = LOWER(status) WHERE status != LOWER(status)",
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
    results = []
    with engine.connect() as conn:
        for m in MIGRATIONS:
            try:
                conn.execute(text(m["sql"]))
                conn.commit()
                results.append({"migration": m["name"], "status": "applied"})
            except Exception as e:
                err = str(e)
                if "1060" in err or "Duplicate column" in err or "already exists" in err:
                    results.append({"migration": m["name"], "status": "already_exists"})
                else:
                    results.append({"migration": m["name"], "status": "error", "detail": err})
    return {"results": results}


@router.get("/stats")
def db_stats(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Conteo de registros en cada tabla principal."""
    return {
        "sales":          db.query(Sale).count(),
        "sale_items":     db.query(SaleItem).count(),
        "sessions":       db.query(CashSession).count(),
        "cash_movements": db.query(CashMovement).count(),
        "inv_movements":  db.query(InventoryMovement).count(),
    }


@router.delete("/sales")
def delete_all_sales(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Elimina todas las ventas y sus registros relacionados.
    Orden: return_items → returns → sale_items → sales (respeta FK constraints).
    Las sesiones de caja y el inventario actual NO se modifican."""
    from ..models import SaleReturn, SaleReturnItem
    return_items_del = db.query(SaleReturnItem).delete(synchronize_session=False)
    returns_del      = db.query(SaleReturn).delete(synchronize_session=False)
    items_del        = db.query(SaleItem).delete(synchronize_session=False)
    sales_del        = db.query(Sale).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_sales":         sales_del,
        "deleted_sale_items":    items_del,
        "deleted_returns":       returns_del,
        "deleted_return_items":  return_items_del,
        "message": f"Se eliminaron {sales_del} ventas, {returns_del} devoluciones y {items_del} líneas de detalle.",
    }


@router.delete("/sessions")
def delete_all_sessions(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Elimina todas las sesiones de caja y sus movimientos de dinero.
    Requiere que no haya ventas asociadas a las sesiones (eliminar ventas primero)."""
    movements_del = db.query(CashMovement).delete(synchronize_session=False)
    sessions_del  = db.query(CashSession).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_sessions":  sessions_del,
        "deleted_movements": movements_del,
        "message": f"Se eliminaron {sessions_del} sesiones y {movements_del} movimientos.",
    }


@router.delete("/inventory-movements")
def delete_inventory_movements(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Elimina el historial de movimientos de inventario.
    El stock actual de los productos NO cambia."""
    deleted = db.query(InventoryMovement).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": deleted,
        "message": f"Se eliminaron {deleted} movimientos de inventario.",
    }


@router.delete("/all")
def full_reset(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Reset completo: elimina ventas, sesiones y movimientos de inventario.
    Usuarios, productos, categorías y configuración se conservan."""
    inv_del  = db.query(InventoryMovement).delete(synchronize_session=False)
    items_del= db.query(SaleItem).delete(synchronize_session=False)
    sales_del= db.query(Sale).delete(synchronize_session=False)
    mov_del  = db.query(CashMovement).delete(synchronize_session=False)
    sess_del = db.query(CashSession).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_sales":            sales_del,
        "deleted_sale_items":       items_del,
        "deleted_sessions":         sess_del,
        "deleted_cash_movements":   mov_del,
        "deleted_inv_movements":    inv_del,
        "message": (
            f"Reset completo: {sales_del} ventas, {sess_del} sesiones, "
            f"{inv_del} mov. inventario eliminados."
        ),
    }


@router.get("/backup")
def backup_database(_=Depends(require_admin)):
    """Genera un respaldo completo de la base de datos (mysqldump) y lo
    devuelve como archivo .sql descargable. Incluye esquema y datos."""
    env = os.environ.copy()
    env["MYSQL_PWD"] = settings.DB_PASSWORD
    cmd = [
        "mysqldump",
        "-h", settings.DB_HOST,
        "-P", str(settings.DB_PORT),
        "-u", settings.DB_USER,
        "--ssl=0",
        "--single-transaction",
        "--routines",
        "--triggers",
        settings.DB_NAME,
    ]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, timeout=_DUMP_TIMEOUT)
    except FileNotFoundError:
        raise HTTPException(
            500,
            "mysqldump no está instalado en el contenedor del backend. "
            "Reconstruye la imagen: docker-compose build backend && docker-compose up -d backend",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "El respaldo tardó demasiado y fue cancelado (timeout)")

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[:500]
        raise HTTPException(500, f"Error al generar el respaldo: {detail}")

    filename = f"pos_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sql"
    return Response(
        content=result.stdout,
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
def restore_database(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Restaura la base de datos completa a partir de un archivo .sql de
    respaldo generado por /admin/backup. SOBRESCRIBE todos los datos actuales
    (el dump de mysqldump incluye DROP TABLE + CREATE TABLE para cada tabla).
    Definido como `def` (no `async def`): subprocess.run() es bloqueante, y
    FastAPI ejecuta los endpoints síncronos en un threadpool en vez del loop
    de asyncio, evitando congelar el resto de las peticiones del worker."""
    content = file.file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío")

    # La dependencia require_admin/get_current_user deja abierta (hasta el
    # final de la petición) una transacción de solo lectura sobre `users`
    # para verificar el rol. Como el restore necesita bloquear esa misma
    # tabla exclusivamente (DROP+CREATE), hay que liberar ese lock ahora;
    # de lo contrario esta misma petición se autobloquea contra sí misma.
    db.close()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        env = os.environ.copy()
        env["MYSQL_PWD"] = settings.DB_PASSWORD
        cmd = [
            "mysql",
            "-h", settings.DB_HOST,
            "-P", str(settings.DB_PORT),
            "-u", settings.DB_USER,
            "--ssl=0",
            # Si otro cliente POS conectado mantiene un bloqueo sobre alguna
            # tabla, fallar rápido con un error claro en vez de colgar la
            # petición varios minutos.
            "--init-command=SET SESSION lock_wait_timeout=15",
            settings.DB_NAME,
        ]
        with open(tmp_path, "rb") as f:
            result = subprocess.run(cmd, env=env, stdin=f, capture_output=True, timeout=_DUMP_TIMEOUT)
    except FileNotFoundError:
        raise HTTPException(
            500,
            "El cliente 'mysql' no está instalado en el contenedor del backend. "
            "Reconstruye la imagen: docker-compose build backend && docker-compose up -d backend",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "La restauración tardó demasiado y fue cancelada (timeout)")
    finally:
        if tmp_path:
            os.unlink(tmp_path)

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[:500]
        raise HTTPException(500, f"Error al restaurar el respaldo: {detail}")

    return {"message": "Base de datos restaurada correctamente desde el respaldo"}
