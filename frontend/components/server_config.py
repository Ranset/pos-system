"""
Botón y diálogo para configurar la dirección (IP o dominio) del servidor backend.
"""
import flet as ft
from config import PRIMARY, ERROR
from services import api


def build_server_config_button(page: ft.Page, on_saved=None) -> ft.IconButton:
    """Botón discreto que abre un diálogo para cambiar la dirección del backend."""

    url_field = ft.TextField(
        label="Dirección del servidor",
        hint_text="http://192.168.1.80:8000/api",
        width=380,
        border_color=PRIMARY,
        focused_border_color=PRIMARY,
        color=ft.colors.WHITE,
        label_style=ft.TextStyle(color=ft.colors.WHITE70),
        bgcolor=ft.colors.WHITE10,
    )
    error_text = ft.Text("", color=ERROR, size=12)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Configurar servidor"),
        content=ft.Column(
            tight=True,
            spacing=12,
            width=380,
            controls=[
                ft.Text(
                    "Ingresa la IP o el nombre de dominio del servidor backend "
                    "(puedes incluir el puerto, ej. 192.168.1.80:8000).",
                    size=12, color=ft.colors.WHITE54,
                ),
                url_field,
                error_text,
            ],
        ),
    )

    def close_dialog(_=None):
        dlg.open = False
        page.update()

    def save(_=None):
        value = (url_field.value or "").strip()
        if not value:
            error_text.value = "Ingresa una dirección"
            page.update()
            return

        if not value.startswith("http://") and not value.startswith("https://"):
            value = f"http://{value}"
        value = value.rstrip("/")
        if not value.endswith("/api"):
            value = f"{value}/api"

        api.set_base_url(value)
        close_dialog()
        if on_saved:
            on_saved()

    dlg.actions = [
        ft.TextButton("Cancelar", on_click=close_dialog),
        ft.ElevatedButton(
            "Guardar",
            on_click=save,
            style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
        ),
    ]

    def open_dialog(_=None):
        url_field.value = api.base_url
        error_text.value = ""
        page.dialog = dlg
        dlg.open = True
        page.update()

    return ft.IconButton(
        icon=ft.icons.SETTINGS_ETHERNET,
        icon_color=ft.colors.WHITE24,
        icon_size=20,
        tooltip="Configurar dirección del servidor",
        on_click=open_dialog,
    )
