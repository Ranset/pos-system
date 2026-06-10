"""
Cliente HTTP para comunicarse con el backend FastAPI.
Centraliza todas las llamadas a la API.
"""
import httpx
from typing import Optional, Any
from config import API_BASE_URL


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    def __init__(self):
        self.base_url = API_BASE_URL
        self.token: Optional[str] = None
        self.current_user: Optional[dict] = None
        self._timeout = httpx.Timeout(15.0)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _handle_response(self, resp: httpx.Response) -> Any:
        if resp.status_code in (200, 201):
            return resp.json()
        elif resp.status_code == 204:
            return None
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise APIError(str(detail), resp.status_code)

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.request(method, url, headers=self._headers(), **kwargs)
        return self._handle_response(resp)

    def get(self, path: str, params: dict = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, data: dict = None, form: dict = None):
        if form:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self.base_url}{path}",
                    data=form,
                    headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
                )
            return self._handle_response(resp)
        return self.request("POST", path, json=data)

    def put(self, path: str, data: dict):
        return self.request("PUT", path, json=data)

    def delete(self, path: str):
        return self.request("DELETE", path)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict:
        result = self.post("/auth/login", form={
            "username": username, "password": password,
            "grant_type": "password",
        })
        self.token = result["access_token"]
        self.current_user = result["user"]
        return result

    def logout(self):
        self.token = None
        self.current_user = None

    @property
    def is_authenticated(self) -> bool:
        return self.token is not None

    @property
    def user_role(self) -> str:
        return (self.current_user or {}).get("role", "")

    def is_admin(self) -> bool:
        return self.user_role == "admin"

    def is_manager(self) -> bool:
        return self.user_role in ("admin", "manager")

    # ── Users ─────────────────────────────────────────────────────────────────

    def get_users(self):
        return self.get("/users/")

    def create_user(self, data: dict):
        return self.post("/users/", data)

    def update_user(self, user_id: int, data: dict):
        return self.put(f"/users/{user_id}", data)

    def delete_user(self, user_id: int):
        return self.delete(f"/users/{user_id}")

    # ── Products ──────────────────────────────────────────────────────────────

    def get_products(self, search: str = None, category_id: int = None, active_only: bool = True):
        params = {"active_only": str(active_only).lower()}
        if search:
            params["search"] = search
        if category_id:
            params["category_id"] = category_id
        return self.get("/products/", params=params)

    def get_product_by_barcode(self, code: str):
        return self.get(f"/products/barcode/{code}")

    def create_product(self, data: dict):
        return self.post("/products/", data)

    def update_product(self, product_id: int, data: dict):
        return self.put(f"/products/{product_id}", data)

    def delete_product(self, product_id: int):
        return self.delete(f"/products/{product_id}")

    def adjust_stock(self, data: dict):
        return self.post("/products/inventory/adjust", data)

    def get_low_stock(self):
        return self.get("/products/inventory/low-stock")

    def get_categories(self):
        return self.get("/categories/")

    def create_category(self, data: dict):
        return self.post("/categories/", data)

    def update_category(self, cat_id: int, data: dict):
        return self.put(f"/categories/{cat_id}", data)

    # ── Sales ─────────────────────────────────────────────────────────────────

    def create_sale(self, data: dict):
        return self.post("/sales/", data)

    def get_sales(self, params: dict = None):
        return self.get("/sales/", params=params)

    def get_sale(self, sale_id: int):
        return self.get(f"/sales/{sale_id}")

    def verify_supervisor(self, username: str, password: str) -> dict:
        return self.request("POST", "/auth/verify-supervisor",
                            params={"username": username, "password": password})

    def get_sale_returns(self, sale_id: int) -> list:
        return self.get(f"/sales/{sale_id}/returns")

    def cancel_sale(self, sale_id: int, reason: str, supervisor_id: int = None):
        params = {"reason": reason}
        if supervisor_id:
            params["supervisor_id"] = supervisor_id
        return self.request("POST", f"/sales/{sale_id}/cancel", params=params)

    def process_return(self, sale_id: int, supervisor_id: int,
                       items: list, reason: str = "Devolución de cliente",
                       is_cash_return: bool = True):
        import json
        return self.request("POST", f"/sales/{sale_id}/return",
                            params={
                                "supervisor_id":  supervisor_id,
                                "reason":         reason,
                                "items":          json.dumps(items),
                                "is_cash_return": str(is_cash_return).lower(),
                            })

    # ── Cash ──────────────────────────────────────────────────────────────────

    def get_registers(self):
        return self.get("/cash/registers")

    def get_all_registers(self):
        return self.get("/cash/registers/all")

    def update_physical_count(self, session_id: int, closing_amount: float):
        return self.request("PATCH",
                            f"/cash/sessions/{session_id}/physical-count",
                            params={"closing_amount": closing_amount})
        return self.get("/cash/registers/all")

    def create_register(self, data: dict):
        return self.post("/cash/registers", data)

    def update_register(self, register_id: int, data: dict):
        return self.put(f"/cash/registers/{register_id}", data)

    def delete_register(self, register_id: int):
        return self.delete(f"/cash/registers/{register_id}")

    def get_active_sessions(self):
        return self.get("/cash/sessions/active")

    def open_session(self, data: dict):
        return self.post("/cash/open", data)

    def close_session(self, session_id: int, data: dict):
        return self.post(f"/cash/sessions/{session_id}/close", data)

    def add_cash_movement(self, session_id: int, data: dict):
        return self.post(f"/cash/sessions/{session_id}/movement", data)

    def get_sessions(self):
        return self.get("/cash/sessions")

    def get_session(self, session_id: int):
        return self.get(f"/cash/sessions/{session_id}")

    # ── Reports ───────────────────────────────────────────────────────────────

    def get_daily_report(self, target_date: str = None):
        params = {}
        if target_date:
            params["target_date"] = target_date
        return self.get("/reports/daily", params=params)

    def get_range_report(self, start: str, end: str):
        return self.get("/reports/range", params={"start": start, "end": end})

    def get_session_report(self, session_id: int):
        return self.get(f"/reports/session/{session_id}")

    # ── Config ────────────────────────────────────────────────────────────────

    def get_config_map(self):
        return self.get("/config/map")

    def get_configs(self, category: str = None):
        params = {}
        if category:
            params["category"] = category
        return self.get("/config/", params=params)

    def update_config(self, key: str, value: str):
        return self.put(f"/config/{key}", {"value": value})

    def bulk_update_config(self, configs: list):
        return self.put("/config/bulk/update", {"configs": configs})

    def init_config(self):
        return self.get("/config/initialize")

    # ── Administración de base de datos ───────────────────────────────────────
    def get_db_stats(self):
        return self.get("/admin/stats")

    def force_migrate(self):
        return self.post("/admin/force-migrate", {})

    def delete_all_sales(self):
        return self.delete("/admin/sales")

    def delete_all_sessions(self):
        return self.delete("/admin/sessions")

    def delete_inventory_movements(self):
        return self.delete("/admin/inventory-movements")

    def full_db_reset(self):
        return self.delete("/admin/all")


# Instancia global compartida
api = APIClient()
