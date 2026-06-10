from typing import List, Optional
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Sale, SaleItem, SaleStatus, PaymentMethod, Product, Inventory, InventoryMovement, CashSession
from ..schemas import SaleOut, SaleCreate
from ..services.auth import require_cashier, require_manager, get_current_user

router = APIRouter(prefix="/sales", tags=["Ventas"])


def _generate_folio(db: Session) -> str:
    today = date.today()
    prefix = today.strftime("%Y%m%d")
    last = (
        db.query(Sale)
        .filter(Sale.folio.like(f"{prefix}%"))
        .order_by(Sale.id.desc())
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.folio.split("-")[-1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}-{seq:04d}"


@router.post("/", response_model=SaleOut, status_code=201)
def create_sale(
    data: SaleCreate,
    db: Session = Depends(get_db),
    current=Depends(require_cashier),
):
    if not data.items:
        raise HTTPException(400, "La venta debe tener al menos un producto")

    subtotal = Decimal("0")
    tax_total = Decimal("0")
    sale_items = []

    for item_data in data.items:
        product = (
            db.query(Product)
            .options(joinedload(Product.inventory))
            .filter(Product.id == item_data.product_id, Product.is_active == True)
            .first()
        )
        if not product:
            raise HTTPException(404, f"Producto {item_data.product_id} no encontrado")

        inv = product.inventory
        if inv and not product.allow_fractional and item_data.quantity != int(item_data.quantity):
            raise HTTPException(400, f"El producto {product.name} no permite venta fraccionada")
        if inv and inv.quantity < item_data.quantity:
            raise HTTPException(400, f"Stock insuficiente para {product.name} (disponible: {inv.quantity})")

        disc_pct = min(item_data.discount_pct, product.discount_max)
        unit_price = item_data.unit_price
        line_subtotal = unit_price * Decimal(str(item_data.quantity))
        disc_amount = line_subtotal * Decimal(str(disc_pct / 100))
        line_subtotal -= disc_amount
        tax_amount = line_subtotal * Decimal(str(product.tax_rate))

        subtotal += line_subtotal
        tax_total += tax_amount

        sale_items.append({
            "product": product,
            "inventory": inv,
            "quantity": item_data.quantity,
            "unit_price": unit_price,
            "discount_pct": disc_pct,
            "tax_rate": product.tax_rate,
            "subtotal": line_subtotal,
        })

    total = subtotal + tax_total - data.discount_amount
    change = data.payment_amount - total

    if change < 0 and data.payment_amount > 0:
        raise HTTPException(400, "Monto de pago insuficiente")

    # Calcular el efectivo real que entra a la caja física:
    # - efectivo: el total (o el pago recibido si hay cambio)
    # - tarjeta/transferencia: $0 (no entra a la caja)
    # - mixto: solo la parte en efectivo (campo cash_tendered del request)
    pm = data.payment_method
    if pm == PaymentMethod.CASH:
        cash_tendered = data.payment_amount          # puede tener cambio
    elif pm == PaymentMethod.MIXED:
        cash_tendered = data.cash_tendered           # la parte enviada en efectivo
    else:
        cash_tendered = Decimal("0")                 # tarjeta/transferencia: $0 físico

    # Reintentar generación de folio: con varias cajas concurrentes,
    # dos ventas pueden calcular el mismo folio antes de hacer commit,
    # provocando un choque con el índice único sales.ix_sales_folio.
    max_retries = 5
    for attempt in range(max_retries):
        sale = Sale(
            folio=_generate_folio(db),
            session_id=data.session_id,
            cashier_id=current.id,
            customer_name=data.customer_name,
            customer_tax_id=data.customer_tax_id,
            subtotal=subtotal,
            tax_amount=tax_total,
            discount_amount=data.discount_amount,
            total=total,
            payment_method=data.payment_method,
            payment_amount=data.payment_amount,
            change_amount=max(change, Decimal("0")),
            cash_tendered=cash_tendered,
            status=SaleStatus.COMPLETED,
            notes=data.notes,
        )
        db.add(sale)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == max_retries - 1:
                raise HTTPException(
                    409, "No se pudo generar un folio único para la venta, intenta de nuevo"
                )

    for si in sale_items:
        item = SaleItem(
            sale_id=sale.id,
            product_id=si["product"].id,
            product_code=si["product"].code,
            product_name=si["product"].name,
            quantity=si["quantity"],
            unit_price=si["unit_price"],
            discount_pct=si["discount_pct"],
            tax_rate=si["tax_rate"],
            subtotal=si["subtotal"],
        )
        db.add(item)

        # Descontar inventario
        inv = si["inventory"]
        if inv:
            prev = inv.quantity
            inv.quantity -= si["quantity"]
            mov = InventoryMovement(
                inventory_id=inv.id,
                user_id=current.id,
                movement_type="out",
                quantity=si["quantity"],
                previous_quantity=prev,
                new_quantity=inv.quantity,
                reason=f"Venta {sale.folio}",
                reference_id=sale.id,
            )
            db.add(mov)

    db.commit()
    db.refresh(sale)
    return sale


@router.get("/", response_model=List[SaleOut])
def list_sales(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session_id: Optional[int] = None,
    cashier_id: Optional[int] = None,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    from datetime import datetime
    q = db.query(Sale).options(
        joinedload(Sale.items), joinedload(Sale.cashier)
    )
    if start_date:
        q = q.filter(Sale.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(Sale.created_at <= datetime.combine(end_date, datetime.max.time()))
    if session_id:
        q = q.filter(Sale.session_id == session_id)
    if cashier_id:
        q = q.filter(Sale.cashier_id == cashier_id)
    return q.order_by(Sale.created_at.desc()).limit(limit).all()


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db), _=Depends(require_cashier)):
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.cashier))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        raise HTTPException(404, "Venta no encontrada")
    return sale


