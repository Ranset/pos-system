"""
Modelos SQLAlchemy para el Sistema POS
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    Text, ForeignKey, Enum as SQLEnum, JSON, DECIMAL, Date
)
from sqlalchemy.orm import relationship
from ..database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    CASHIER = "cashier"


class SaleStatus(str, enum.Enum):
    COMPLETED      = "completed"
    CANCELLED      = "cancelled"
    REFUNDED       = "refunded"
    PARTIAL_RETURN = "partial_return"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"
    MIXED = "mixed"


class SessionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class MovementType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


# ─────────────────────────────────────────────────────────────────────────────
# Usuarios y Roles
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.CASHIER, nullable=False)
    pin = Column(String(6), nullable=True)          # PIN numérico rápido
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    sales = relationship("Sale", back_populates="cashier", foreign_keys="Sale.cashier_id")
    cash_sessions = relationship("CashSession", back_populates="cashier")


# ─────────────────────────────────────────────────────────────────────────────
# Productos e Inventario
# ─────────────────────────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    color = Column(String(7), default="#1565C0")   # Hex color para la UI
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)  # Código/barcode
    name = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(DECIMAL(10, 2), nullable=False)          # Precio venta
    cost = Column(DECIMAL(10, 2), default=0.00)             # Precio costo
    tax_rate = Column(Float, default=0.0)                   # % IVA (ej: 0.16)
    discount_max = Column(Float, default=0.0)               # Descuento máx permitido
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    allow_fractional = Column(Boolean, default=False)       # Venta por fracción
    image_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    category = relationship("Category", back_populates="products")
    inventory = relationship("Inventory", back_populates="product", uselist=False)
    sale_items = relationship("SaleItem", back_populates="product")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)
    quantity = Column(Float, default=0.0)
    min_stock = Column(Float, default=5.0)   # Alerta stock mínimo
    max_stock = Column(Float, default=100.0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="inventory")
    movements = relationship("InventoryMovement", back_populates="inventory")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    movement_type = Column(String(20), nullable=False)   # "in", "out", "adjustment"
    quantity = Column(Float, nullable=False)
    previous_quantity = Column(Float, nullable=False)
    new_quantity = Column(Float, nullable=False)
    reason = Column(String(255), nullable=True)
    reference_id = Column(Integer, nullable=True)        # sale_id or purchase_id
    created_at = Column(DateTime, default=datetime.utcnow)

    inventory = relationship("Inventory", back_populates="movements")
    user = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
# Caja y Sesiones
# ─────────────────────────────────────────────────────────────────────────────

class CashRegister(Base):
    __tablename__ = "cash_registers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False)           # Ej: "Caja 1", "Caja Principal"
    location = Column(String(120), nullable=True)
    printer_name = Column(String(120), nullable=True)   # Nombre impresora asociada
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("CashSession", back_populates="register")


class CashSession(Base):
    __tablename__ = "cash_sessions"

    id = Column(Integer, primary_key=True, index=True)
    register_id = Column(Integer, ForeignKey("cash_registers.id"), nullable=False)
    cashier_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opening_amount = Column(DECIMAL(10, 2), default=0.00)   # Fondo inicial
    closing_amount = Column(DECIMAL(10, 2), nullable=True)  # Conteo físico al cerrar
    expected_amount = Column(DECIMAL(10, 2), nullable=True) # Calculado por el sistema
    difference = Column(DECIMAL(10, 2), nullable=True)      # Diferencia
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.OPEN)
    notes = Column(Text, nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    register = relationship("CashRegister", back_populates="sessions")
    cashier = relationship("User", back_populates="cash_sessions")
    sales = relationship("Sale", back_populates="session")
    movements = relationship("CashMovement", back_populates="session")


class CashMovement(Base):
    """Retiros o depósitos manuales en caja (aparte de ventas)"""
    __tablename__ = "cash_movements"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("cash_sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movement_type = Column(SQLEnum(MovementType), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("CashSession", back_populates="movements")
    user = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
# Ventas
# ─────────────────────────────────────────────────────────────────────────────

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True, nullable=False, index=True)   # Número de ticket
    session_id = Column(Integer, ForeignKey("cash_sessions.id"), nullable=True)
    cashier_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_name = Column(String(120), nullable=True)
    customer_tax_id = Column(String(30), nullable=True)  # RFC / NIT
    subtotal = Column(DECIMAL(10, 2), nullable=False)
    tax_amount = Column(DECIMAL(10, 2), default=0.00)
    discount_amount = Column(DECIMAL(10, 2), default=0.00)
    total = Column(DECIMAL(10, 2), nullable=False)
    payment_method = Column(SQLEnum(PaymentMethod), default=PaymentMethod.CASH)
    payment_amount = Column(DECIMAL(10, 2), nullable=False)    # Monto total recibido
    change_amount  = Column(DECIMAL(10, 2), default=0.00)      # Cambio entregado
    cash_tendered  = Column(DECIMAL(10, 2), default=0.00)      # Parte EN EFECTIVO (crítico para cierre)
    commission_pct    = Column(Float, default=0.0)             # % comisión aplicada según método de pago
    commission_amount = Column(DECIMAL(10, 2), default=0.00)   # Monto de comisión (puede ser negativo)
    # status: String en lugar de Enum para evitar conflictos de case en MySQL.
    # Los valores válidos se definen en SaleStatus; se almacenan en minúsculas.
    status = Column(String(30), default=SaleStatus.COMPLETED.value)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cashier = relationship("User", back_populates="sales", foreign_keys=[cashier_id])
    session = relationship("CashSession", back_populates="sales")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product_code = Column(String(50), nullable=False)    # Snapshot al momento de venta
    product_name = Column(String(150), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(DECIMAL(10, 2), nullable=False)
    discount_pct = Column(Float, default=0.0)            # % descuento aplicado
    tax_rate = Column(Float, default=0.0)
    subtotal = Column(DECIMAL(10, 2), nullable=False)

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")


# ─────────────────────────────────────────────────────────────────────────────
# Normalización automática de status al leer de la BD
# Evita errores si la BD tiene valores en mayúsculas (COMPLETED → completed)
# ─────────────────────────────────────────────────────────────────────────────
from sqlalchemy import event as _sa_event

@_sa_event.listens_for(Sale, "load")
def _normalize_sale_status(target, context):
    if target.status and isinstance(target.status, str):
        target.status = target.status.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Configuración del sistema
# ─────────────────────────────────────────────────────────────────────────────

class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    category = Column(String(50), default="general")   # general, fiscal, printer, etc.
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# Devoluciones de ventas
# ─────────────────────────────────────────────────────────────────────────────

class SaleReturn(Base):
    """Registro de una devolución (parcial o total) de una venta."""
    __tablename__ = "sale_returns"

    id = Column(Integer, primary_key=True, index=True)
    original_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    cashier_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    supervisor_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason           = Column(String(500), nullable=True)
    total_returned   = Column(DECIMAL(10, 2), nullable=False, default=0)
    cash_returned    = Column(DECIMAL(10, 2), nullable=False, default=0)
    created_at       = Column(DateTime, default=datetime.utcnow)

    original_sale = relationship("Sale", foreign_keys=[original_sale_id])
    cashier       = relationship("User", foreign_keys=[cashier_id])
    supervisor    = relationship("User", foreign_keys=[supervisor_id])
    items         = relationship("SaleReturnItem", back_populates="sale_return",
                                 cascade="all, delete-orphan")


class SaleReturnItem(Base):
    """Artículo individual incluido en una devolución."""
    __tablename__ = "sale_return_items"

    id            = Column(Integer, primary_key=True, index=True)
    return_id     = Column(Integer, ForeignKey("sale_returns.id"), nullable=False)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=True)
    product_name  = Column(String(150), nullable=False)
    quantity      = Column(Float, nullable=False)
    unit_price    = Column(DECIMAL(10, 2), nullable=False)
    subtotal      = Column(DECIMAL(10, 2), nullable=False)

    sale_return = relationship("SaleReturn", back_populates="items")
    product     = relationship("Product")
