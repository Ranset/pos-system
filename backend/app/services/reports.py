"""
Servicio de generación de reportes financieros
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from ..models import Sale, SaleItem, SaleStatus, PaymentMethod, CashSession, CashMovement, SaleReturn


def get_daily_summary(db: Session, target_date: date) -> dict:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())

    sales = (
        db.query(Sale)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .all()
    )

    completed = [s for s in sales if (s.status or "").lower() in ("completed", "partial_return")]
    cancelled = [s for s in sales if (s.status or "").lower() == "cancelled"]

    total_revenue = sum(s.total for s in completed) or Decimal("0")
    total_tax = sum(s.tax_amount for s in completed) or Decimal("0")
    total_disc = sum(s.discount_amount for s in completed) or Decimal("0")

    cash = sum(s.total for s in completed if s.payment_method == PaymentMethod.CASH) or Decimal("0")
    card = sum(s.total for s in completed if s.payment_method == PaymentMethod.CARD) or Decimal("0")
    transfer = sum(s.total for s in completed if s.payment_method == PaymentMethod.TRANSFER) or Decimal("0")

    # Top 10 productos
    product_totals: dict = {}
    for sale in completed:
        for item in sale.items:
            key = (item.product_code, item.product_name)
            if key not in product_totals:
                product_totals[key] = {"code": item.product_code, "name": item.product_name,
                                       "qty": 0, "total": Decimal("0")}
            product_totals[key]["qty"] += item.quantity
            product_totals[key]["total"] += item.subtotal

    top_products = sorted(product_totals.values(), key=lambda x: x["total"], reverse=True)[:10]
    for p in top_products:
        p["total"] = float(p["total"])

    # Ventas por hora
    hours: dict = {h: 0 for h in range(24)}
    for sale in completed:
        hours[sale.created_at.hour] += 1
    sales_by_hour = [{"hour": h, "count": c} for h, c in hours.items()]

    return {
        "date": str(target_date),
        "total_sales": len(completed),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_discounts": float(total_disc),
        "cash_sales": float(cash),
        "card_sales": float(card),
        "transfer_sales": float(transfer),
        "cancelled_sales": len(cancelled),
        "top_products": top_products,
        "sales_by_hour": sales_by_hour,
    }


def get_session_summary(db: Session, session_id: int) -> dict:
    session = db.query(CashSession).filter(CashSession.id == session_id).first()
    if not session:
        return {}

    from sqlalchemy import text as _text

    def dec(v) -> Decimal:
        return Decimal(str(v or 0))

    # ── Query 1: totales brutos de ventas (sin devoluciones) ─────────────
    sales_row = db.execute(_text("""
        SELECT
            COUNT(*)                                                        AS n_sales,
            COALESCE(SUM(total),         0)                                AS gross_revenue,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='cash'     THEN total ELSE 0 END), 0) AS cash_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='card'     THEN total ELSE 0 END), 0) AS card_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='transfer' THEN total ELSE 0 END), 0) AS transfer_rev,
            COALESCE(SUM(CASE WHEN LOWER(payment_method)='mixed'    THEN total ELSE 0 END), 0) AS mixed_rev,
            COALESCE(SUM(cash_tendered), 0)                                AS cash_tendered,
            COALESCE(SUM(CASE WHEN LOWER(payment_method) IN ('cash','mixed') THEN change_amount ELSE 0 END), 0) AS total_change
        FROM sales
        WHERE session_id = :sid
          AND LOWER(status) IN ('completed', 'partial_return')
    """), {"sid": session.id}).mappings().one()

    n_sales      = int(sales_row["n_sales"] or 0)
    gross        = dec(sales_row["gross_revenue"])
    cash_gross   = dec(sales_row["cash_tendered"])
    total_change = dec(sales_row["total_change"])

    # ── Query 2: devoluciones de las ventas de esta sesión ────────────────
    ret_row = db.execute(_text("""
        SELECT
            COALESCE(SUM(sr.total_returned), 0) AS total_returned,
            COALESCE(SUM(sr.cash_returned),  0) AS cash_returned
        FROM sale_returns sr
        INNER JOIN sales s ON s.id = sr.original_sale_id
        WHERE s.session_id = :sid
    """), {"sid": session.id}).mappings().one()

    total_returned_all = dec(ret_row["total_returned"])
    total_cash_ret     = dec(ret_row["cash_returned"])

    # ── Cálculos netos ────────────────────────────────────────────────────
    # Totales por método (neto = bruto − proporción de devolución por método)
    # Para simplificar: el total neto global se divide por método en proporción
    gross_f  = float(gross) or 1  # evitar división por 0
    ret_f    = float(total_returned_all)
    ret_ratio = ret_f / gross_f if gross_f else 0  # fracción del bruto que se devolvió

    def net_method(method_total: Decimal) -> Decimal:
        """Aproxima el neto por método asumiendo devoluciones proporcionales."""
        return method_total * Decimal(str(1 - ret_ratio))

    total_revenue  = gross - total_returned_all
    cash_revenue   = net_method(dec(sales_row["cash_rev"]))
    card_revenue   = net_method(dec(sales_row["card_rev"]))
    transfer_rev   = net_method(dec(sales_row["transfer_rev"]))
    mixed_revenue  = net_method(dec(sales_row["mixed_rev"]))

    cash_net = cash_gross - total_change - total_cash_ret

    # ── Movimientos manuales ──────────────────────────────────────────────
    cash_in  = sum(m.amount for m in session.movements if m.movement_type.value == "income")  or Decimal("0")
    cash_out = sum(m.amount for m in session.movements if m.movement_type.value == "expense") or Decimal("0")

    opening = session.opening_amount or Decimal("0")
    expected_in_register = opening + cash_net + cash_in - cash_out

    return {
        "total_sales":          n_sales,
        "total_revenue":        float(total_revenue),
        "total_returned":       float(total_returned_all),
        "cash_revenue":         float(cash_revenue),
        "card_revenue":         float(card_revenue),
        "transfer_revenue":     float(transfer_rev),
        "mixed_revenue":        float(mixed_revenue),
        "physical_cash_in":     float(cash_gross),
        "total_change":         float(total_change),
        "total_cash_returned":  float(total_cash_ret),
        "cash_net":             float(cash_net),
        "cash_in":              float(cash_in),
        "cash_out":             float(cash_out),
        "movements_total":      float(cash_in - cash_out),
        "opening_amount":       float(opening),
        "expected_in_register": float(expected_in_register),
    }


def get_daily_summary(db: Session, target_date: date) -> dict:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())

    sales = (
        db.query(Sale)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .all()
    )

    completed = [s for s in sales if (s.status or "").lower() in ("completed", "partial_return")]
    cancelled = [s for s in sales if (s.status or "").lower() == "cancelled"]

    total_revenue = sum(s.total for s in completed) or Decimal("0")
    total_tax = sum(s.tax_amount for s in completed) or Decimal("0")
    total_disc = sum(s.discount_amount for s in completed) or Decimal("0")

    cash = sum(s.total for s in completed if s.payment_method == PaymentMethod.CASH) or Decimal("0")
    card = sum(s.total for s in completed if s.payment_method == PaymentMethod.CARD) or Decimal("0")
    transfer = sum(s.total for s in completed if s.payment_method == PaymentMethod.TRANSFER) or Decimal("0")

    # Top 10 productos
    product_totals: dict = {}
    for sale in completed:
        for item in sale.items:
            key = (item.product_code, item.product_name)
            if key not in product_totals:
                product_totals[key] = {"code": item.product_code, "name": item.product_name,
                                       "qty": 0, "total": Decimal("0")}
            product_totals[key]["qty"] += item.quantity
            product_totals[key]["total"] += item.subtotal

    top_products = sorted(product_totals.values(), key=lambda x: x["total"], reverse=True)[:10]
    for p in top_products:
        p["total"] = float(p["total"])

    # Ventas por hora
    hours: dict = {h: 0 for h in range(24)}
    for sale in completed:
        hours[sale.created_at.hour] += 1
    sales_by_hour = [{"hour": h, "count": c} for h, c in hours.items()]

    return {
        "date": str(target_date),
        "total_sales": len(completed),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_discounts": float(total_disc),
        "cash_sales": float(cash),
        "card_sales": float(card),
        "transfer_sales": float(transfer),
        "cancelled_sales": len(cancelled),
        "top_products": top_products,
        "sales_by_hour": sales_by_hour,
    }


def get_session_summary(db: Session, session_id: int) -> dict:
    session = db.query(CashSession).filter(CashSession.id == session_id).first()
    if not session:
        return {}

    sales = [s for s in session.sales if (s.status or "").lower() in ("completed", "partial_return")]

    # Totales por método de pago
    total_revenue  = sum(s.total         for s in sales) or Decimal("0")
    cash_revenue   = sum(s.total         for s in sales if s.payment_method == PaymentMethod.CASH)     or Decimal("0")
    card_revenue   = sum(s.total         for s in sales if s.payment_method == PaymentMethod.CARD)     or Decimal("0")
    transfer_rev   = sum(s.total         for s in sales if s.payment_method == PaymentMethod.TRANSFER) or Decimal("0")
    mixed_revenue  = sum(s.total         for s in sales if s.payment_method == PaymentMethod.MIXED)    or Decimal("0")

    # Dinero físico que realmente entró a la caja:
    # - efectivo puro:  sale.cash_tendered (= payment_amount, puede tener cambio)
    # - mixto:          sale.cash_tendered (= solo la parte en efectivo, total - parte tarjeta)
    # - tarjeta/transf: $0
    physical_cash_in = sum(
        (s.cash_tendered or Decimal("0")) for s in sales
    ) or Decimal("0")

    # Cambio entregado (sale solo del dinero en caja, reduce el efectivo)
    total_change = sum(
        (s.change_amount or Decimal("0")) for s in sales
        if s.payment_method in (PaymentMethod.CASH, PaymentMethod.MIXED)
    ) or Decimal("0")

    # Movimientos manuales de caja
    cash_in  = sum(m.amount for m in session.movements if m.movement_type.value == "income")  or Decimal("0")
    cash_out = sum(m.amount for m in session.movements if m.movement_type.value == "expense") or Decimal("0")

    # Esperado en caja al cierre:
    # fondo apertura + efectivo de ventas - cambio entregado + entradas - salidas
    opening = session.opening_amount or Decimal("0")
    expected_in_register = opening + physical_cash_in - total_change + cash_in - cash_out

    return {
        "total_sales":          len(sales),
        "total_revenue":        float(total_revenue),
        # Desglose por método
        "cash_revenue":         float(cash_revenue),     # ventas 100% efectivo
        "card_revenue":         float(card_revenue),     # ventas 100% tarjeta
        "transfer_revenue":     float(transfer_rev),     # ventas 100% transferencia
        "mixed_revenue":        float(mixed_revenue),    # ventas mixtas (total)
        # Efectivo físico
        "physical_cash_in":     float(physical_cash_in), # efectivo bruto recibido
        "total_change":         float(total_change),      # cambio entregado
        "cash_net":             float(physical_cash_in - total_change), # efectivo neto
        # Movimientos manuales
        "cash_in":              float(cash_in),
        "cash_out":             float(cash_out),
        "movements_total":      float(cash_in - cash_out),
        # Apertura y esperado final
        "opening_amount":       float(opening),
        "expected_in_register": float(expected_in_register),
    }


def get_range_summary(db: Session, start: date, end: date) -> list:
    results = []
    current = start
    while current <= end:
        results.append(get_daily_summary(db, current))
        current += timedelta(days=1)
    return results
