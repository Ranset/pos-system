"""
POS System – Punto de entrada de la aplicación Flet
Ejecutar con: flet run main.py  (modo escritorio)
              flet run --web main.py  (modo web para red local)
"""
import flet as ft
import sys
import os

# Asegurar que el directorio raíz esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, APP_TITLE, APP_VERSION, ERROR, WARNING
from services import api, APIError
from views import (
    login_view, pos_view, products_view,
    inventory_view, users_view, cash_view,
    reports_view, settings_view,
)
from components import build_nav_rail


# ── Índices de vistas ─────────────────────────────────────────────────────────
VIEW_POS         = 0
VIEW_CASH        = 1
VIEW_PRODUCTS    = 2
VIEW_INVENTORY   = 3
VIEW_USERS       = 4
VIEW_REPORTS     = 5
VIEW_SETTINGS    = 6


def main(page: ft.Page):
    # ── Configuración de la ventana ───────────────────────────────────────────
    page.title            = APP_TITLE
    page.theme_mode       = ft.ThemeMode.DARK
    page.bgcolor          = BG_DARK
    page.window_width     = 1280
    page.window_height    = 800
    page.window_min_width = 1024
    page.window_min_height= 680
    page.padding          = 0
    page.spacing          = 0
    page.fonts = {
        "monospace": "Courier New",
    }
    page.theme = ft.Theme(
        color_scheme_seed=PRIMARY,
        visual_density="compact",   # ft.VisualDensity no existe en Flet 0.21.x
    )

    # ── Estado global de la aplicación ───────────────────────────────────────
    app_state = {
        "config":     {},
        "session_id": None,
        "session_info": None,
        "pos_active": False,   # True solo cuando el POS es la vista activa
    }

    # ── Contenedor principal ──────────────────────────────────────────────────
    content_area = ft.Container(expand=True)
    nav_container = ft.Container(content=None)
    current_view_index = {"val": VIEW_POS}

    loading_overlay = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.colors.with_opacity(0.6, ft.colors.BLACK),
        alignment=ft.alignment.center,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.ProgressRing(color=PRIMARY, width=48, height=48),
                ft.Text("Cargando...", color=ft.colors.WHITE),
            ],
        ),
    )

    def show_loading(visible: bool):
        loading_overlay.visible = visible
        page.update()

    # ── Inicio de sesión ──────────────────────────────────────────────────────

    def on_login_success():
        _load_app_config()
        _load_session_info()
        navigate_to(VIEW_POS)
        rebuild_layout()

    def _load_app_config():
        try:
            app_state["config"] = api.get_config_map()
        except Exception:
            app_state["config"] = {}

    def _load_session_info():
        """Carga la sesión activa del usuario actual.
        Cajeros solo toman su propia sesión; gerentes/admins toman la primera disponible.
        En caso de error resetea el estado para no dejar datos obsoletos."""
        try:
            sessions = api.get_active_sessions()
            if not sessions:
                app_state["session_id"]   = None
                app_state["session_info"] = None
                return

            # Comparación de IDs con conversión explícita (evita mismatch int vs str)
            my_id  = (api.current_user or {}).get("id")
            is_mgr = api.is_manager()

            def same_user(s: dict) -> bool:
                try:
                    return int((s.get("cashier") or {}).get("id", -1)) == int(my_id)
                except (TypeError, ValueError):
                    return False

            my_sessions = [s for s in sessions if same_user(s)]

            if is_mgr:
                # Gerente/Admin: prefiere su propia sesión; si no tiene, toma la primera
                chosen = my_sessions[0] if my_sessions else sessions[0]
            else:
                # Cajero: SOLO usa la sesión que él mismo abrió
                chosen = my_sessions[0] if my_sessions else None

            if chosen:
                app_state["session_id"]   = chosen["id"]
                app_state["session_info"] = {
                    "id":       chosen["id"],
                    "register": chosen["register"]["name"],
                    "cashier":  chosen["cashier"]["full_name"],
                }
            else:
                app_state["session_id"]   = None
                app_state["session_info"] = None

        except Exception as e:
            # Resetear en lugar de dejar datos obsoletos de una sesión anterior
            print(f"[session_info] Error: {e}")
            app_state["session_id"]   = None
            app_state["session_info"] = None

    # ── Navegación ────────────────────────────────────────────────────────────

    VIEW_BUILDERS = {
        VIEW_POS:       lambda: pos_view(page, app_state),
        VIEW_CASH:      lambda: cash_view(page, app_state),
        VIEW_PRODUCTS:  lambda: products_view(page, app_state),
        VIEW_INVENTORY: lambda: inventory_view(page, app_state),
        VIEW_USERS:     lambda: users_view(page, app_state),
        VIEW_REPORTS:   lambda: reports_view(page, app_state),
        VIEW_SETTINGS:  lambda: settings_view(page, app_state),
    }

    def navigate_to(index: int):
        # Desactivar handlers del POS al navegar a cualquier otra vista
        app_state["pos_active"] = (index == VIEW_POS)
        # Restaurar handler global de teclado al salir del POS u otra vista
        page.on_keyboard_event = on_keyboard
        current_view_index["val"] = index
        builder = VIEW_BUILDERS.get(index, lambda: ft.Text("Vista no encontrada"))
        content_area.content = builder()
        # Refrescar info de sesión al ir a POS o Caja
        if index in (VIEW_POS, VIEW_CASH):
            _load_session_info()
        _rebuild_nav()
        page.update()

    def on_nav_change(index: int):
        navigate_to(index)

    def on_logout(e=None):
        def confirm(_):
            api.logout()
            app_state.update({"config": {}, "session_id": None, "session_info": None})
            page.dialog.open = False
            show_login_screen()
        dlg = ft.AlertDialog(
            title=ft.Text("Cerrar sesión"),
            content=ft.Text("¿Deseas cerrar tu sesión?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(page.dialog,'open',False) or page.update()),
                ft.ElevatedButton("Cerrar sesión", on_click=confirm,
                                  style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    def _rebuild_nav():
        nav_container.content = build_nav_rail(
            selected_index=current_view_index["val"],
            on_change=on_nav_change,
            on_logout=on_logout,
            session_info=app_state.get("session_info"),
        )

    def rebuild_layout():
        _rebuild_nav()
        page.controls.clear()
        page.add(
            ft.Stack(
                expand=True,
                controls=[
                    ft.Row(
                        expand=True,
                        spacing=0,
                        controls=[
                            nav_container,
                            ft.VerticalDivider(width=1, color=ft.colors.WHITE12),
                            content_area,
                        ],
                    ),
                    loading_overlay,
                ],
            )
        )
        page.update()

    def show_login_screen():
        page.controls.clear()
        page.add(login_view(page, on_login_success))
        page.update()

    # ── Barra de estado ───────────────────────────────────────────────────────

    def build_status_bar():
        user = api.current_user or {}
        session_text = ""
        if app_state.get("session_id"):
            info = app_state.get("session_info") or {}
            session_text = f"  •  Caja: {info.get('register','')}"
        return ft.Container(
            bgcolor=ft.colors.with_opacity(0.5, ft.colors.BLACK),
            padding=ft.padding.symmetric(horizontal=12, vertical=3),
            content=ft.Row([
                ft.Text(f"v{APP_VERSION}", size=10, color=ft.colors.WHITE24),
                ft.Text(f"Usuario: {user.get('full_name','')}  ({user.get('role','')})" + session_text,
                        size=10, color=ft.colors.WHITE38, expand=True, text_align=ft.TextAlign.CENTER),
                ft.Text("Red local", size=10, color=ft.colors.WHITE24),
            ]),
        )

    # ── Shortcuts de teclado ──────────────────────────────────────────────────

    def on_keyboard(e: ft.KeyboardEvent):
        if not api.is_authenticated:
            return
        if e.ctrl:
            key_map = {
                "1": VIEW_POS, "2": VIEW_CASH, "3": VIEW_PRODUCTS,
                "4": VIEW_INVENTORY, "5": VIEW_USERS, "6": VIEW_REPORTS, "7": VIEW_SETTINGS,
            }
            if e.key in key_map:
                navigate_to(key_map[e.key])

    page.on_keyboard_event = on_keyboard

    # ── Verificar conexión con backend ────────────────────────────────────────

    def check_backend():
        import httpx
        try:
            r = httpx.get(api.base_url.replace("/api","") + "/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # ── Arranque ──────────────────────────────────────────────────────────────

    if not check_backend():
        page.add(ft.Container(
            expand=True, bgcolor=BG_DARK, alignment=ft.alignment.center,
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16, controls=[
                ft.Icon(ft.icons.WIFI_OFF, size=72, color=ft.colors.WHITE24),
                ft.Text("No se puede conectar al servidor", size=22, color=ft.colors.WHITE),
                ft.Text(f"Verifica que el backend esté corriendo en:\n{api.base_url}",
                        size=13, color=ft.colors.WHITE54, text_align=ft.TextAlign.CENTER),
                ft.ElevatedButton(
                    "Reintentar",
                    icon=ft.icons.REFRESH,
                    on_click=lambda _: main(page),
                    style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                ),
            ]),
        ))
        return

    show_login_screen()


if __name__ == "__main__":
    ft.app(target=main)
