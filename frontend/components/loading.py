"""
Utilidades de UI para indicar que la aplicación está cargando datos
(no colgada) mientras se resuelve una llamada bloqueante a la API.
"""
import flet as ft


def loading_icon_button(page: ft.Page, icon, on_click, icon_color=None,
                        tooltip: str = None, size: int = 40) -> ft.Container:
    """IconButton que se reemplaza por un ft.ProgressRing mientras `on_click`
    hace su trabajo (normalmente una llamada bloqueante a la API), para que
    el usuario vea que se están cargando datos en vez de una app congelada."""
    ring = ft.ProgressRing(width=18, height=18, stroke_width=2,
                           color=icon_color, visible=False)
    btn = ft.IconButton(icon, icon_color=icon_color, tooltip=tooltip)

    def handler(e):
        btn.visible = False
        ring.visible = True
        page.update()
        try:
            on_click(e)
        finally:
            btn.visible = True
            ring.visible = False
            page.update()

    btn.on_click = handler
    return ft.Container(
        width=size, height=size, alignment=ft.alignment.center,
        content=ft.Stack([btn, ring], width=size, height=size),
    )
