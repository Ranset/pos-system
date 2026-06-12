"""
Vista de Login - Pantalla de autenticación
"""
import flet as ft
from config import PRIMARY, BG_DARK, BG_CARD, ERROR, APP_TITLE
from services import api, APIError
from components import build_server_config_button


def login_view(page: ft.Page, on_login_success):
    """Devuelve el control de la pantalla de login."""

    username_field = ft.TextField(
        label="Usuario",
        prefix_icon=ft.icons.PERSON,
        width=340,
        autofocus=True,
        border_color=PRIMARY,
        focused_border_color=PRIMARY,
        color=ft.colors.WHITE,
        label_style=ft.TextStyle(color=ft.colors.WHITE70),
        bgcolor=ft.colors.WHITE10,
    )
    password_field = ft.TextField(
        label="Contraseña",
        prefix_icon=ft.icons.LOCK,
        password=True,
        can_reveal_password=True,
        width=340,
        border_color=PRIMARY,
        focused_border_color=PRIMARY,
        color=ft.colors.WHITE,
        label_style=ft.TextStyle(color=ft.colors.WHITE70),
        bgcolor=ft.colors.WHITE10,
    )
    error_text = ft.Text("", color=ERROR, size=13)
    loading = ft.ProgressRing(visible=False, width=24, height=24, color=PRIMARY)

    def do_login(e=None):
        error_text.value = ""
        user = username_field.value.strip()
        pwd = password_field.value.strip()

        if not user or not pwd:
            error_text.value = "Completa todos los campos"
            page.update()
            return

        loading.visible = True
        page.update()
        try:
            api.login(user, pwd)
            on_login_success()
        except APIError as ex:
            error_text.value = str(ex)
        except Exception as ex:
            error_text.value = f"Error de conexión: {ex}"
        finally:
            loading.visible = False
            page.update()

    password_field.on_submit = do_login

    try:
        import pyi_splash # type: ignore # Es normal que marque error se importa con pyinstaller
        # Close the splash screen. It does not matter when the call
        # to this function is made, the splash screen remains open until
        # this function is called or the Python program is terminated.
        pyi_splash.close()
    except:
        pass

    server_config_button = build_server_config_button(page)
    server_config_button.top = 12
    server_config_button.right = 12

    return ft.Stack(
        expand=True,
        controls=[
            ft.Container(
                expand=True,
                bgcolor=BG_DARK,
                alignment=ft.alignment.center,
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                    controls=[
                        ft.Container(
                            bgcolor=BG_CARD,
                            border_radius=16,
                            padding=40,
                            width=400,
                            content=ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=20,
                                controls=[
                                    ft.Icon(ft.icons.POINT_OF_SALE, size=64, color=PRIMARY),
                                    ft.Text(APP_TITLE, size=26, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                                    ft.Text("Inicia sesión para continuar", size=13, color=ft.colors.WHITE54),
                                    ft.Divider(color=ft.colors.WHITE12),
                                    username_field,
                                    password_field,
                                    error_text,
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        controls=[loading],
                                    ),
                                    ft.ElevatedButton(
                                        text="Iniciar sesión",
                                        icon=ft.icons.LOGIN,
                                        width=340,
                                        height=48,
                                        on_click=do_login,
                                        style=ft.ButtonStyle(
                                            bgcolor=PRIMARY,
                                            color=ft.colors.WHITE,
                                            shape=ft.RoundedRectangleBorder(radius=8),
                                        ),
                                    ),
                                ],
                            ),
                        )
                    ],
                ),
            ),
            server_config_button,
        ],
    )
