"""
Barra de navegación lateral – NavigationRail con acceso por roles
"""
import flet as ft
from config import PRIMARY, PRIMARY_LT, BG_CARD, BG_SURFACE
from services import api

NAV_ITEMS = [
    # (index, label, icon, selected_icon, min_role)
    (0, "Punto de Venta", ft.icons.POINT_OF_SALE_OUTLINED, ft.icons.POINT_OF_SALE,     "cashier"),
    (1, "Caja",          ft.icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ft.icons.ACCOUNT_BALANCE_WALLET, "cashier"),
    (2, "Productos",     ft.icons.INVENTORY_2_OUTLINED,    ft.icons.INVENTORY_2,        "manager"),
    (3, "Inventario",    ft.icons.WAREHOUSE_OUTLINED,      ft.icons.WAREHOUSE,          "manager"),
    (7, "Ventas",        ft.icons.RECEIPT_LONG_OUTLINED,   ft.icons.RECEIPT_LONG,       "manager"),
    (4, "Usuarios",      ft.icons.GROUP_OUTLINED,          ft.icons.GROUP,              "admin"),
    (5, "Reportes",      ft.icons.ANALYTICS_OUTLINED,      ft.icons.ANALYTICS,          "manager"),
    (6, "Configuración", ft.icons.SETTINGS_OUTLINED,       ft.icons.SETTINGS,           "admin"),
]

ROLE_ORDER = {"cashier": 0, "manager": 1, "admin": 2}


def build_nav_rail(
    selected_index: int,
    on_change,
    on_logout,
    session_info: dict = None,
) -> ft.NavigationRail:
    user = api.current_user or {}
    role = user.get("role", "cashier")
    role_level = ROLE_ORDER.get(role, 0)

    def is_visible(min_role: str) -> bool:
        return role_level >= ROLE_ORDER.get(min_role, 0)

    destinations = [
        ft.NavigationRailDestination(
            icon_content=ft.Icon(icon, color=ft.colors.WHITE38),
            selected_icon_content=ft.Icon(sel_icon, color=PRIMARY_LT),
            label_content=ft.Text(label, size=11, color=ft.colors.WHITE70),
            padding=ft.padding.symmetric(vertical=2),
        )
        for _, label, icon, sel_icon, min_role in NAV_ITEMS
        if is_visible(min_role)
    ]

    # Mapa índice visual → índice lógico
    visible_indices = [idx for idx, _, _, _, min_role in NAV_ITEMS if is_visible(min_role)]

    def handle_change(e):
        visual_idx = e.control.selected_index
        logical_idx = visible_indices[visual_idx] if visual_idx < len(visible_indices) else 0
        on_change(logical_idx)

    # Ajustar selected_index al índice visual
    visual_selected = 0
    if selected_index in visible_indices:
        visual_selected = visible_indices.index(selected_index)

    # Info de sesión de caja
    session_badge = ft.Container()
    if session_info:
        session_badge = ft.Container(
            bgcolor=ft.colors.GREEN_900,
            border_radius=6,
            padding=ft.padding.symmetric(4, 6),
            content=ft.Column(spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.icons.CIRCLE, color=ft.colors.GREEN_400, size=8),
                ft.Text("Caja", size=9, color=ft.colors.GREEN_300),
                ft.Text(session_info.get("register",""), size=9, color=ft.colors.GREEN_200,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, width=56),
            ]),
        )

    return ft.NavigationRail(
        selected_index=visual_selected,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=72,
        min_extended_width=180,
        bgcolor=BG_CARD,
        indicator_color=PRIMARY + "33",
        indicator_shape=ft.RoundedRectangleBorder(radius=8),
        destinations=destinations,
        on_change=handle_change,
        leading=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            controls=[
                ft.Container(height=8),
                ft.Container(
                    width=40, height=40, border_radius=20,
                    bgcolor=PRIMARY + "33",
                    border=ft.border.all(2, PRIMARY),
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        (user.get("full_name","?")[:1]).upper(),
                        size=18, color=PRIMARY_LT, weight=ft.FontWeight.BOLD,
                    ),
                    tooltip=f"{user.get('full_name','')} ({role})",
                ),
                session_badge,
            ],
        ),
        trailing=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            controls=[
                ft.IconButton(
                    ft.icons.LOGOUT,
                    icon_color=ft.colors.WHITE38,
                    icon_size=20,
                    on_click=on_logout,
                    tooltip="Cerrar sesión",
                ),
            ],
        ),
    )
