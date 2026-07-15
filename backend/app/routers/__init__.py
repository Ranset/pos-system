from .auth import router as auth_router
from .users import router as users_router
from .products import router as products_router, cat_router as categories_router
from .sales import router as sales_router
from .cash import router as cash_router
from .reports import router as reports_router
from .settings import router as settings_router
from .admin import router as admin_router
from .clip import router as clip_router, webhook_router as clip_webhook_router

__all__ = [
    "auth_router", "users_router", "products_router", "categories_router",
    "sales_router", "cash_router", "reports_router", "settings_router",
    "admin_router", "clip_router", "clip_webhook_router",
]
