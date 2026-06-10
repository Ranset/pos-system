from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Product, Category, Inventory, InventoryMovement
from ..schemas import (
    ProductOut, ProductCreate, ProductUpdate, CategoryOut,
    CategoryCreate, CategoryUpdate, StockAdjustment, InventoryOut,
    InventoryMovementOut,
)
from ..services.auth import require_manager, require_cashier, get_current_user

router = APIRouter(prefix="/products", tags=["Productos"])
cat_router = APIRouter(prefix="/categories", tags=["Categorías"])


# ── Categorías ────────────────────────────────────────────────────────────────

@cat_router.get("/", response_model=List[CategoryOut])
def list_categories(db: Session = Depends(get_db), _=Depends(require_cashier)):
    return db.query(Category).filter(Category.is_active == True).order_by(Category.name).all()


@cat_router.post("/", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryCreate, db: Session = Depends(get_db), _=Depends(require_manager)):
    if db.query(Category).filter(Category.name == data.name).first():
        raise HTTPException(400, "La categoría ya existe")
    cat = Category(**data.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@cat_router.put("/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: int, data: CategoryUpdate, db: Session = Depends(get_db), _=Depends(require_manager)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(404, "Categoría no encontrada")
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(cat, field, val)
    db.commit()
    db.refresh(cat)
    return cat


@cat_router.delete("/{cat_id}", status_code=204)
def delete_category(cat_id: int, db: Session = Depends(get_db), _=Depends(require_manager)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(404, "Categoría no encontrada")
    cat.is_active = False
    db.commit()


# ── Productos ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ProductOut])
def list_products(
    search: Optional[str] = Query(None),
    category_id: Optional[int] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    q = db.query(Product).options(
        joinedload(Product.category), joinedload(Product.inventory)
    )
    if active_only:
        q = q.filter(Product.is_active == True)
    if category_id:
        q = q.filter(Product.category_id == category_id)
    if search:
        term = f"%{search}%"
        q = q.filter(Product.name.ilike(term) | Product.code.ilike(term))
    return q.order_by(Product.name).all()


@router.get("/barcode/{code}", response_model=ProductOut)
def get_by_barcode(code: str, db: Session = Depends(get_db), _=Depends(require_cashier)):
    product = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.inventory))
        .filter(Product.code == code, Product.is_active == True)
        .first()
    )
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db), _=Depends(require_cashier)):
    product = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.inventory))
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    return product


@router.post("/", response_model=ProductOut, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db), _=Depends(require_manager)):
    if db.query(Product).filter(Product.code == data.code).first():
        raise HTTPException(400, "El código de producto ya existe")

    product_data = data.model_dump(exclude={"initial_stock", "min_stock", "max_stock"})
    product = Product(**product_data)
    db.add(product)
    db.flush()

    inv = Inventory(
        product_id=product.id,
        quantity=data.initial_stock,
        min_stock=data.min_stock,
        max_stock=data.max_stock,
    )
    db.add(inv)
    db.commit()
    db.refresh(product)
    return product


@router.put("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db), _=Depends(require_manager)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    if data.code and data.code != product.code:
        if db.query(Product).filter(Product.code == data.code).first():
            raise HTTPException(400, "El código ya está en uso")
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(product, field, val)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), _=Depends(require_manager)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    product.is_active = False
    db.commit()


# ── Inventario ────────────────────────────────────────────────────────────────

@router.get("/{product_id}/inventory", response_model=InventoryOut)
def get_inventory(product_id: int, db: Session = Depends(get_db), _=Depends(require_cashier)):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    return inv


@router.post("/inventory/adjust")
def adjust_stock(
    data: StockAdjustment,
    db: Session = Depends(get_db),
    current=Depends(require_manager),
):
    inv = db.query(Inventory).filter(Inventory.product_id == data.product_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")

    prev_qty = inv.quantity
    inv.quantity += data.quantity

    if inv.quantity < 0:
        raise HTTPException(400, "Stock no puede ser negativo")

    movement = InventoryMovement(
        inventory_id=inv.id,
        user_id=current.id,
        movement_type=data.movement_type,
        quantity=abs(data.quantity),
        previous_quantity=prev_qty,
        new_quantity=inv.quantity,
        reason=data.reason,
    )
    db.add(movement)
    db.commit()
    return {"detail": "Stock actualizado", "new_quantity": inv.quantity}


@router.get("/{product_id}/inventory/movements", response_model=List[InventoryMovementOut])
def get_inventory_movements(
    product_id: int,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")

    movements = (
        db.query(InventoryMovement)
        .options(joinedload(InventoryMovement.user))
        .filter(InventoryMovement.inventory_id == inv.id)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for m in movements:
        result.append(InventoryMovementOut(
            id=m.id,
            movement_type=m.movement_type,
            quantity=m.quantity,
            previous_quantity=m.previous_quantity,
            new_quantity=m.new_quantity,
            reason=m.reason,
            reference_id=m.reference_id,
            created_at=m.created_at,
            user_name=m.user.full_name if m.user else None,
        ))
    return result


@router.get("/inventory/low-stock")
def low_stock(db: Session = Depends(get_db), _=Depends(require_cashier)):
    from sqlalchemy import text
    results = (
        db.query(Product, Inventory)
        .join(Inventory, Product.id == Inventory.product_id)
        .filter(Inventory.quantity <= Inventory.min_stock, Product.is_active == True)
        .all()
    )
    return [
        {
            "product_id": p.id, "code": p.code, "name": p.name,
            "quantity": i.quantity, "min_stock": i.min_stock,
        }
        for p, i in results
    ]
