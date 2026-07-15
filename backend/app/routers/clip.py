"""Endpoints de integración con terminal de pago Clip PinPad.
Toda comunicación con la API de Clip pasa por ClipPinpadService — este router
solo orquesta HTTP/DB, nunca llama a Clip directamente."""
import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db, SessionLocal
from ..models import ClipTerminal, ClipPayment, ClipPaymentStatus, CashSession, Product, Sale, AppConfig
from ..schemas import (
    ClipTerminalOut, ClipTerminalCreate, ClipTerminalUpdate,
    ClipPaymentCreate, ClipPaymentOut, SaleCreate,
)
from ..services.auth import require_cashier, require_manager, require_admin
from ..services.clip_pinpad import ClipPinpadService, ClipServiceError
from .sales import _get_commission_pct

router = APIRouter(prefix="/clip", tags=["Clip PinPad"])
webhook_router = APIRouter(prefix="/webhooks", tags=["Clip PinPad"])


# ── CRUD de Terminales ────────────────────────────────────────────────────────

@router.get("/terminals", response_model=List[ClipTerminalOut])
def list_terminals(db: Session = Depends(get_db), _=Depends(require_cashier)):
    """Terminales activas (para el selector de cobro en el POS)."""
    return db.query(ClipTerminal).filter(ClipTerminal.is_active == True).order_by(ClipTerminal.id).all()


