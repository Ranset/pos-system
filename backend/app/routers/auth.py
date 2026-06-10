from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas import Token, UserOut
from ..services.auth import authenticate_user, authenticate_pin, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuario desactivado")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/pin-login", response_model=Token)
def pin_login(username: str, pin: str, db: Session = Depends(get_db)):
    user = authenticate_pin(db, username, pin)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="PIN incorrecto")
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/verify-supervisor")
def verify_supervisor(username: str, password: str, db: Session = Depends(get_db),
                      _=Depends(get_current_user)):
    """Verifica credenciales de Gerente o Administrador para aprobar operaciones sensibles.
    Llamado por el cajero para obtener aprobación sin revelar el token del supervisor."""
    from ..models import UserRole
    user = authenticate_user(db, username, password)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise HTTPException(status_code=403,
                            detail="Se requiere rol de Gerente o Administrador")
    return {
        "valid":      True,
        "supervisor_id": user.id,
        "full_name":  user.full_name,
        "role":       user.role.value,
    }


@router.get("/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)):
    return current_user
