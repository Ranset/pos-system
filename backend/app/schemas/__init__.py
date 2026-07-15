"""
Schemas Pydantic v2 para validación y serialización
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from ..models import UserRole, SaleStatus, PaymentMethod, SessionStatus, MovementType


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    user: "UserOut"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    username: str
    full_name: str
    email: Optional[str] = None
    role: UserRole = UserRole.CASHIER
    is_active: bool = True


class UserCreate(UserBase):
    password: str
    pin: Optional[str] = None

    @field_validator("pin")
    @classmethod
    def pin_numeric(cls, v):
        if v and not v.isdigit():
            raise ValueError("PIN debe ser numérico")
        if v and len(v) not in (4, 6):
            raise ValueError("PIN debe tener 4 o 6 dígitos")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    pin: Optional[str] = None
    password: Optional[str] = None


class UserOut(UserBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Categories
# ─────────────────────────────────────────────────────────────────────────────

class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#1565C0"
    is_active: bool = True


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class CategoryOut(CategoryBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Products
# ─────────────────────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    price: Decimal
    cost: Decimal = Decimal("0.00")
    tax_rate: float = 0.0
    discount_max: float = 0.0
    category_id: Optional[int] = None
    is_active: bool = True
    allow_fractional: bool = False


class ProductCreate(ProductBase):
    initial_stock: float = 0.0
    min_stock: float = 5.0
    max_stock: float = 100.0


class ProductUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    cost: Optional[Decimal] = None
    tax_rate: Optional[float] = None
    discount_max: Optional[float] = None
    category_id: Optional[int] = None
    is_active: Optional[bool] = None
    allow_fractional: Optional[bool] = None


class InventoryOut(BaseModel):
    id: int
    quantity: float
    min_stock: float
    max_stock: float
    last_updated: datetime

    model_config = {"from_attributes": True}


class ProductOut(ProductBase):
    id: int
    created_at: datetime
    category: Optional[CategoryOut] = None
    inventory: Optional[InventoryOut] = None

    model_config = {"from_attributes": True}


class StockAdjustment(BaseModel):
    product_id: int
    quantity: float          # Positivo = entrada, Negativo = salida
    reason: str
    movement_type: str = "adjustment"  # "in", "out", "adjustment"


class InventoryMovementOut(BaseModel):
    id: int
    movement_type: str
    quantity: float
    previous_quantity: float
    new_quantity: float
    reason: Optional[str] = None
    reference_id: Optional[int] = None
    created_at: datetime
    user_name: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Importación de productos desde Excel
# ─────────────────────────────────────────────────────────────────────────────

class ProductImportRow(BaseModel):
    """Una fila del Excel de importación. Todos los campos son opcionales a
    nivel de validación: las filas sin código/nombre/precio se omiten en el
    propio endpoint (no provocan un error 422 de todo el lote)."""
    code: Optional[str] = None
    name: Optional[str] = None
    initial_stock: Optional[float] = None
    cost: Optional[float] = None
    price: Optional[float] = None
    description: Optional[str] = None
    tax_rate: Optional[float] = None
    discount_max: Optional[float] = None
    category: Optional[str] = None
    min_stock: Optional[float] = None
    max_stock: Optional[float] = None


class ProductImportRowResult(BaseModel):
    row: int
    code: Optional[str] = None
    name: Optional[str] = None
    status: str  # "created" | "updated" | "skipped"
    detail: Optional[str] = None


class ProductImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    details: list[ProductImportRowResult]

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Cash Sessions
# ─────────────────────────────────────────────────────────────────────────────

class CashRegisterOut(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    printer_name: Optional[str] = None
    clip_terminal_id: Optional[int] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CashRegisterCreate(BaseModel):
    name: str
    location: Optional[str] = ""
    printer_name: Optional[str] = None
    clip_terminal_id: Optional[int] = None


class CashRegisterUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    printer_name: Optional[str] = None
    clip_terminal_id: Optional[int] = None
    is_active: Optional[bool] = None


class OpenCashSession(BaseModel):
    register_id: int
    opening_amount: Decimal = Decimal("0.00")
    notes: Optional[str] = None


class CloseCashSession(BaseModel):
    closing_amount: Decimal
    notes: Optional[str] = None


class TransferCashSession(BaseModel):
    new_cashier_id: int
    reason: Optional[str] = None


class CashMovementCreate(BaseModel):
    movement_type: MovementType
    amount: Decimal
    reason: str


class CashMovementOut(BaseModel):
    id: int
    movement_type: MovementType
    amount: Decimal
    reason: str
    created_at: datetime
    user: UserOut

    model_config = {"from_attributes": True}


class CashSessionOut(BaseModel):
    id: int
    # Alias "register" preserva compatibilidad JSON/ORM; evita warning ABCMeta.register
    cash_register: CashRegisterOut = Field(alias="register")
    cashier: UserOut
    opening_amount: Decimal
    closing_amount: Optional[Decimal] = None
    expected_amount: Optional[Decimal] = None
    difference: Optional[Decimal] = None
    status: SessionStatus
    notes: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    movements: List[CashMovementOut] = []

    model_config = {"from_attributes": True, "populate_by_name": True}


# ─────────────────────────────────────────────────────────────────────────────
# Sales
# ─────────────────────────────────────────────────────────────────────────────

class SaleItemCreate(BaseModel):
    product_id: int
    quantity: float
    unit_price: Decimal
    discount_pct: float = 0.0


class SaleCreate(BaseModel):
    session_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_tax_id: Optional[str] = None
    items: List[SaleItemCreate]
    payment_method: PaymentMethod = PaymentMethod.CASH
    payment_amount: Decimal
    discount_amount: Decimal = Decimal("0.00")
    cash_tendered: Decimal = Decimal("0.00")   # parte pagada en efectivo (mixto: solo esa parte)
    notes: Optional[str] = None


class SaleItemOut(BaseModel):
    id: int
    product_id: Optional[int]
    product_code: str
    product_name: str
    quantity: float
    unit_price: Decimal
    discount_pct: float
    tax_rate: float
    subtotal: Decimal

    model_config = {"from_attributes": True}


class SaleOut(BaseModel):
    id: int
    folio: str
    cashier: UserOut
    customer_name: Optional[str]
    customer_tax_id: Optional[str]
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total: Decimal
    payment_method: PaymentMethod
    payment_amount: Decimal
    change_amount: Decimal
    cash_tendered: Decimal = Decimal("0.00")
    commission_pct: float = 0.0
    commission_amount: Decimal = Decimal("0.00")
    # str en lugar de SaleStatus para tolerar valores en mayúsculas del legado en BD
    status: str

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v):
        return v.lower() if isinstance(v, str) else v
    notes: Optional[str]
    created_at: datetime
    items: List[SaleItemOut] = []

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Clip PinPad
# ─────────────────────────────────────────────────────────────────────────────

class ClipTerminalOut(BaseModel):
    id: int
    name: str
    serial_number: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClipTerminalCreate(BaseModel):
    name: str
    serial_number: str


class ClipTerminalUpdate(BaseModel):
    name: Optional[str] = None
    serial_number: Optional[str] = None
    is_active: Optional[bool] = None


class ClipPaymentCreate(BaseModel):
    sale_payload: SaleCreate
    tip_amount: Decimal = Decimal("0.00")
    clip_terminal_id: Optional[int] = None  # si no se manda, se usa el de la caja activa


class ClipPaymentOut(BaseModel):
    id: int
    sale_id: Optional[int] = None
    clip_terminal_id: int
    reference: str
    pinpad_request_id: Optional[str] = None
    amount: Decimal
    tip_amount: Decimal
    amount_paid: Optional[Decimal] = None
    status: str
    error_message: Optional[str] = None
    card_brand: Optional[str] = None
    last4: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    sale: Optional[SaleOut] = None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

class DailySummary(BaseModel):
    date: str
    total_sales: int
    total_revenue: Decimal
    total_tax: Decimal
    total_discounts: Decimal
    cash_sales: Decimal
    card_sales: Decimal
    transfer_sales: Decimal
    cancelled_sales: int
    top_products: List[dict]
    sales_by_hour: List[dict]


class SessionSummary(BaseModel):
    session: CashSessionOut
    total_sales: int
    total_revenue: Decimal
    cash_in: Decimal
    cash_out: Decimal
    movements_total: Decimal


# ─────────────────────────────────────────────────────────────────────────────
# App Config
# ─────────────────────────────────────────────────────────────────────────────

class ConfigItem(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str]
    category: str = "general"


class ConfigUpdate(BaseModel):
    value: str


class ConfigBulkUpdate(BaseModel):
    configs: List[ConfigItem]


# Pydantic v2: resolver forward references declaradas con "UserOut"
Token.model_rebuild()
