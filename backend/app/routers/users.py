from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import UserOut, UserCreate, UserUpdate
from ..services.auth import require_admin, require_manager, hash_password, get_current_user

router = APIRouter(prefix="/users", tags=["Usuarios"])


@router.get("/", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(require_manager)):
    return db.query(User).order_by(User.full_name).all()


@router.post("/", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "El nombre de usuario ya existe")
    if data.email and db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "El correo ya está registrado")

    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role,
        pin=data.pin,
        is_active=data.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _=Depends(require_manager)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, data: UserUpdate, db: Session = Depends(get_db), _=Depends(require_admin)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.email is not None:
        user.email = data.email
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.pin is not None:
        user.pin = data.pin
    if data.password:
        user.hashed_password = hash_password(data.password)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    if current.id == user_id:
        raise HTTPException(400, "No puedes eliminar tu propio usuario")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    # Verificar si el usuario tiene historial que impide el borrado físico
    from ..models import Sale, CashSession, CashMovement
    has_sales    = db.query(Sale).filter(Sale.cashier_id == user_id).first()
    has_sessions = db.query(CashSession).filter(CashSession.cashier_id == user_id).first()
    has_movements= db.query(CashMovement).filter(CashMovement.user_id == user_id).first()

    if has_sales or has_sessions or has_movements:
        raise HTTPException(
            409,
            "El usuario tiene ventas o sesiones de caja registradas y no puede eliminarse "
            "permanentemente (protege la integridad del historial). "
            "Usa 'Desactivar' para bloquearlo sin perder el historial.",
        )

    # Sin historial → eliminar permanentemente
    db.delete(user)
    db.commit()


@router.put("/me/password")
def change_my_password(
    old_password: str,
    new_password: str,
    db: Session = Depends(get_db),
    current=Depends(get_current_user),
):
    from ..services.auth import verify_password, hash_password
    if not verify_password(old_password, current.hashed_password):
        raise HTTPException(400, "Contraseña actual incorrecta")
    current.hashed_password = hash_password(new_password)
    db.commit()
    return {"detail": "Contraseña actualizada"}