@router.get("/{sale_id}/returns")
def get_sale_returns(
    sale_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    """Devuelve todas las devoluciones registradas para una venta."""
    from ..models import SaleReturn
    returns = (
        db.query(SaleReturn)
        .filter(SaleReturn.original_sale_id == sale_id)
        .order_by(SaleReturn.created_at)
        .all()
    )
    result = []
    for r in returns:
        result.append({
            "id":             r.id,
            "created_at":     r.created_at.isoformat() if r.created_at else None,
            "reason":         r.reason,
            "total_returned": float(r.total_returned or 0),
            "cash_returned":  float(r.cash_returned or 0),
            "supervisor":     r.supervisor.full_name if r.supervisor else "—",
            "cashier":        r.cashier.full_name if r.cashier else "—",
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity":     item.quantity,
                    "unit_price":   float(item.unit_price),
                    "subtotal":     float(item.subtotal),
                }
                for item in r.items
            ],
        })
    return result


@router.post("/{sale_id}/cancel")
def cancel_sale(
    sale_id: int,
    reason: str = "Sin motivo especificado",
    supervisor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current=Depends(require_cashier),
):
    sale = db.query(Sale).options(joinedload(Sale.items)).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Venta no encontrada")
    if sale.status not in (SaleStatus.COMPLETED, SaleStatus.PARTIAL_RETURN):
        raise HTTPException(400, "Solo se pueden cancelar ventas completadas")

    approver_id = supervisor_id or current.id
    sale.status = SaleStatus.CANCELLED.value
    sale.notes  = (sale.notes or "") + f" | CANCELADA por usuario {approver_id}: {reason}"

    # Revertir inventario
    for item in sale.items:
        if item.product_id:
            inv = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
            if inv:
                prev = inv.quantity
                inv.quantity += item.quantity
                db.add(InventoryMovement(
                    inventory_id=inv.id,
                    user_id=approver_id,
                    movement_type="in",
                    quantity=item.quantity,
                    previous_quantity=prev,
                    new_quantity=inv.quantity,
                    reason=f"Cancelación venta {sale.folio}",
                    reference_id=sale.id,
                ))

    db.commit()
    return {"detail": "Venta cancelada", "folio": sale.folio}


