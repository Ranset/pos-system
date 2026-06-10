"""
Vista de Gestión de Usuarios – Roles y Permisos
"""
import flet as ft
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError

ROLE_LABELS = {"admin": "Administrador", "manager": "Gerente", "cashier": "Cajero"}
ROLE_COLORS = {"admin": "#E53935", "manager": "#FB8C00", "cashier": "#43A047"}
ROLE_ICONS  = {"admin": ft.icons.SHIELD, "manager": ft.icons.MANAGE_ACCOUNTS,
                "cashier": ft.icons.POINT_OF_SALE}

PERMS_INFO = {
    "admin":   ["✅ Acceso total al sistema", "✅ Gestión de usuarios", "✅ Configuración avanzada",
                "✅ Cancelar ventas", "✅ Reportes completos", "✅ Ajuste de inventario"],
    "manager": ["✅ Gestión de productos", "✅ Ajuste de inventario", "✅ Cancelar ventas",
                "✅ Reportes", "✅ Apertura/cierre de caja", "❌ Gestión de usuarios", "❌ Configuración"],
    "cashier": ["✅ Registrar ventas", "✅ Ver productos e inventario", "✅ Apertura/cierre de caja",
                "❌ Cancelar ventas", "❌ Reportes", "❌ Gestión de productos"],
}