@router.get("/terminals/all", response_model=List[ClipTerminalOut])
def list_all_terminals(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Todas las terminales incluyendo inactivas (para administración)."""
    return db.query(ClipTerminal).order_by(ClipTerminal.id).all()


@router.post("/terminals", response_model=ClipTerminalOut, status_code=201)
def create_terminal(
    data: ClipTerminalCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    existing = db.query(ClipTerminal).filter(ClipTerminal.serial_number == data.serial_number).first()
    if existing:
        raise HTTPException(400, f"Ya existe una terminal con el número de serie '{data.serial_number}'")
    terminal = ClipTerminal(name=data.name, serial_number=data.serial_number, is_active=True)
    db.add(terminal)
    db.commit()
    db.refresh(terminal)
    return terminal


@router.put("/terminals/{terminal_id}", response_model=ClipTerminalOut)
def update_terminal(
    terminal_id: int,
    data: ClipTerminalUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    terminal = db.query(ClipTerminal).filter(ClipTerminal.id == terminal_id).first()
    if not terminal:
        raise HTTPException(404, "Terminal no encontrada")
    if data.serial_number and data.serial_number != terminal.serial_number:
        if db.query(ClipTerminal).filter(ClipTerminal.serial_number == data.serial_number).first():
            raise HTTPException(400, f"Ya existe una terminal con el número de serie '{data.serial_number}'")
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(terminal, field, val)
    db.commit()
    db.refresh(terminal)
    return terminal


@router.delete("/terminals/{terminal_id}", status_code=204)
def delete_terminal(
    terminal_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    terminal = db.query(ClipTerminal).filter(ClipTerminal.id == terminal_id).first()
    if not terminal:
        raise HTTPException(404, "Terminal no encontrada")

    has_payments = db.query(ClipPayment).filter(ClipPayment.clip_terminal_id == terminal_id).first()
    if has_payments:
        raise HTTPException(
            409,
            "La terminal tiene cobros registrados y no puede eliminarse permanentemente "
            "(protege la integridad del historial). Usa 'Desactivar' para ocultarla sin perder el historial.",
        )

    from ..models import CashRegister
    assigned = db.query(CashRegister).filter(CashRegister.clip_terminal_id == terminal_id).first()
    if assigned:
        raise HTTPException(400, f"La terminal está asignada a la caja '{assigned.name}'. Desasígnala primero.")

    db.delete(terminal)
    db.commit()


@router.post("/terminals/{terminal_id}/cancel-pending")
def cancel_pending_by_terminal(
    terminal_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    """Recuperación manual: cancela en Clip cualquier cobro que la terminal
    tenga pendiente, sin necesidad de conocer el pinpad_request_id exacto."""
    service = ClipPinpadService(db)
    terminal = service.validate_terminal(terminal_id)
    try:
        result = service.cancel_payment_by_terminal(terminal)
    except ClipServiceError as exc:
        raise HTTPException(400, str(exc))
    return {"detail": "Cancelación enviada a la terminal", "clip_response": result}


# ── Flujo de cobro ─────────────────────────────────────────────────────────────

def _compute_expected_total(db: Session, data: SaleCreate) -> Decimal:
    """Replica la fórmula de _create_sale_internal (subtotal + impuestos - descuento
    + comisión), sin persistir nada. Se usa para fijar el monto exacto que se le
    pide a Clip, de modo que cuando el pago se apruebe, _create_sale_internal
    nunca lo rechace por 'monto de pago insuficiente'."""
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for item_data in data.items:
        product = db.query(Product).filter(
            Product.id == item_data.product_id, Product.is_active == True
        ).first()
        if not product:
            raise HTTPException(404, f"Producto {item_data.product_id} no encontrado")
        disc_pct = min(item_data.discount_pct, product.discount_max)
        line_subtotal = item_data.unit_price * Decimal(str(item_data.quantity))
        disc_amount = line_subtotal * Decimal(str(disc_pct / 100))
        line_subtotal -= disc_amount
        tax_total += line_subtotal * Decimal(str(product.tax_rate))
        subtotal += line_subtotal

    total = subtotal + tax_total - data.discount_amount
    commission_pct = _get_commission_pct(db, data.payment_method)
    commission_amount = (total * commission_pct / 100) if commission_pct else Decimal("0")
    return total + commission_amount


def _resolve_terminal_id(db: Session, payment_data: ClipPaymentCreate) -> int:
    if payment_data.clip_terminal_id:
        return payment_data.clip_terminal_id
    session_id = payment_data.sale_payload.session_id
    if not session_id:
        raise HTTPException(400, "Debes indicar clip_terminal_id o una sesión de caja con terminal asignada")
    session = (
        db.query(CashSession)
        .options(joinedload(CashSession.register))
        .filter(CashSession.id == session_id)
        .first()
    )
    if not session or not session.register or not session.register.clip_terminal_id:
        raise HTTPException(400, "La caja de esta sesión no tiene una terminal Clip asignada")
    return session.register.clip_terminal_id


def _get_webhook_url(db: Session) -> Optional[str]:
    """URL base pública configurada en Configuración → Terminal de Pago Clip
    (ej. túnel de Cloudflare) + la ruta fija del receptor de webhook. None si
    no está configurada — el sistema sigue funcionando solo con polling +
    reconciliación periódica (ver _clip_reconciliation_loop en main.py)."""
    cfg = db.query(AppConfig).filter(AppConfig.key == "clip.webhook_url").first()
    base = (cfg.value or "").strip().rstrip("/") if cfg else ""
    return f"{base}/api/webhooks/clip" if base else None


@router.post("/payments", response_model=ClipPaymentOut, status_code=201)
def create_payment(
    data: ClipPaymentCreate,
    db: Session = Depends(get_db),
    current=Depends(require_cashier),
):
    service = ClipPinpadService(db)
    terminal = service.validate_terminal(_resolve_terminal_id(db, data))

    expected_total = _compute_expected_total(db, data.sale_payload)
    sale_payload = data.sale_payload.model_copy(update={"payment_amount": expected_total})

    reference = f"pos-{uuid.uuid4().hex}"
    try:
        payment = service.create_payment(
            reference=reference,
            amount=expected_total,
            terminal=terminal,
            tip_amount=data.tip_amount,
            cashier_id=current.id,
            session_id=data.sale_payload.session_id,
            sale_payload=sale_payload.model_dump(mode="json"),
            webhook_url=_get_webhook_url(db),
        )
    except ClipServiceError as exc:
        raise HTTPException(502, str(exc))
    return payment


def _load_payment_with_sale(db: Session, payment_id: int) -> Optional[ClipPayment]:
    return (
        db.query(ClipPayment)
        .options(joinedload(ClipPayment.sale).joinedload(Sale.items),
                 joinedload(ClipPayment.sale).joinedload(Sale.cashier))
        .filter(ClipPayment.id == payment_id)
        .first()
    )


@router.get("/payments/{payment_id}/status", response_model=ClipPaymentOut)
def get_payment_status(
    payment_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    from datetime import datetime, timedelta

    payment = _load_payment_with_sale(db, payment_id)
    if not payment:
        raise HTTPException(404, "Cobro no encontrado")

    throttle_cutoff = datetime.utcnow() - timedelta(seconds=3)
    if payment.status == ClipPaymentStatus.PENDING.value and (
        not payment.last_synced_at or payment.last_synced_at < throttle_cutoff
    ):
        try:
            service = ClipPinpadService(db)
            service.sync_payment(payment_id)
        except ClipServiceError:
            pass  # error transitorio de red; el frontend reintenta en el próximo tick
        payment = _load_payment_with_sale(db, payment_id)
    return payment


@router.post("/payments/{payment_id}/cancel", response_model=ClipPaymentOut)
def cancel_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    payment = db.query(ClipPayment).filter(ClipPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Cobro no encontrado")
    if payment.status != ClipPaymentStatus.PENDING.value:
        raise HTTPException(400, f"El cobro ya está en estado '{payment.status}', no se puede cancelar")

    service = ClipPinpadService(db)
    try:
        return service.cancel_payment(payment)
    except ClipServiceError as exc:
        raise HTTPException(409, str(exc))


# ── Webhook ─────────────────────────────────────────────────────────────────────

def _process_clip_webhook_bg(payload: dict):
    """Corre en background tras responder 200 a Clip. Sesión propia — NO se
    reutiliza Depends(get_db), ya que esa se habrá cerrado para cuando
    BackgroundTasks ejecute esto (mismo patrón que _seed_defaults() en main.py)."""
    db = SessionLocal()
    try:
        ClipPinpadService(db).process_webhook(payload)
    except Exception as exc:
        print(f"[clip webhook] error inesperado procesando payload: {exc}")
    finally:
        db.close()


@webhook_router.post("/clip", status_code=200)
def clip_webhook(payload: dict, background_tasks: BackgroundTasks):
    """Clip no manda nuestro JWT — este endpoint es intencionalmente público.
    Nunca se hace trabajo pesado aquí: se responde 200 de inmediato y todo el
    procesamiento real ocurre en background, reconfirmando siempre con
    GET /payment (ver ClipPinpadService.process_webhook)."""
    background_tasks.add_task(_process_clip_webhook_bg, payload)
    return {"received": True}