@router.post("/{sale_id}/return")
def process_return(
    sale_id:        int,
    supervisor_id:  int,
    reason:         str  = "Devolución de cliente",
    items:          str  = "",       # JSON: [{"sale_item_id": N, "quantity": X}, ...]
    is_cash_return: bool = True,     # True = se devuelve en efectivo (resta del físico en caja)
    db:             Session = Depends(get_db),
    current=Depends(require_cashier),
):
    """Procesa una devolución parcial o total de artículos de una venta.
    Requiere ID de supervisor ya verificado por /auth/verify-supervisor.
    `items` es un JSON string con los artículos a devolver."""
    import json
    from ..models import SaleReturn, SaleReturnItem

    sale = db.query(Sale).options(joinedload(Sale.items)).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Venta no encontrada")
    if sale.status == SaleStatus.CANCELLED:
        raise HTTPException(400, "No se puede devolver una venta cancelada")

    # Parsear items a devolver
    try:
        return_items = json.loads(items) if items else []
    except Exception:
        raise HTTPException(400, "Formato de artículos inválido")

    if not return_items:
        raise HTTPException(400, "Debes seleccionar al menos un artículo para devolver")

    # Construir mapa de sale_items por id
    items_map = {si.id: si for si in sale.items}

    total_returned  = Decimal("0")
    # cash_proportion ya no es necesario — el checkbox del frontend lo decide explícitamente

    sale_return = SaleReturn(
        original_sale_id=sale_id,
        cashier_id=current.id,
        supervisor_id=supervisor_id,
        reason=reason,
    )
    db.add(sale_return)
    db.flush()

    for ri in return_items:
        si_id = ri.get("sale_item_id")
        qty   = float(ri.get("quantity", 0))
        if si_id not in items_map or qty <= 0:
            continue
        si = items_map[si_id]
        if qty > si.quantity:
            qty = si.quantity

        disc    = si.discount_pct / 100 if si.discount_pct else 0
        unit_p  = float(si.unit_price) * (1 - disc)
        subtotal = Decimal(str(round(qty * unit_p, 2)))
        total_returned += subtotal

        db.add(SaleReturnItem(
            return_id=sale_return.id,
            product_id=si.product_id,
            product_name=si.product_name,
            quantity=qty,
            unit_price=si.unit_price,
            subtotal=subtotal,
        ))

        # Devolver al inventario
        if si.product_id:
            inv = db.query(Inventory).filter(Inventory.product_id == si.product_id).first()
            if inv:
                prev = inv.quantity
                inv.quantity += qty
                db.add(InventoryMovement(
                    inventory_id=inv.id,
                    user_id=supervisor_id,
                    movement_type="in",
                    quantity=qty,
                    previous_quantity=prev,
                    new_quantity=inv.quantity,
                    reason=f"Devolución venta {sale.folio}",
                    reference_id=sale.id,
                ))

    # Si is_cash_return=True → la devolución sale del efectivo en caja (reduce expected_in_register)
    # Si is_cash_return=False → devolución por otro medio (tarjeta, transferencia) → no afecta caja
    cash_returned = total_returned if is_cash_return else Decimal("0")

    sale_return.total_returned = total_returned
    sale_return.cash_returned  = cash_returned

    # Actualizar estado de la venta original
    sale.status = SaleStatus.PARTIAL_RETURN.value  # "partial_return" explícito → evita ambigüedad de case
    sale.notes  = (sale.notes or "") + f" | DEV ${total_returned:.2f}"

    db.commit()
    db.refresh(sale_return)
    return {
        "detail":          "Devolución registrada",
        "return_id":       sale_return.id,
        "folio":           sale.folio,
        "total_returned":  float(total_returned),
        "cash_returned":   float(cash_returned),
    }
