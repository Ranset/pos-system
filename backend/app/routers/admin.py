"""
Router de administración de base de datos.
Operaciones destructivas — solo administradores.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..database import get_db, engine
from ..models import Sale, SaleItem, CashSession, CashMovement, InventoryMovement
from ..services.auth import require_admin

router = APIRouter(prefix="/admin", tags=["Administración"])


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
