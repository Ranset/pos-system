"""
Servicio de generación de reportes financieros
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Date, extract, text
from ..models import (
    Sale, SaleItem, SaleStatus, PaymentMethod, CashSession, CashMovement,
    SaleReturn, Product, Category, User, Inventory, InventoryMovement,
)
from ..config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Conversión UTC ↔ hora local
# ─────────────────────────────────────────────────────────────────────────────
# `created_at` / `opened_at` se guardan con datetime.utcnow() (naive UTC), pero
# los reportes deben agruparse y mostrarse según la hora local de la tienda.
# El backend suele correr dentro de un contenedor Docker configurado en UTC,
# por lo que NO podemos confiar en la hora del sistema (datetime.now()):
# el desfase se toma del valor configurado en `settings.TIMEZONE_OFFSET_HOURS`
# (variable de entorno TIMEZONE_OFFSET_HOURS, por defecto -5).

_OFFSET = timedelta(hours=settings.TIMEZONE_OFFSET_HOURS)
_OFFSET_MINUTES = round(_OFFSET.total_seconds() / 60)


def to_local(dt):
    """Convierte un datetime UTC (naive), tal como se guarda en BD, a hora local."""
    if dt is None:
        return dt
    return dt + _OFFSET


def to_utc(dt):
    """Convierte un datetime en hora local (naive) a UTC, para filtrar en BD."""
    if dt is None:
        return dt
    return dt - _OFFSET


def local_dt_expr(column):
    """Expresión SQL que convierte una columna DateTime (UTC) a hora local,
    para usarla en agrupaciones (cast a fecha, extract de mes/año, etc.)."""
    if _OFFSET_MINUTES == 0:
        return column
    if _OFFSET_MINUTES > 0:
        return func.date_add(column, text(f"INTERVAL {_OFFSET_MINUTES} MINUTE"))
    return func.date_sub(column, text(f"INTERVAL {-_OFFSET_MINUTES} MINUTE"))


def get_daily_summary(db: Session, target_date: date) -> dict:
    start = to_utc(datetime.combine(target_date, datetime.min.time()))
    end = to_utc(datetime.combine(target_date, datetime.max.time()))

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
        hours[to_local(sale.created_at).hour] += 1
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
    start = to_utc(datetime.combine(target_date, datetime.min.time()))
    end = to_utc(datetime.combine(target_date, datetime.max.time()))

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
        hours[to_local(sale.created_at).hour] += 1
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


def get_yearly_summary(db: Session, year: int) -> list:
    """Resumen de ventas agrupadas por mes para un año (para gráfica de barras)."""
    rows = (
        db.query(
            extract("month", local_dt_expr(Sale.created_at)).label("month"),
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total), 0).label("total"),
        )
        .filter(
            extract("year", local_dt_expr(Sale.created_at)) == year,
            func.lower(Sale.status).in_(["completed", "partial_return"]),
        )
        .group_by("month")
        .all()
    )
    by_month = {int(r.month): (int(r.count), float(r.total or 0)) for r in rows}
    return [
        {
            "month": m,
            "total_sales": by_month.get(m, (0, 0.0))[0],
            "total_revenue": by_month.get(m, (0, 0.0))[1],
        }
        for m in range(1, 13)
    ]


def get_period_summary(db: Session, start: date, end: date) -> dict:
    """Resumen agregado de un rango de fechas: totales, top productos,
    top categorías y distribución de ventas por hora."""
    start_dt = to_utc(datetime.combine(start, datetime.min.time()))
    end_dt = to_utc(datetime.combine(end, datetime.max.time()))

    sales = (
        db.query(Sale)
        .options(joinedload(Sale.items))
        .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt)
        .all()
    )

    completed = [s for s in sales if (s.status or "").lower() in ("completed", "partial_return")]
    cancelled = [s for s in sales if (s.status or "").lower() == "cancelled"]

    total_revenue = sum(s.total for s in completed) or Decimal("0")
    total_tax = sum(s.tax_amount for s in completed) or Decimal("0")
    total_disc = sum(s.discount_amount for s in completed) or Decimal("0")
    total_items_qty = sum(item.quantity for s in completed for item in s.items) or 0

    cash = sum(s.total for s in completed if s.payment_method == PaymentMethod.CASH) or Decimal("0")
    card = sum(s.total for s in completed if s.payment_method == PaymentMethod.CARD) or Decimal("0")
    transfer = sum(s.total for s in completed if s.payment_method == PaymentMethod.TRANSFER) or Decimal("0")
    mixed = sum(s.total for s in completed if s.payment_method == PaymentMethod.MIXED) or Decimal("0")

    # Mapa producto → categoría (una sola consulta)
    product_ids = {item.product_id for s in completed for item in s.items if item.product_id}
    products_map = {}
    if product_ids:
        products_map = {
            p.id: p
            for p in db.query(Product)
            .options(joinedload(Product.category))
            .filter(Product.id.in_(product_ids))
            .all()
        }

    product_totals: dict = {}
    category_totals: dict = {}
    for sale in completed:
        for item in sale.items:
            key = (item.product_code, item.product_name)
            if key not in product_totals:
                product_totals[key] = {"code": item.product_code, "name": item.product_name,
                                       "qty": 0, "total": Decimal("0")}
            product_totals[key]["qty"] += item.quantity
            product_totals[key]["total"] += item.subtotal

            product = products_map.get(item.product_id)
            cat_name = product.category.name if product and product.category else "Sin categoría"
            if cat_name not in category_totals:
                category_totals[cat_name] = {"name": cat_name, "qty": 0, "total": Decimal("0")}
            category_totals[cat_name]["qty"] += item.quantity
            category_totals[cat_name]["total"] += item.subtotal

    top_products = sorted(product_totals.values(), key=lambda x: x["total"], reverse=True)[:10]
    for p in top_products:
        p["total"] = float(p["total"])

    top_categories = sorted(category_totals.values(), key=lambda x: x["total"], reverse=True)[:10]
    for c in top_categories:
        c["total"] = float(c["total"])

    # Ventas por hora
    hours: dict = {h: 0 for h in range(24)}
    for sale in completed:
        hours[to_local(sale.created_at).hour] += 1
    sales_by_hour = [{"hour": h, "count": c} for h, c in hours.items()]

    return {
        "start": str(start),
        "end": str(end),
        "total_sales": len(completed),
        "total_items": float(total_items_qty),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_discounts": float(total_disc),
        "cash_sales": float(cash),
        "card_sales": float(card),
        "transfer_sales": float(transfer),
        "mixed_sales": float(mixed),
        "cancelled_sales": len(cancelled),
        "top_products": top_products,
        "top_categories": top_categories,
        "sales_by_hour": sales_by_hour,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generador de informes personalizados (vista "Informes")
# ─────────────────────────────────────────────────────────────────────────────

PAYMENT_LABELS = {
    "cash": "Efectivo", "card": "Tarjeta", "transfer": "Transferencia", "mixed": "Mixto",
}
MOVEMENT_LABELS = {"in": "Entrada", "out": "Salida", "adjustment": "Ajuste"}
SALE_STATUS_LABELS = {
    "completed": "Completada", "cancelled": "Cancelada",
    "partial_return": "Devolución parcial", "returned": "Devuelta",
}
SESSION_STATUS_LABELS = {"open": "Abierta", "closed": "Cerrada"}

REPORT_TITLES = {
    "productos":            "Productos vendidos",
    "grupos_productos":     "Grupos de productos",
    "cajeros":              "Ventas por cajero",
    "formas_pago":          "Formas de pago",
    "lista_ventas":         "Lista de ventas",
    "ventas_diarias":       "Ventas diarias",
    "ventas_horas":         "Ventas por hora",
    "ventas_canceladas":    "Ventas canceladas",
    "devoluciones":         "Devoluciones",
    "margen_beneficio":     "Margen de beneficio",
    "efectivo_inicio_caja": "Efectivo en inicio de caja",
    "descuentos_aplicados": "Descuentos aplicados",
    "lista_productos":      "Lista de productos",
    "movimientos_inventario": "Movimientos de inventario",
    "stock_bajo":           "Stock bajo",
}


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _enum_value(v):
    return v.value if hasattr(v, "value") else str(v)


def _range_dt(start: date = None, end: date = None):
    if not start:
        start = date.today().replace(day=1)
    if not end:
        end = date.today()
    return (
        to_utc(datetime.combine(start, datetime.min.time())),
        to_utc(datetime.combine(end, datetime.max.time())),
    )


def _valid_sales_query(db: Session, start_dt, end_dt, cashier_id=None, payment_method=None,
                        statuses=("completed", "partial_return")):
    q = (
        db.query(Sale)
        .options(joinedload(Sale.items))
        .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt)
    )
    if statuses:
        q = q.filter(func.lower(Sale.status).in_(statuses))
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if payment_method:
        q = q.filter(Sale.payment_method == PaymentMethod(payment_method))
    return q


def _users_map(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.query(User).filter(User.id.in_(ids)).all()}


def _build_productos(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    sales = (
        _valid_sales_query(db, start_dt, end_dt, cashier_id, payment_method)
        .options(joinedload(Sale.items).joinedload(SaleItem.product).joinedload(Product.category))
        .all()
    )

    totals: dict = {}
    for s in sales:
        for it in s.items:
            key = (it.product_code, it.product_name)
            row = totals.setdefault(key, {
                "code": it.product_code, "name": it.product_name,
                "category": "Sin categoría", "qty": 0.0, "total": Decimal("0"),
            })
            if it.product and it.product.category:
                row["category"] = it.product.category.name
            row["qty"] += it.quantity
            row["total"] += it.subtotal

    rows = sorted(totals.values(), key=lambda r: r["total"], reverse=True)
    for r in rows:
        r["total"] = float(r["total"])

    columns = [
        {"key": "code", "label": "Código", "type": "text"},
        {"key": "name", "label": "Producto", "type": "text"},
        {"key": "category", "label": "Categoría", "type": "text"},
        {"key": "qty", "label": "Cantidad", "type": "qty"},
        {"key": "total", "label": "Total", "type": "currency"},
    ]
    return columns, rows


def _build_grupos_productos(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    sales = _valid_sales_query(db, start_dt, end_dt, cashier_id, payment_method).all()

    product_ids = {it.product_id for s in sales for it in s.items if it.product_id}
    products_map = {}
    if product_ids:
        products_map = {
            p.id: p
            for p in db.query(Product).options(joinedload(Product.category))
            .filter(Product.id.in_(product_ids)).all()
        }

    totals: dict = {}
    grand_total = Decimal("0")
    for s in sales:
        for it in s.items:
            product = products_map.get(it.product_id)
            cat_name = product.category.name if product and product.category else "Sin categoría"
            row = totals.setdefault(cat_name, {"name": cat_name, "qty": 0.0, "total": Decimal("0")})
            row["qty"] += it.quantity
            row["total"] += it.subtotal
            grand_total += it.subtotal

    rows = sorted(totals.values(), key=lambda r: r["total"], reverse=True)
    for r in rows:
        pct = float(r["total"] / grand_total * 100) if grand_total else 0.0
        r["total"] = float(r["total"])
        r["pct"] = pct

    columns = [
        {"key": "name", "label": "Grupo de productos", "type": "text"},
        {"key": "qty", "label": "Cantidad", "type": "qty"},
        {"key": "total", "label": "Total", "type": "currency"},
        {"key": "pct", "label": "% del total", "type": "percent"},
    ]
    return columns, rows


def _build_cajeros(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = (
        db.query(Sale.cashier_id, func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt,
                func.lower(Sale.status).in_(["completed", "partial_return"]))
    )
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if payment_method:
        q = q.filter(Sale.payment_method == PaymentMethod(payment_method))
    rows_raw = q.group_by(Sale.cashier_id).all()

    users = _users_map(db, [r[0] for r in rows_raw])
    rows = []
    for cid, count, total in rows_raw:
        total_f = float(total or 0)
        rows.append({
            "cashier": users.get(cid, f"Usuario #{cid}"),
            "count": int(count),
            "total": total_f,
            "avg": (total_f / count) if count else 0.0,
        })
    rows.sort(key=lambda r: r["total"], reverse=True)

    columns = [
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "count", "label": "Ventas", "type": "number"},
        {"key": "total", "label": "Total", "type": "currency"},
        {"key": "avg", "label": "Ticket promedio", "type": "currency"},
    ]
    return columns, rows


def _build_formas_pago(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = (
        db.query(Sale.payment_method, func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt,
                func.lower(Sale.status).in_(["completed", "partial_return"]))
    )
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    rows_raw = q.group_by(Sale.payment_method).all()

    grand_total = sum(float(r[2] or 0) for r in rows_raw) or 0.0
    rows = []
    for method, count, total in rows_raw:
        total_f = float(total or 0)
        method_val = _enum_value(method)
        rows.append({
            "method": PAYMENT_LABELS.get(method_val, method_val),
            "count": int(count),
            "total": total_f,
            "pct": (total_f / grand_total * 100) if grand_total else 0.0,
        })
    rows.sort(key=lambda r: r["total"], reverse=True)

    columns = [
        {"key": "method", "label": "Forma de pago", "type": "text"},
        {"key": "count", "label": "Ventas", "type": "number"},
        {"key": "total", "label": "Total", "type": "currency"},
        {"key": "pct", "label": "% del total", "type": "percent"},
    ]
    return columns, rows


def _build_lista_ventas(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = db.query(Sale).filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt)
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if payment_method:
        q = q.filter(Sale.payment_method == PaymentMethod(payment_method))
    sales = q.order_by(Sale.created_at.desc()).all()

    users = _users_map(db, [s.cashier_id for s in sales])
    rows = []
    for s in sales:
        method_val = _enum_value(s.payment_method)
        rows.append({
            "folio": s.folio,
            "date": to_local(s.created_at).isoformat() if s.created_at else "",
            "cashier": users.get(s.cashier_id, f"Usuario #{s.cashier_id}"),
            "method": PAYMENT_LABELS.get(method_val, method_val),
            "subtotal": float(s.subtotal or 0),
            "discount": float(s.discount_amount or 0),
            "tax": float(s.tax_amount or 0),
            "total": float(s.total or 0),
            "status": SALE_STATUS_LABELS.get((s.status or "").lower(), s.status),
        })

    columns = [
        {"key": "folio", "label": "Folio", "type": "text"},
        {"key": "date", "label": "Fecha", "type": "datetime"},
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "method", "label": "Forma de pago", "type": "text"},
        {"key": "subtotal", "label": "Subtotal", "type": "currency"},
        {"key": "discount", "label": "Descuento", "type": "currency"},
        {"key": "tax", "label": "Impuesto", "type": "currency"},
        {"key": "total", "label": "Total", "type": "currency"},
        {"key": "status", "label": "Estado", "type": "text"},
    ]
    return columns, rows


def _build_ventas_diarias(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = (
        db.query(
            cast(local_dt_expr(Sale.created_at), Date).label("day"),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total), 0),
            func.coalesce(func.sum(Sale.tax_amount), 0),
            func.coalesce(func.sum(Sale.discount_amount), 0),
        )
        .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt,
                func.lower(Sale.status).in_(["completed", "partial_return"]))
    )
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if payment_method:
        q = q.filter(Sale.payment_method == PaymentMethod(payment_method))
    rows_raw = q.group_by("day").order_by("day").all()

    rows = []
    for day, count, total, tax, disc in rows_raw:
        total_f = float(total or 0)
        rows.append({
            "date": str(day),
            "count": int(count),
            "total": total_f,
            "tax": float(tax or 0),
            "discount": float(disc or 0),
            "avg": (total_f / count) if count else 0.0,
        })

    columns = [
        {"key": "date", "label": "Fecha", "type": "date"},
        {"key": "count", "label": "Ventas", "type": "number"},
        {"key": "total", "label": "Ingresos", "type": "currency"},
        {"key": "tax", "label": "Impuesto", "type": "currency"},
        {"key": "discount", "label": "Descuentos", "type": "currency"},
        {"key": "avg", "label": "Ticket promedio", "type": "currency"},
    ]
    return columns, rows


def _build_ventas_horas(db, start, end, target_date, cashier_id, payment_method):
    d = target_date or date.today()
    start_dt = to_utc(datetime.combine(d, datetime.min.time()))
    end_dt = to_utc(datetime.combine(d, datetime.max.time()))
    sales = _valid_sales_query(db, start_dt, end_dt, cashier_id, payment_method).all()

    hours = {h: {"count": 0, "total": Decimal("0")} for h in range(24)}
    for s in sales:
        h = to_local(s.created_at).hour
        hours[h]["count"] += 1
        hours[h]["total"] += s.total

    rows = [
        {"hour": f"{h:02d}:00", "count": hours[h]["count"], "total": float(hours[h]["total"])}
        for h in range(24)
    ]

    columns = [
        {"key": "hour", "label": "Hora", "type": "text"},
        {"key": "count", "label": "Ventas", "type": "number"},
        {"key": "total", "label": "Total", "type": "currency"},
    ]
    return columns, rows


def _build_ventas_canceladas(db, start, end, target_date, cashier_id, payment_method):
    import re as _re
    start_dt, end_dt = _range_dt(start, end)
    q = db.query(Sale).filter(
        Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        func.lower(Sale.status) == "cancelled",
    )
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    sales = q.order_by(Sale.created_at.desc()).all()

    users = _users_map(db, [s.cashier_id for s in sales])
    rows = []
    for s in sales:
        notes = s.notes or ""
        reason = notes
        m = _re.search(r"CANCELADA por usuario \d+: (.+?)(?:\s*\||$)", notes)
        if m:
            reason = m.group(1).strip()
        rows.append({
            "folio": s.folio,
            "date": to_local(s.created_at).isoformat() if s.created_at else "",
            "cashier": users.get(s.cashier_id, f"Usuario #{s.cashier_id}"),
            "total": float(s.total or 0),
            "reason": reason,
        })

    columns = [
        {"key": "folio", "label": "Folio", "type": "text"},
        {"key": "date", "label": "Fecha", "type": "datetime"},
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "total", "label": "Total", "type": "currency"},
        {"key": "reason", "label": "Motivo", "type": "text"},
    ]
    return columns, rows


def _build_devoluciones(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = (
        db.query(SaleReturn)
        .options(
            joinedload(SaleReturn.original_sale),
            joinedload(SaleReturn.cashier),
            joinedload(SaleReturn.supervisor),
        )
        .filter(SaleReturn.created_at >= start_dt, SaleReturn.created_at <= end_dt)
    )
    if cashier_id:
        q = q.filter(SaleReturn.cashier_id == cashier_id)
    returns = q.order_by(SaleReturn.created_at.desc()).all()

    rows = []
    for r in returns:
        rows.append({
            "date": to_local(r.created_at).isoformat() if r.created_at else "",
            "folio": r.original_sale.folio if r.original_sale else "",
            "cashier": r.cashier.full_name if r.cashier else "",
            "supervisor": r.supervisor.full_name if r.supervisor else "",
            "reason": r.reason or "",
            "total": float(r.total_returned or 0),
        })

    columns = [
        {"key": "date", "label": "Fecha", "type": "datetime"},
        {"key": "folio", "label": "Folio venta", "type": "text"},
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "supervisor", "label": "Supervisor", "type": "text"},
        {"key": "reason", "label": "Motivo", "type": "text"},
        {"key": "total", "label": "Total devuelto", "type": "currency"},
    ]
    return columns, rows


def _build_margen_beneficio(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    sales = _valid_sales_query(db, start_dt, end_dt, cashier_id, payment_method).all()

    product_ids = {it.product_id for s in sales for it in s.items if it.product_id}
    products_map = {}
    if product_ids:
        products_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    totals: dict = {}
    for s in sales:
        for it in s.items:
            key = (it.product_code, it.product_name)
            row = totals.setdefault(key, {"name": it.product_name, "qty": 0.0,
                                          "revenue": Decimal("0"), "cost": Decimal("0")})
            row["qty"] += it.quantity
            row["revenue"] += it.subtotal
            product = products_map.get(it.product_id)
            cost_unit = product.cost if product and product.cost else Decimal("0")
            row["cost"] += _dec(cost_unit) * Decimal(str(it.quantity))

    rows = []
    for r in totals.values():
        margin = r["revenue"] - r["cost"]
        margin_pct = float(margin / r["revenue"] * 100) if r["revenue"] else 0.0
        rows.append({
            "name": r["name"], "qty": r["qty"],
            "revenue": float(r["revenue"]), "cost": float(r["cost"]),
            "margin": float(margin), "margin_pct": margin_pct,
        })
    rows.sort(key=lambda r: r["margin"], reverse=True)

    columns = [
        {"key": "name", "label": "Producto", "type": "text"},
        {"key": "qty", "label": "Cantidad", "type": "qty"},
        {"key": "revenue", "label": "Ingresos", "type": "currency"},
        {"key": "cost", "label": "Costo", "type": "currency"},
        {"key": "margin", "label": "Margen", "type": "currency"},
        {"key": "margin_pct", "label": "Margen %", "type": "percent"},
    ]
    return columns, rows


def _build_efectivo_inicio_caja(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = (
        db.query(CashSession)
        .options(joinedload(CashSession.register), joinedload(CashSession.cashier))
        .filter(CashSession.opened_at >= start_dt, CashSession.opened_at <= end_dt)
    )
    if cashier_id:
        q = q.filter(CashSession.cashier_id == cashier_id)
    sessions = q.order_by(CashSession.opened_at.desc()).all()

    rows = []
    for s in sessions:
        status_val = _enum_value(s.status)
        rows.append({
            "date": to_local(s.opened_at).isoformat() if s.opened_at else "",
            "register": s.register.name if s.register else "",
            "cashier": s.cashier.full_name if s.cashier else "",
            "opening": float(s.opening_amount or 0),
            "status": SESSION_STATUS_LABELS.get(status_val, status_val),
        })

    columns = [
        {"key": "date", "label": "Fecha de apertura", "type": "datetime"},
        {"key": "register", "label": "Caja", "type": "text"},
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "opening", "label": "Fondo inicial", "type": "currency"},
        {"key": "status", "label": "Estado", "type": "text"},
    ]
    return columns, rows


def _build_descuentos_aplicados(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    q = db.query(Sale).filter(
        Sale.created_at >= start_dt, Sale.created_at <= end_dt,
        func.lower(Sale.status).in_(["completed", "partial_return"]),
        Sale.discount_amount > 0,
    )
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    if payment_method:
        q = q.filter(Sale.payment_method == PaymentMethod(payment_method))
    sales = q.order_by(Sale.created_at.desc()).all()

    users = _users_map(db, [s.cashier_id for s in sales])
    rows = []
    for s in sales:
        subtotal = float(s.subtotal or 0)
        discount = float(s.discount_amount or 0)
        rows.append({
            "folio": s.folio,
            "date": s.created_at.isoformat() if s.created_at else "",
            "cashier": users.get(s.cashier_id, f"Usuario #{s.cashier_id}"),
            "subtotal": subtotal,
            "discount": discount,
            "discount_pct": (discount / subtotal * 100) if subtotal else 0.0,
            "total": float(s.total or 0),
        })

    columns = [
        {"key": "folio", "label": "Folio", "type": "text"},
        {"key": "date", "label": "Fecha", "type": "datetime"},
        {"key": "cashier", "label": "Cajero", "type": "text"},
        {"key": "subtotal", "label": "Subtotal", "type": "currency"},
        {"key": "discount", "label": "Descuento", "type": "currency"},
        {"key": "discount_pct", "label": "% Descuento", "type": "percent"},
        {"key": "total", "label": "Total", "type": "currency"},
    ]
    return columns, rows


def _build_lista_productos(db, start, end, target_date, cashier_id, payment_method):
    products = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.inventory))
        .filter(Product.is_active.is_(True))
        .order_by(Product.name)
        .all()
    )

    rows = []
    for p in products:
        inv = p.inventory
        rows.append({
            "code": p.code,
            "name": p.name,
            "description": p.description or "",
            "category": p.category.name if p.category else "Sin categoría",
            "stock": float(inv.quantity) if inv else 0.0,
            "min_stock": float(inv.min_stock) if inv else 0.0,
            "max_stock": float(inv.max_stock) if inv else 0.0,
            "cost": float(p.cost or 0),
            "price": float(p.price or 0),
        })

    columns = [
        {"key": "code",        "label": "Código",      "type": "text"},
        {"key": "name",        "label": "Producto",    "type": "text"},
        {"key": "description", "label": "Descripción", "type": "text"},
        {"key": "category",    "label": "Categoría",   "type": "text"},
        {"key": "stock",       "label": "Stock",       "type": "qty"},
        {"key": "min_stock",   "label": "Stock mín.",  "type": "qty"},
        {"key": "max_stock",   "label": "Stock máx.",  "type": "qty"},
        {"key": "cost",        "label": "Costo",       "type": "currency"},
        {"key": "price",       "label": "Precio",      "type": "currency"},
    ]
    return columns, rows


def _build_movimientos_inventario(db, start, end, target_date, cashier_id, payment_method):
    start_dt, end_dt = _range_dt(start, end)
    movs = (
        db.query(InventoryMovement)
        .options(
            joinedload(InventoryMovement.inventory).joinedload(Inventory.product),
            joinedload(InventoryMovement.user),
        )
        .filter(InventoryMovement.created_at >= start_dt, InventoryMovement.created_at <= end_dt)
        .order_by(InventoryMovement.created_at.desc())
        .all()
    )

    rows = []
    for m in movs:
        product = m.inventory.product if m.inventory else None
        rows.append({
            "date": to_local(m.created_at).isoformat() if m.created_at else "",
            "product": product.name if product else "",
            "type": MOVEMENT_LABELS.get(m.movement_type, m.movement_type),
            "qty": float(m.quantity),
            "previous": float(m.previous_quantity),
            "new": float(m.new_quantity),
            "reason": m.reason or "",
            "user": m.user.full_name if m.user else "",
        })

    columns = [
        {"key": "date", "label": "Fecha", "type": "datetime"},
        {"key": "product", "label": "Producto", "type": "text"},
        {"key": "type", "label": "Tipo", "type": "text"},
        {"key": "qty", "label": "Cantidad", "type": "qty"},
        {"key": "previous", "label": "Stock anterior", "type": "qty"},
        {"key": "new", "label": "Stock nuevo", "type": "qty"},
        {"key": "reason", "label": "Motivo", "type": "text"},
        {"key": "user", "label": "Usuario", "type": "text"},
    ]
    return columns, rows


def _build_stock_bajo(db, start, end, target_date, cashier_id, payment_method):
    rows_raw = (
        db.query(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .options(joinedload(Product.category))
        .filter(Product.is_active.is_(True), Inventory.quantity <= Inventory.min_stock)
        .order_by(Product.name)
        .all()
    )

    rows = []
    for p, inv in rows_raw:
        rows.append({
            "code": p.code,
            "name": p.name,
            "category": p.category.name if p.category else "Sin categoría",
            "stock": float(inv.quantity),
            "min_stock": float(inv.min_stock),
            "diff": float(inv.quantity - inv.min_stock),
        })

    columns = [
        {"key": "code", "label": "Código", "type": "text"},
        {"key": "name", "label": "Producto", "type": "text"},
        {"key": "category", "label": "Categoría", "type": "text"},
        {"key": "stock", "label": "Stock actual", "type": "qty"},
        {"key": "min_stock", "label": "Stock mínimo", "type": "qty"},
        {"key": "diff", "label": "Diferencia", "type": "qty"},
    ]
    return columns, rows


_REPORT_BUILDERS = {
    "productos": _build_productos,
    "grupos_productos": _build_grupos_productos,
    "cajeros": _build_cajeros,
    "formas_pago": _build_formas_pago,
    "lista_ventas": _build_lista_ventas,
    "ventas_diarias": _build_ventas_diarias,
    "ventas_horas": _build_ventas_horas,
    "ventas_canceladas": _build_ventas_canceladas,
    "devoluciones": _build_devoluciones,
    "margen_beneficio": _build_margen_beneficio,
    "efectivo_inicio_caja": _build_efectivo_inicio_caja,
    "descuentos_aplicados": _build_descuentos_aplicados,
    "lista_productos": _build_lista_productos,
    "movimientos_inventario": _build_movimientos_inventario,
    "stock_bajo": _build_stock_bajo,
}


def generate_custom_report(db: Session, report_type: str, start: date = None, end: date = None,
                            target_date: date = None, cashier_id: int = None,
                            payment_method: str = None) -> dict:
    """Genera un informe personalizado según el tipo solicitado, devolviendo
    columnas (con tipo de dato para el formateo en frontend) y filas."""
    builder = _REPORT_BUILDERS.get(report_type)
    if not builder:
        raise ValueError(f"Tipo de informe desconocido: {report_type}")

    columns, rows = builder(db, start, end, target_date, cashier_id, payment_method)
    return {
        "report_type": report_type,
        "title": REPORT_TITLES[report_type],
        "columns": columns,
        "rows": rows,
    }
