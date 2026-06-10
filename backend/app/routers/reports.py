from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.auth import require_manager, require_cashier
from ..services.reports import (
    get_daily_summary, get_session_summary, get_range_summary,
    get_yearly_summary, get_period_summary,
)

router = APIRouter(prefix="/reports", tags=["Reportes"])


@router.get("/daily")
def daily_report(
    target_date: date = Query(default=date.today()),
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    return get_daily_summary(db, target_date)


@router.get("/range")
def range_report(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    if (end - start).days > 31:
        from fastapi import HTTPException
        raise HTTPException(400, "El rango máximo es de 31 días")
    return get_range_summary(db, start, end)


@router.get("/monthly")
def monthly_report(
    year: int = Query(default=date.today().year),
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    """Resumen de ventas agrupadas por mes para un año (gráfica de ventas mensuales)."""
    return get_yearly_summary(db, year)


@router.get("/period")
def period_report(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    """Resumen agregado de un rango de fechas: top productos, top categorías y ventas por hora."""
    if (end - start).days > 366:
        from fastapi import HTTPException
        raise HTTPException(400, "El rango máximo es de 366 días")
    return get_period_summary(db, start, end)


@router.get("/debug/session-returns/{session_id}")
def debug_session_returns(session_id: int, db: Session = Depends(get_db)):
    """Endpoint de diagnóstico: muestra las devoluciones de una sesión directamente de la BD."""
    from sqlalchemy import text as _t
    rows = db.execute(_t("""
        SELECT sr.id, sr.original_sale_id, sr.total_returned, sr.cash_returned,
               sr.reason, s.session_id, s.total AS sale_total, s.status AS sale_status
        FROM sale_returns sr
        JOIN sales s ON s.id = sr.original_sale_id
        WHERE s.session_id = :sid
    """), {"sid": session_id}).mappings().all()
    return {
        "session_id":   session_id,
        "returns_count": len(rows),
        "returns": [dict(r) for r in rows],
    }


@router.get("/session/{session_id}")
def session_report(
    session_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    """Resumen financiero de una sesión de caja.
    Cálculo inline para evitar problemas de caché de módulos Python."""
    from sqlalchemy import text as _t
    from decimal import Decimal
    from ..models import CashSession

    session = db.query(CashSession).filter(CashSession.id == session_id).first()
    if not session:
        return {}

    def dec(v) -> Decimal:
        return Decimal(str(v or 0))

    # ── Query 1: ventas válidas de la sesión ──────────────────────────────
    s1 = db.execute(_t("""
        SELECT
            COUNT(*)                                                                  AS n_sales,
            COALESCE(SUM(total), 0)                                                  AS gross,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='cash'     THEN total ELSE 0 END),0) AS cash_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='card'     THEN total ELSE 0 END),0) AS card_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='transfer' THEN total ELSE 0 END),0) AS transfer_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='mixed'    THEN total ELSE 0 END),0) AS mixed_rev,
            COALESCE(SUM(cash_tendered), 0)                                          AS cash_tendered,
            COALESCE(SUM(CASE WHEN LOWER(payment_method) IN ('cash','mixed')
                         THEN change_amount ELSE 0 END), 0)                          AS total_change
        FROM sales
        WHERE session_id = :sid
          AND LOWER(status) IN ('completed', 'partial_return')
    """), {"sid": session_id}).mappings().one()

    # ── Query 2: devoluciones de ventas de esta sesión ────────────────────
    s2 = db.execute(_t("""
        SELECT
            COALESCE(SUM(sr.total_returned), 0) AS total_returned,
            COALESCE(SUM(sr.cash_returned),  0) AS cash_returned
        FROM sale_returns sr
        INNER JOIN sales s ON s.id = sr.original_sale_id
        WHERE s.session_id = :sid
    """), {"sid": session_id}).mappings().one()

    gross            = dec(s1["gross"])
    total_returned   = dec(s2["total_returned"])
    cash_returned    = dec(s2["cash_returned"])
    cash_tendered    = dec(s1["cash_tendered"])
    total_change     = dec(s1["total_change"])

    total_revenue    = gross - total_returned
    cash_net         = cash_tendered - total_change - cash_returned

    # Desglose neto por método (proporcional a la devolución)
    ratio = float(total_returned) / max(float(gross), 0.01) if gross else 0
    def net(v): return dec(v) * Decimal(str(1 - ratio))

    # Movimientos manuales
    cash_in  = sum(m.amount for m in session.movements if m.movement_type.value == "income")  or Decimal("0")
    cash_out = sum(m.amount for m in session.movements if m.movement_type.value == "expense") or Decimal("0")

    opening  = session.opening_amount or Decimal("0")
    expected = opening + cash_net + cash_in - cash_out

    # ── Detalle de movimientos manuales ──────────────────────────────────
    income_detail  = []
    expense_detail = []
    for m in session.movements:
        entry = {
            "time":   m.created_at.strftime("%H:%M:%S") if m.created_at else "",
            "amount": float(m.amount),
            "reason": m.reason or "",
        }
        if m.movement_type.value == "income":
            income_detail.append(entry)
        else:
            expense_detail.append(entry)

    # ── Detalle de devoluciones ───────────────────────────────────────────
    ret_detail = []
    ret_rows = db.execute(_t("""
        SELECT sr.id, sr.reason, sr.total_returned, sr.created_at,
               s.folio, u.full_name AS supervisor_name
        FROM   sale_returns sr
        JOIN   sales s ON s.id = sr.original_sale_id
        JOIN   users u ON u.id = sr.supervisor_id
        WHERE  s.session_id = :sid
        ORDER  BY sr.created_at
    """), {"sid": session_id}).mappings().all()

    for r in ret_rows:
        items_q = db.execute(_t("""
            SELECT product_name, quantity, subtotal
            FROM   sale_return_items
            WHERE  return_id = :rid
        """), {"rid": r["id"]}).mappings().all()
        ret_detail.append({
            "time":           r["created_at"].strftime("%H:%M:%S") if r["created_at"] else "",
            "folio":          r["folio"] or "",
            "supervisor":     r["supervisor_name"] or "—",
            "reason":         r["reason"] or "",
            "total_returned": float(r["total_returned"] or 0),
            "items": [{"name": i["product_name"], "qty": float(i["quantity"]),
                       "subtotal": float(i["subtotal"])} for i in items_q],
        })

    # ── Detalle de cancelaciones ──────────────────────────────────────────
    cancel_detail = []
    cancel_rows = db.execute(_t("""
        SELECT s.id, s.folio, s.total, s.notes, s.created_at
        FROM   sales s
        WHERE  s.session_id = :sid AND LOWER(s.status) = 'cancelled'
        ORDER  BY s.created_at
    """), {"sid": session_id}).mappings().all()

    import re as _re
    for c in cancel_rows:
        items_q = db.execute(_t("""
            SELECT product_name, quantity, subtotal
            FROM   sale_items WHERE sale_id = :sid2
        """), {"sid2": c["id"]}).mappings().all()

        # Extraer supervisor y motivo del campo notes
        notes = c["notes"] or ""
        supervisor_c = "—"
        reason_c = "—"
        m = _re.search(r"CANCELADA por usuario (\d+): (.+?)(?:\s*\||$)", notes)
        if m:
            try:
                u = db.execute(_t("SELECT full_name FROM users WHERE id=:uid"),
                               {"uid": int(m.group(1))}).fetchone()
                if u:
                    supervisor_c = u[0]
            except Exception:
                pass
            reason_c = m.group(2).strip()

        cancel_detail.append({
            "time":      c["created_at"].strftime("%H:%M:%S") if c["created_at"] else "",
            "folio":     c["folio"] or "",
            "total":     float(c["total"] or 0),
            "supervisor": supervisor_c,
            "reason":    reason_c,
            "items": [{"name": i["product_name"], "qty": float(i["quantity"]),
                       "subtotal": float(i["subtotal"])} for i in items_q],
        })

    return {
        "total_sales":          int(s1["n_sales"] or 0),
        "total_revenue":        float(total_revenue),
        "total_returned":       float(total_returned),
        "cash_revenue":         float(net(s1["cash_rev"])),
        "card_revenue":         float(net(s1["card_rev"])),
        "transfer_revenue":     float(net(s1["transfer_rev"])),
        "mixed_revenue":        float(net(s1["mixed_rev"])),
        "physical_cash_in":     float(cash_tendered),
        "total_change":         float(total_change),
        "total_cash_returned":  float(cash_returned),
        "cash_net":             float(cash_net),
        "cash_in":              float(cash_in),
        "cash_out":             float(cash_out),
        "movements_total":      float(cash_in - cash_out),
        "opening_amount":       float(opening),
        "expected_in_register": float(expected),
        # Detalles para el ticket de cierre
        "income_detail":        income_detail,
        "expense_detail":       expense_detail,
        "returns_detail":       ret_detail,
        "cancellations_detail": cancel_detail,
    }
