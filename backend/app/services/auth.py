"""
Servicio de autenticación: JWT, hashing de contraseñas, validación de permisos
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from ..models import User, UserRole
from ..config import settings
from ..database import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ── Mapa de permisos por rol ──────────────────────────────────────────────────
ROLE_PERMISSIONS = {
    UserRole.ADMIN: {
        "users": ["read", "write", "delete"],
        "products": ["read", "write", "delete"],
        "sales": ["read", "write", "cancel"],
        "inventory": ["read", "write"],
        "cash": ["read", "open", "close"],
        "reports": ["read"],
        "config": ["read", "write"],
    },
    UserRole.MANAGER: {
        "users": ["read"],
        "products": ["read", "write"],
        "sales": ["read", "write", "cancel"],
        "inventory": ["read", "write"],
        "cash": ["read", "open", "close"],
        "reports": ["read"],
        "config": ["read"],
    },
    UserRole.CASHIER: {
        "users": [],
        "products": ["read"],
        "sales": ["read", "write"],
        "inventory": ["read"],
        "cash": ["read", "open", "close"],
        "reports": [],
        "config": [],
    },
}


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def authenticate_pin(db: Session, username: str, pin: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username, User.pin == pin).first()
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exc
    return user


def require_role(*roles: UserRole):
    """Dependencia que verifica que el usuario tenga uno de los roles indicados."""
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para esta acción",
            )
        return current_user
    return checker


def has_permission(user: User, resource: str, action: str) -> bool:
    perms = ROLE_PERMISSIONS.get(user.role, {})
    return action in perms.get(resource, [])


require_admin = require_role(UserRole.ADMIN)
require_manager = require_role(UserRole.ADMIN, UserRole.MANAGER)
require_cashier = require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.CASHIER)
