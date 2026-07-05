from typing import List
from decimal import Decimal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import CashSession, CashRegister, CashMovement, Sale, SaleStatus, SessionStatus, User
from ..schemas import (
    CashSessionOut, OpenCashSession, CloseCashSession, TransferCashSession,
    CashMovementCreate, CashMovementOut, CashRegisterOut,
    CashRegisterCreate, CashRegisterUpdate,
)
from ..services.auth import require_cashier, require_manager, require_admin, get_current_user

router = APIRouter(prefix="/cash", tags=["Caja"])


# ── CRUD de Cajas Registradoras ───────────────────────────────────────────────

@router.get("/registers", response_model=List[CashRegisterOut])
def list_registers(db: Session = Depends(get_db), _=Depends(require_cashier)):
    """Cajas activas (para uso en POS y apertura de sesión)."""
    return db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.id).all()


@router.get("/registers/all", response_model=List[CashRegisterOut])
def list_all_registers(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Todas las cajas incluyendo inactivas (para administración)."""
    return db.query(CashRegister).order_by(CashRegister.id).all()


@router.post("/registers", response_model=CashRegisterOut, status_code=201)
def create_register(
    data: CashRegisterCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    existing = db.query(CashRegister).filter(CashRegister.name == data.name).first()
    if existing:
        raise HTTPException(400, f"Ya existe una caja con el nombre '{data.name}'")
    reg = CashRegister(
        name=data.name,
        location=data.location or "",
        printer_name=data.printer_name,
        is_active=True,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return reg


@router.put("/registers/{register_id}", response_model=CashRegisterOut)
def update_register(
    register_id: int,
    data: CashRegisterUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    reg = db.query(CashRegister).filter(CashRegister.id == register_id).first()
    if not reg:
        raise HTTPException(404, "Caja no encontrada")
    if data.name and data.name != reg.name:
        if db.query(CashRegister).filter(CashRegister.name == data.name).first():
            raise HTTPException(400, f"Ya existe una caja con el nombre '{data.name}'")
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(reg, field, val)
    db.commit()
    db.refresh(reg)
    return reg


@router.delete("/registers/{register_id}", status_code=204)
def delete_register(
    register_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    reg = db.query(CashRegister).filter(CashRegister.id == register_id).first()
    if not reg:
        raise HTTPException(404, "Caja no encontrada")

    # Bloquear si hay una sesión actualmente abierta
    open_session = db.query(CashSession).filter(
        CashSession.register_id == register_id,
        CashSession.status == SessionStatus.OPEN,
    ).first()
    if open_session:
        raise HTTPException(400, "No se puede eliminar una caja con sesión activa. Ciérrala primero.")

    # Bloquear si tiene historial de sesiones cerradas (preservar registros)
    has_history = db.query(CashSession).filter(
        CashSession.register_id == register_id,
    ).first()
    if has_history:
        raise HTTPException(
            409,
            "La caja tiene historial de sesiones y no puede eliminarse permanentemente "
            "(protege la integridad del historial). "
            "Usa 'Desactivar' para ocultarla sin perder el historial.",
        )

    # Sin historial → eliminar permanentemente
    db.delete(reg)
    db.commit()


@router.get("/sessions/active")
def get_active_sessions(db: Session = Depends(get_db), _=Depends(require_cashier)):
    sessions = (
        db.query(CashSession)
        .options(joinedload(CashSession.register), joinedload(CashSession.cashier))
        .filter(CashSession.status == SessionStatus.OPEN)
        .all()
    )
    return [
        {
            "id": s.id,
            "register": {"id": s.register.id, "name": s.register.name},
            "cashier": {"id": s.cashier.id, "full_name": s.cashier.full_name},
            "opening_amount": float(s.opening_amount),
            "opened_at": s.opened_at.isoformat(),
        }
        for s in sessions
    ]


@router.post("/open", response_model=CashSessionOut)
def open_session(data: OpenCashSession, db: Session = Depends(get_db), current=Depends(require_cashier)):
    register = db.query(CashRegister).filter(
        CashRegister.id == data.register_id, CashRegister.is_active == True
    ).first()
    if not register:
        raise HTTPException(404, "Caja no encontrada")

    # Verificar que no haya sesión abierta para esta caja
    existing = db.query(CashSession).filter(
        CashSession.register_id == data.register_id,
        CashSession.status == SessionStatus.OPEN,
    ).first()
    if existing:
        raise HTTPException(400, f"La caja ya tiene una sesión abierta (ID: {existing.id})")

    session = CashSession(
        register_id=data.register_id,
        cashier_id=current.id,
        opening_amount=data.opening_amount,
        notes=data.notes,
        status=SessionStatus.OPEN,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/close", response_model=CashSessionOut)
def close_session(
    session_id: int,
    data: CloseCashSession,
    db: Session = Depends(get_db),
    current=Depends(require_cashier),
):
    session = (
        db.query(CashSession)
        .options(
            joinedload(CashSession.register),
            joinedload(CashSession.cashier),
            joinedload(CashSession.movements),
            joinedload(CashSession.sales),
        )
        .filter(CashSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Sesión no encontrada")
    if session.status == SessionStatus.CLOSED:
        raise HTTPException(400, "La sesión ya está cerrada")

    # Calcular monto esperado
    completed_sales = [s for s in session.sales if s.status == SaleStatus.COMPLETED]
    cash_sales = sum(
        s.total for s in completed_sales if s.payment_method.value == "cash"
    ) or Decimal("0")
    cash_in = sum(
        m.amount for m in session.movements if m.movement_type.value == "income"
    ) or Decimal("0")
    cash_out = sum(
        m.amount for m in session.movements if m.movement_type.value == "expense"
    ) or Decimal("0")

    expected = session.opening_amount + cash_sales + cash_in - cash_out
    difference = data.closing_amount - expected

    session.closing_amount = data.closing_amount
    session.expected_amount = expected
    session.difference = difference
    session.status = SessionStatus.CLOSED
    session.closed_at = datetime.utcnow()
    if data.notes:
        session.notes = (session.notes or "") + f" | Cierre: {data.notes}"

    db.commit()
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/transfer", response_model=CashSessionOut)
def transfer_session(
    session_id: int,
    data: TransferCashSession,
    db: Session = Depends(get_db),
    current=Depends(require_manager),
):
    """Transfiere la propiedad de una caja abierta a otro usuario.
    Solo gerentes/administradores pueden hacerlo (visible únicamente para
    ellos también en el frontend)."""
    session = (
        db.query(CashSession)
        .options(
            joinedload(CashSession.register),
            joinedload(CashSession.cashier),
            joinedload(CashSession.movements).joinedload(CashMovement.user),
        )
        .filter(CashSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Sesión no encontrada")
    if session.status != SessionStatus.OPEN:
        raise HTTPException(400, "Solo se puede transferir una caja abierta")

    new_cashier = db.query(User).filter(
        User.id == data.new_cashier_id, User.is_active == True
    ).first()
    if not new_cashier:
        raise HTTPException(404, "El usuario destino no existe o está inactivo")
    if new_cashier.id == session.cashier_id:
        raise HTTPException(400, "La caja ya pertenece a ese usuario")

    previous_cashier_name = session.cashier.full_name
    note = (f"Transferida de {previous_cashier_name} a {new_cashier.full_name} "
            f"por {current.full_name} el {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}")
    if data.reason:
        note += f" — Motivo: {data.reason}"
    session.notes = (session.notes + " | " + note) if session.notes else note
    session.cashier = new_cashier   # actualiza cashier_id y el objeto relacionado en caché

    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=CashSessionOut)
def get_session(session_id: int, db: Session = Depends(get_db), _=Depends(require_cashier)):
    session = (
        db.query(CashSession)
        .options(
            joinedload(CashSession.register),
            joinedload(CashSession.cashier),
            joinedload(CashSession.movements).joinedload(CashMovement.user),
        )
        .filter(CashSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Sesión no encontrada")
    return session


@router.get("/sessions", response_model=List[CashSessionOut])
def list_sessions(
    limit: int = 30,
    db: Session = Depends(get_db),
    _=Depends(require_manager),
):
    return (
        db.query(CashSession)
        .options(
            joinedload(CashSession.register),
            joinedload(CashSession.cashier),
        )
        .order_by(CashSession.opened_at.desc())
        .limit(limit)
        .all()
    )


@router.patch("/sessions/{session_id}/physical-count")
def update_physical_count(
    session_id: int,
    closing_amount: float,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    """Actualiza el conteo físico de una sesión ya cerrada.
    Permite registrar la diferencia entre lo esperado y lo contado realmente."""
    from decimal import Decimal
    session = db.query(CashSession).filter(CashSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Sesión no encontrada")
    session.closing_amount = Decimal(str(closing_amount))
    db.commit()
    return {"detail": "Conteo físico actualizado", "closing_amount": closing_amount}


@router.post("/sessions/{session_id}/movement", response_model=CashMovementOut)
def add_movement(
    session_id: int,
    data: CashMovementCreate,
    db: Session = Depends(get_db),
    current=Depends(require_cashier),
):
    session = db.query(CashSession).filter(
        CashSession.id == session_id, CashSession.status == SessionStatus.OPEN
    ).first()
    if not session:
        raise HTTPException(404, "Sesión activa no encontrada")

    mov = CashMovement(
        session_id=session_id,
        user_id=current.id,
        movement_type=data.movement_type,
        amount=data.amount,
        reason=data.reason,
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)
    return mov
