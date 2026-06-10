from .login import login_view
from .pos import pos_view
from .products import products_view
from .inventory import inventory_view
from .users import users_view
from .cash import cash_view
from .sales import sales_view
from .reports import reports_view
from .settings import settings_view

__all__ = [
    "login_view", "pos_view", "products_view", "inventory_view",
    "users_view", "cash_view", "sales_view", "reports_view", "settings_view",
]
