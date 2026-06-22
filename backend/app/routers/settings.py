from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AppConfig
from ..schemas import ConfigItem, ConfigUpdate, ConfigBulkUpdate
from ..services.auth import require_admin, require_cashier, get_current_user

router = APIRouter(prefix="/config", tags=["Configuración"])

# Configuraciones por defecto del sistema
DEFAULT_CONFIGS = [
    # Tienda
    ("store.name", "Mi Tienda", "Nombre de la tienda", "store"),
    ("store.address", "", "Dirección", "store"),
    ("store.phone", "", "Teléfono", "store"),
    ("store.email", "", "Correo electrónico", "store"),
    ("store.tax_id", "", "RFC / NIT / RUC", "store"),
    ("store.logo_path", "", "Ruta del logo", "store"),
    ("store.footer_text", "¡Gracias por su compra!", "Texto pie de ticket", "store"),
    ("store.qr_content", "", "Contenido del código QR del ticket (URL o texto)", "store"),
    ("store.qr_cta_text", "¡Síguenos en nuestras redes!", "Título / llamada a la acción sobre el QR", "store"),
    # Fiscal
    ("fiscal.tax_name", "IVA", "Nombre del impuesto", "fiscal"),
    ("fiscal.default_tax_rate", "0.16", "Tasa de impuesto por defecto (0.16 = 16%)", "fiscal"),
    ("fiscal.print_tax_breakdown", "true", "Desglosar impuesto en ticket", "fiscal"),
    ("fiscal.currency_symbol", "$", "Símbolo de moneda", "fiscal"),
    ("fiscal.currency_name", "MXN", "Nombre de moneda", "fiscal"),
    ("fiscal.decimal_places", "2", "Decimales en precios", "fiscal"),
    # Impresora
    ("printer.enabled", "false", "Habilitar impresión automática", "printer"),
    ("printer.type", "usb", "Tipo: usb / serial / network", "printer"),
    ("printer.usb_vendor_id", "", "USB Vendor ID", "printer"),
    ("printer.usb_product_id", "", "USB Product ID", "printer"),
    ("printer.serial_port", "/dev/ttyUSB0", "Puerto serial", "printer"),
    ("printer.network_host", "", "IP de impresora en red", "printer"),
    ("printer.network_port", "9100", "Puerto de red", "printer"),
    ("printer.paper_width", "80", "Ancho de papel (mm): 58 o 80", "printer"),
    ("printer.open_drawer", "true", "Abrir cajón automáticamente", "printer"),
    ("printer.copies", "1", "Número de copias por ticket", "printer"),
    # POS
    ("pos.require_session", "true", "Requerir apertura de caja", "pos"),
    ("pos.allow_negative_stock", "false", "Permitir stock negativo", "pos"),
    ("pos.allow_price_edit", "false", "Permitir editar precio en POS", "pos"),
    ("pos.max_discount_pct", "10", "Descuento máximo global (%)", "pos"),
    ("pos.show_product_images", "true", "Mostrar imágenes de productos", "pos"),
    ("pos.beep_on_scan", "true", "Sonido al escanear", "pos"),
    # UI
    ("ui.theme", "dark", "Tema: dark / light", "ui"),
    ("ui.primary_color", "#1565C0", "Color primario", "ui"),
    ("ui.language", "es", "Idioma", "ui"),
    # ── Atajos de teclado ──────────────────────────────────────────────────────
    ("hotkey.pos.cobrar",              "F12",       "Ir a cobrar",                 "hotkeys"),
    ("hotkey.pos.refresh",             "F5",        "Actualizar catálogo",         "hotkeys"),
    ("hotkey.pos.clear_search",        "Escape",    "Limpiar búsqueda",            "hotkeys"),
    ("hotkey.payment.confirm",         "F12",       "Confirmar venta",             "hotkeys"),
    ("hotkey.payment.back",            "Escape",    "Volver al POS",               "hotkeys"),
    ("hotkey.payment.method_cash",     "F1",        "Método: Efectivo",            "hotkeys"),
    ("hotkey.payment.method_card",     "F2",        "Método: Tarjeta",             "hotkeys"),
    ("hotkey.payment.method_transfer", "F3",        "Método: Transferencia",       "hotkeys"),
    ("hotkey.payment.method_mixed",    "F4",        "Método: Mixto",               "hotkeys"),
    ("hotkey.payment.exact",           "F9",        "Monto exacto",                "hotkeys"),
    ("hotkey.payment.backspace",       "Backspace", "Borrar último dígito",        "hotkeys"),
    ("hotkey.payment.clear",           "Delete",    "Borrar monto completo",       "hotkeys"),
    ("hotkey.success.new_sale",        "Enter",     "Nueva venta (pantalla éxito)","hotkeys"),
    ("hotkey.success.print",           "P",         "Reimprimir ticket",           "hotkeys"),
]


@router.get("/initialize")
def initialize_defaults(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Inserta las configuraciones por defecto si no existen."""
    created = 0
    for key, val, desc, cat in DEFAULT_CONFIGS:
        exists = db.query(AppConfig).filter(AppConfig.key == key).first()
        if not exists:
            db.add(AppConfig(key=key, value=val, description=desc, category=cat))
            created += 1
    db.commit()
    return {"initialized": created}


@router.get("/", response_model=List[ConfigItem])
def get_all_configs(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_cashier),
):
    q = db.query(AppConfig)
    if category:
        q = q.filter(AppConfig.category == category)
    return q.order_by(AppConfig.category, AppConfig.key).all()


@router.get("/map")
def get_config_map(db: Session = Depends(get_db), _=Depends(require_cashier)):
    """Devuelve todas las configs como {key: value} para uso rápido en el frontend."""
    configs = db.query(AppConfig).all()
    return {c.key: c.value for c in configs}


@router.get("/{key}")
def get_config(key: str, db: Session = Depends(get_db), _=Depends(require_cashier)):
    cfg = db.query(AppConfig).filter(AppConfig.key == key).first()
    if not cfg:
        raise HTTPException(404, f"Configuración '{key}' no encontrada")
    return cfg


@router.put("/{key}")
def update_config(
    key: str,
    data: ConfigUpdate,
    db: Session = Depends(get_db),
    current=Depends(require_admin),
):
    """Actualiza o crea una configuración (upsert)."""
    cfg = db.query(AppConfig).filter(AppConfig.key == key).first()
    if not cfg:
        # Upsert: crear la clave si no existe (ej. hotkeys nuevos sin inicializar)
        # Inferir categoría desde el prefijo de la clave (ej. "hotkey.pos.cobrar" → "hotkeys")
        category = key.split(".")[0] + "s" if "." in key else "general"
        cfg = AppConfig(key=key, value=data.value, category=category,
                        updated_by=current.id)
        db.add(cfg)
    else:
        cfg.value = data.value
        cfg.updated_by = current.id
    db.commit()
    return {"detail": "Configuración actualizada", "key": key, "value": data.value}


@router.put("/bulk/update")
def bulk_update(
    data: ConfigBulkUpdate,
    db: Session = Depends(get_db),
    current=Depends(require_admin),
):
    updated = 0
    for item in data.configs:
        cfg = db.query(AppConfig).filter(AppConfig.key == item.key).first()
        if cfg:
            cfg.value = item.value
            cfg.updated_by = current.id
            updated += 1
        else:
            db.add(AppConfig(
                key=item.key, value=item.value,
                description=item.description, category=item.category,
            ))
            updated += 1
    db.commit()
    return {"updated": updated}