def users_view(page: ft.Page, app_state: dict):
    if not api.is_admin():
        return ft.Container(
            expand=True, bgcolor=BG_DARK,
            alignment=ft.alignment.center,
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.icons.LOCK, size=64, color=ft.colors.WHITE24),
                ft.Text("Acceso restringido", size=18, color=ft.colors.WHITE54),
                ft.Text("Solo administradores pueden gestionar usuarios.", color=ft.colors.WHITE38),
            ]),
        )

    users_data: list = []
    status_text = ft.Text("", color=ft.colors.WHITE54, size=12)

    # ── Tarjetas de estadísticas ──────────────────────────────────────────────

    stat_admin   = ft.Text("0", size=26, weight=ft.FontWeight.BOLD, color=ROLE_COLORS["admin"])
    stat_manager = ft.Text("0", size=26, weight=ft.FontWeight.BOLD, color=ROLE_COLORS["manager"])
    stat_cashier = ft.Text("0", size=26, weight=ft.FontWeight.BOLD, color=ROLE_COLORS["cashier"])
    stat_inactive= ft.Text("0", size=26, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE38)

    def _stat_card(label, value_ctrl, color, icon):
        return ft.Container(
            expand=True, bgcolor=BG_CARD, border_radius=10,
            border=ft.border.all(1, color + "44"),
            padding=ft.padding.all(16),
            content=ft.Column(spacing=4, controls=[
                ft.Row([ft.Icon(icon, color=color, size=20), ft.Text(label, color=ft.colors.WHITE60, size=12)]),
                value_ctrl,
            ]),
        )

    stats_row = ft.Row(
        controls=[
            _stat_card("Administradores", stat_admin, ROLE_COLORS["admin"], ft.icons.SHIELD),
            _stat_card("Gerentes", stat_manager, ROLE_COLORS["manager"], ft.icons.MANAGE_ACCOUNTS),
            _stat_card("Cajeros", stat_cashier, ROLE_COLORS["cashier"], ft.icons.POINT_OF_SALE),
            _stat_card("Inactivos", stat_inactive, ft.colors.WHITE38, ft.icons.PERSON_OFF),
        ],
        spacing=10,
    )

    # ── Lista de usuarios ─────────────────────────────────────────────────────

    users_list = ft.ListView(expand=True, spacing=8, padding=8)

    # ── Controles de filtro directos (sin ft.Ref) ─────────────────────────────
    search_field = ft.TextField(
        hint_text="Buscar usuario...",
        prefix_icon=ft.icons.SEARCH,
        expand=True,
        bgcolor=BG_SURFACE,
        border_color=PRIMARY,
        color=ft.colors.WHITE,
        hint_style=ft.TextStyle(color=ft.colors.WHITE38),
    )
    role_dropdown = ft.Dropdown(
        label="Filtrar por rol",
        value="all",
        width=200,
        color=ft.colors.WHITE,
        border_color=PRIMARY,
        options=[
            ft.dropdown.Option("all",     "Todos los roles"),
            ft.dropdown.Option("admin",   "Administradores"),
            ft.dropdown.Option("manager", "Gerentes"),
            ft.dropdown.Option("cashier", "Cajeros"),
        ],
    )


    def _show_snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    def load_users(e=None):
        try:
            nonlocal users_data
            users_data = api.get_users()
            _filter_and_render()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def _filter_and_render():
        search = (search_field.value or "").strip().lower()
        role_val = role_dropdown.value or "all"

        filtered = [
            u for u in users_data
            if (not search or search in u.get("username","").lower() or search in u.get("full_name","").lower())
            and (role_val == "all" or u.get("role","") == role_val)
        ]

        # Estadísticas
        stat_admin.value   = str(sum(1 for u in users_data if u.get("role") == "admin"))
        stat_manager.value = str(sum(1 for u in users_data if u.get("role") == "manager"))
        stat_cashier.value = str(sum(1 for u in users_data if u.get("role") == "cashier"))
        stat_inactive.value= str(sum(1 for u in users_data if not u.get("is_active", True)))
        status_text.value  = f"{len(filtered)} usuario(s)"

        users_list.controls.clear()
        current_id = (api.current_user or {}).get("id")

        for u in filtered:
            role   = u.get("role", "cashier")
            active = u.get("is_active", True)
            is_me  = u.get("id") == current_id
            rcolor = ROLE_COLORS.get(role, PRIMARY)
            has_pin= bool(u.get("pin"))

            def make_edit(usr):   return lambda _: open_user_dialog(usr)
            def make_toggle(usr): return lambda _: toggle_user(usr)
            def make_reset(usr):  return lambda _: open_reset_pw_dialog(usr)
            def make_delete(usr): return lambda _: delete_user(usr)

            users_list.controls.append(ft.Container(
                bgcolor=BG_CARD,
                border_radius=10,
                border=ft.border.all(1, rcolor + "33" if active else ft.colors.WHITE12),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                content=ft.Row(
                    controls=[
                        # Avatar
                        ft.Container(
                            width=48, height=48, border_radius=24,
                            bgcolor=rcolor + "33",
                            border=ft.border.all(2, rcolor),
                            alignment=ft.alignment.center,
                            content=ft.Icon(ROLE_ICONS.get(role, ft.icons.PERSON),
                                            color=rcolor, size=24),
                        ),
                        # Info
                        ft.Column(
                            expand=True, spacing=2,
                            controls=[
                                ft.Row([
                                    ft.Text(u.get("full_name",""), color=ft.colors.WHITE,
                                            size=15, weight=ft.FontWeight.W_600),
                                    ft.Text("(Tú)" if is_me else "", color=PRIMARY_LT, size=12),
                                    ft.Container(
                                        content=ft.Text(ROLE_LABELS.get(role, role), size=11,
                                                        color=ft.colors.WHITE),
                                        bgcolor=rcolor + "55",
                                        border_radius=4,
                                        padding=ft.padding.symmetric(3, 8),
                                    ),
                                    ft.Container(
                                        content=ft.Text("Activo" if active else "Inactivo",
                                                        size=10, color=ft.colors.WHITE),
                                        bgcolor=SUCCESS+"55" if active else ERROR+"44",
                                        border_radius=4,
                                        padding=ft.padding.symmetric(2, 6),
                                    ),
                                ], spacing=8),
                                ft.Row([
                                    ft.Icon(ft.icons.PERSON, size=13, color=ft.colors.WHITE38),
                                    ft.Text(u.get("username",""), size=12, color=ft.colors.WHITE54),
                                    ft.Text("·", color=ft.colors.WHITE24),
                                    ft.Icon(ft.icons.EMAIL, size=13, color=ft.colors.WHITE38),
                                    ft.Text(u.get("email","—"), size=12, color=ft.colors.WHITE54),
                                    ft.Text("·", color=ft.colors.WHITE24),
                                    ft.Icon(ft.icons.PIN, size=13,
                                            color=SUCCESS if has_pin else ft.colors.WHITE24),
                                    ft.Text("PIN configurado" if has_pin else "Sin PIN",
                                            size=11, color=SUCCESS if has_pin else ft.colors.WHITE38),
                                ], spacing=4),
                            ],
                        ),
                        # Acciones
                        ft.Row(spacing=0, controls=[
                            ft.IconButton(ft.icons.EDIT_OUTLINED, icon_color=PRIMARY_LT,
                                          icon_size=20, on_click=make_edit(u), tooltip="Editar"),
                            ft.IconButton(ft.icons.LOCK_RESET, icon_color=WARNING,
                                          icon_size=20, on_click=make_reset(u), tooltip="Cambiar contraseña"),
                            ft.IconButton(
                                ft.icons.TOGGLE_ON if active else ft.icons.TOGGLE_OFF,
                                icon_color=SUCCESS if active else ERROR,
                                icon_size=22,
                                on_click=make_toggle(u) if not is_me else None,
                                tooltip="Activar/Desactivar",
                                disabled=is_me,
                            ),
                            ft.IconButton(
                                ft.icons.DELETE_FOREVER,
                                icon_color=ft.colors.RED_700 if not is_me else ft.colors.WHITE12,
                                icon_size=20,
                                on_click=make_delete(u) if not is_me else None,
                                tooltip="Eliminar usuario" if not is_me else "No puedes eliminarte a ti mismo",
                                disabled=is_me,
                            ),
                        ]),
                    ],
                    spacing=14,
                ),
            ))
        page.update()

    # ── Diálogo de usuario ────────────────────────────────────────────────────

    def open_user_dialog(user: dict = None):
        is_edit = user is not None

        f_username = ft.TextField(label="Nombre de usuario *",
                                  value=user.get("username","") if is_edit else "",
                                  read_only=is_edit)
        f_fullname = ft.TextField(label="Nombre completo *",
                                  value=user.get("full_name","") if is_edit else "")
        f_email    = ft.TextField(label="Correo electrónico",
                                  value=user.get("email","") if is_edit else "")
        f_role     = ft.Dropdown(
            label="Rol *",
            value=user.get("role","cashier") if is_edit else "cashier",
            options=[ft.dropdown.Option(k, v) for k, v in ROLE_LABELS.items()],
        )
        f_pin      = ft.TextField(label="PIN (4–6 dígitos, opcional)",
                                  value=user.get("pin","") if is_edit else "",
                                  keyboard_type=ft.KeyboardType.NUMBER,
                                  password=True, can_reveal_password=True, max_length=6)
        f_password = ft.TextField(label="Contraseña *" if not is_edit else "Nueva contraseña (dejar vacío = no cambiar)",
                                  password=True, can_reveal_password=True)
        perms_col  = ft.Column(spacing=4)
        err_text   = ft.Text("", color=ERROR, size=12)

        def update_perms(e=None):
            role = f_role.value or "cashier"
            perms_col.controls = [
                ft.Text(p, size=12, color=SUCCESS if p.startswith("✅") else ERROR)
                for p in PERMS_INFO.get(role, [])
            ]
            page.update()

        f_role.on_change = update_perms
        update_perms()

        def save(e):
            err_text.value = ""
            if not f_fullname.value.strip() or (not is_edit and not f_username.value.strip()):
                err_text.value = "Nombre de usuario y nombre completo son obligatorios"
                page.update(); return
            if not is_edit and not f_password.value:
                err_text.value = "La contraseña es obligatoria para nuevos usuarios"
                page.update(); return
            try:
                payload = {
                    "full_name": f_fullname.value.strip(),
                    "email": f_email.value.strip() or None,
                    "role": f_role.value,
                    "pin": f_pin.value.strip() or None,
                }
                if not is_edit:
                    payload["username"] = f_username.value.strip()
                    payload["password"] = f_password.value
                    api.create_user(payload)
                    _show_snack(f"✅ Usuario '{payload['username']}' creado")
                else:
                    if f_password.value:
                        payload["password"] = f_password.value
                    api.update_user(user["id"], payload)
                    _show_snack("✅ Usuario actualizado")
                dlg.open = False; page.update()
                load_users()
            except APIError as ex:
                err_text.value = str(ex); page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar Usuario" if is_edit else "Nuevo Usuario",
                           weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=520,
                content=ft.Row(
                    spacing=16,
                    controls=[
                        ft.Column(expand=2, spacing=10, controls=[
                            f_username, f_fullname, f_email, f_password, f_pin, f_role, err_text,
                        ]),
                        ft.VerticalDivider(color=ft.colors.WHITE12),
                        ft.Column(expand=1, spacing=6, controls=[
                            ft.Text("Permisos del rol", color=ft.colors.WHITE70, size=12,
                                    weight=ft.FontWeight.BOLD),
                            perms_col,
                        ]),
                    ],
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(dlg,'open',False) or page.update()),
                ft.ElevatedButton("Guardar", icon=ft.icons.SAVE, on_click=save,
                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    def toggle_user(user: dict):
        try:
            api.update_user(user["id"], {"is_active": not user.get("is_active", True)})
            load_users()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def delete_user(user: dict):
        name     = user.get("full_name", "")
        username = user.get("username", "")
        role     = ROLE_LABELS.get(user.get("role", ""), user.get("role", ""))
        is_active = user.get("is_active", True)

        def confirm(_):
            try:
                api.delete_user(user["id"])
                _show_snack(f"🗑  Usuario '{username}' eliminado permanentemente")
                load_users()
                page.dialog.open = False
                page.update()
            except APIError as ex:
                page.dialog.open = False
                page.update()
                # Error 409: tiene historial → ofrecer desactivar
                if ex.status_code == 409:
                    _open_fallback_dialog(user)
                else:
                    _show_snack(str(ex), ERROR)

        def _open_fallback_dialog(u: dict):
            """El usuario tiene historial: ofrecer desactivar como alternativa."""
            def deactivate(_):
                try:
                    api.update_user(u["id"], {"is_active": False})
                    _show_snack(f"Usuario '{u.get('username','')}' desactivado")
                    load_users()
                except APIError as ex2:
                    _show_snack(str(ex2), ERROR)
                page.dialog.open = False
                page.update()

            fallback = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.icons.INFO_OUTLINE, color=WARNING),
                    ft.Text("No se puede eliminar", weight=ft.FontWeight.BOLD),
                ], spacing=8),
                content=ft.Container(
                    width=400,
                    content=ft.Column(spacing=12, controls=[
                        ft.Container(
                            bgcolor=WARNING + "1A", border_radius=8,
                            padding=ft.padding.all(12),
                            content=ft.Text(
                                f"'{u.get('full_name','')}' tiene ventas o sesiones de caja "
                                "registradas en el historial. Eliminarlo rompería esos registros.",
                                size=13, color=ft.colors.WHITE70,
                            ),
                        ),
                        ft.Text(
                            "¿Deseas desactivarlo en su lugar?\n"
                            "No podrá iniciar sesión pero el historial se conserva.",
                            size=13, color=ft.colors.WHITE70,
                        ),
                    ]),
                ),
                actions=[
                    ft.TextButton("Cancelar",
                                  on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                    ft.ElevatedButton(
                        "Desactivar usuario", icon=ft.icons.TOGGLE_OFF,
                        on_click=deactivate,
                        style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK),
                    ),
                ],
            )
            page.dialog = fallback
            fallback.open = True
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.DELETE_FOREVER, color=ERROR, size=22),
                ft.Text("Eliminar usuario", weight=ft.FontWeight.BOLD, color=ERROR),
            ], spacing=8),
            content=ft.Container(
                width=400,
                content=ft.Column(spacing=12, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8,
                        padding=ft.padding.all(12),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.PERSON, color=ft.colors.WHITE60, size=16),
                                ft.Text(name, size=14, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=6),
                            ft.Text(f"@{username}  •  {role}",
                                    size=12, color=ft.colors.WHITE54),
                        ]),
                    ),
                    ft.Container(
                        bgcolor=BG_SURFACE, border_radius=8,
                        padding=ft.padding.all(10),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.INFO_OUTLINE, color=PRIMARY_LT, size=15),
                                ft.Text("¿Qué pasa al eliminar?",
                                        size=12, color=ft.colors.WHITE70,
                                        weight=ft.FontWeight.W_600),
                            ], spacing=6),
                            ft.Text(
                                "• El usuario se borra permanentemente de la base de datos\n"
                                "• Si tiene historial de ventas, se sugerirá desactivar en su lugar\n"
                                "• Esta acción no se puede deshacer",
                                size=12, color=ft.colors.WHITE54,
                            ),
                        ]),
                    ),
                ]),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: setattr(page.dialog, "open", False) or page.update(),
                ),
                ft.ElevatedButton(
                    "Sí, eliminar permanentemente",
                    icon=ft.icons.DELETE_FOREVER,
                    on_click=confirm,
                    style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE),
                ),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def open_reset_pw_dialog(user: dict):
        f_pw  = ft.TextField(label="Nueva contraseña *", password=True, can_reveal_password=True)
        f_pw2 = ft.TextField(label="Confirmar contraseña *", password=True, can_reveal_password=True)
        err_t = ft.Text("", color=ERROR, size=12)

        def save(e):
            if not f_pw.value or f_pw.value != f_pw2.value:
                err_t.value = "Las contraseñas no coinciden"; page.update(); return
            try:
                api.update_user(user["id"], {"password": f_pw.value})
                _show_snack(f"✅ Contraseña de '{user.get('username','')}' actualizada")
                dlg.open = False; page.update()
            except APIError as ex:
                err_t.value = str(ex); page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Cambiar contraseña – {user.get('full_name','')}"),
            content=ft.Column(spacing=10, controls=[f_pw, f_pw2, err_t]),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(dlg,'open',False) or page.update()),
                ft.ElevatedButton("Cambiar", on_click=save,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    # Conectar eventos
    search_field.on_submit = lambda _: _filter_and_render()
    search_field.on_change = lambda _: _filter_and_render()
    role_dropdown.on_change = lambda _: _filter_and_render()

    # Carga inicial
    load_users()

    return ft.Container(
        expand=True, bgcolor=BG_DARK,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                # Encabezado
                ft.Container(
                    bgcolor=BG_CARD,
                    padding=ft.padding.symmetric(horizontal=20, vertical=14),
                    content=ft.Row([
                        ft.Icon(ft.icons.GROUP, color=PRIMARY, size=26),
                        ft.Text("Gestión de Usuarios", size=20, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, expand=True),
                        ft.ElevatedButton(
                            "Nuevo usuario", icon=ft.icons.PERSON_ADD,
                            on_click=lambda _: open_user_dialog(),
                            style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                        ),
                    ], spacing=12),
                ),
                # Estadísticas
                ft.Container(padding=ft.padding.all(12), content=stats_row),
                # Filtros
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=4),
                    content=ft.Row(controls=[
                        search_field,
                        role_dropdown,
                        ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                      on_click=load_users, tooltip="Actualizar"),
                    ], spacing=10),
                ),
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=2),
                    content=status_text,
                ),
                ft.Container(expand=True, padding=ft.padding.symmetric(horizontal=12),
                             content=users_list),
            ],
        ),
    )
