"""
Vista de Configuración – Panel completo de ajustes del sistema POS
Incluye: configuración clave-valor y administración de cajas registradoras
"""
import flet as ft
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


# ── Grupos de configuración clave-valor ──────────────────────────────────────

CONFIG_GROUPS = [
    {
        "title": "🏪 Información de la Tienda",
        "category": "store",
        "icon": ft.icons.STORE,
        "fields": [
            ("store.name",        "Nombre de la tienda",      "text",   ""),
            ("store.address",     "Dirección",                "text",   ""),
            ("store.phone",       "Teléfono",                 "text",   ""),
            ("store.email",       "Correo electrónico",       "text",   ""),
            ("store.tax_id",      "RFC / NIT / RUC",          "text",   ""),
            ("store.footer_text", "Texto pie de ticket",      "text",   "¡Gracias por su compra!"),
        ],
    },
    {
        "title": "💰 Configuración Fiscal",
        "category": "fiscal",
        "icon": ft.icons.RECEIPT_LONG,
        "fields": [
            ("fiscal.tax_name",           "Nombre del impuesto",             "text",   "IVA"),
            ("fiscal.default_tax_rate",   "Tasa de impuesto (0.16 = 16%)",   "number", "0.16"),
            ("fiscal.currency_symbol",    "Símbolo de moneda",               "text",   "$"),
            ("fiscal.currency_name",      "Código de moneda",                "text",   "MXN"),
            ("fiscal.decimal_places",     "Decimales en precios",            "number", "2"),
            ("fiscal.print_tax_breakdown","Desglosar impuesto en ticket",    "bool",   "true"),
        ],
    },
    {
        "title": "🖨️ Impresora y Cajón",
        "category": "printer",
        "icon": ft.icons.PRINT,
        "fields": [
            ("printer.enabled",       "Habilitar impresión automática",          "bool",   "false"),
            ("printer.type",          "Tipo de conexión",                        "select", "usb|USB,serial|Serial,network|Red (TCP/IP)"),
            ("printer.usb_vendor_id", "USB Vendor ID (hex, ej: 0x0416)",         "text",   ""),
            ("printer.usb_product_id","USB Product ID (hex, ej: 0x5011)",        "text",   ""),
            ("printer.serial_port",   "Puerto serial (ej: COM3, /dev/ttyUSB0)",  "text",   "/dev/ttyUSB0"),
            ("printer.network_host",  "IP de impresora de red",                  "text",   ""),
            ("printer.network_port",  "Puerto de red",                           "number", "9100"),
            ("printer.paper_width",   "Ancho de papel (mm)",                     "select", "58|58 mm,80|80 mm"),
            ("printer.open_drawer",   "Abrir cajón automáticamente",             "bool",   "true"),
            ("printer.copies",        "Copias por ticket",                       "number", "1"),
        ],
    },
    {
        "title": "🖥️ Comportamiento del POS",
        "category": "pos",
        "icon": ft.icons.POINT_OF_SALE,
        "fields": [
            ("pos.require_session",      "Requerir apertura de caja",          "bool",   "true"),
            ("pos.allow_negative_stock", "Permitir stock negativo",             "bool",   "false"),
            ("pos.allow_price_edit",     "Permitir editar precio en venta",     "bool",   "false"),
            ("pos.max_discount_pct",     "Descuento máximo global (%)",         "number", "10"),
            ("pos.show_product_images",  "Mostrar imágenes de productos",       "bool",   "true"),
            ("pos.beep_on_scan",         "Sonido al escanear código",           "bool",   "true"),
        ],
    },
    {
        "title": "🎨 Apariencia",
        "category": "ui",
        "icon": ft.icons.PALETTE,
        "fields": [
            ("ui.primary_color", "Color primario (hex)", "color",  "#1565C0"),
            ("ui.language",      "Idioma",               "select", "es|Español,en|English"),
        ],
    },
]


def settings_view(page: ft.Page, app_state: dict):
    if not api.is_admin():
        return ft.Container(
            expand=True, bgcolor=BG_DARK, alignment=ft.alignment.center,
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.icons.LOCK, size=64, color=ft.colors.WHITE24),
                ft.Text("Acceso restringido", size=18, color=ft.colors.WHITE54),
                ft.Text("Solo administradores pueden modificar la configuración.",
                        color=ft.colors.WHITE38),
            ]),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PESTAÑA 1 – Configuración clave-valor
    # ─────────────────────────────────────────────────────────────────────────

    config_map: dict = {}
    field_refs: dict = {}
    unsaved_badge = ft.Container(
        visible=False,
        bgcolor=WARNING, border_radius=10,
        padding=ft.padding.symmetric(2, 8),
        content=ft.Text("Cambios sin guardar", size=11, color=ft.colors.BLACK),
    )

    def _show_snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    def mark_unsaved(e=None):
        unsaved_badge.visible = True
        page.update()

    def load_config():
        nonlocal config_map
        try:
            config_map = api.get_config_map()
            _rebuild_form()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def _build_field(key, label, ftype, default):
        current_val = config_map.get(key, default)

        if ftype == "bool":
            ctrl = ft.Switch(value=str(current_val).lower() == "true",
                             active_color=PRIMARY, on_change=mark_unsaved)
            field_refs[key] = ("bool", ctrl)
            return ft.Row([
                ft.Text(label, color=ft.colors.WHITE70, size=13, expand=True), ctrl,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        elif ftype == "select":
            options_raw = default.split(",")
            options = [ft.dropdown.Option(o.split("|")[0], o.split("|")[1]) for o in options_raw]
            ctrl = ft.Dropdown(value=str(current_val), options=options, width=220,
                               border_color=PRIMARY, color=ft.colors.WHITE, on_change=mark_unsaved)
            field_refs[key] = ("select", ctrl)
            return ft.Row([ft.Text(label, color=ft.colors.WHITE70, size=13, expand=True), ctrl])

        elif ftype == "color":
            preview = ft.Container(width=28, height=28, border_radius=6, bgcolor=current_val or PRIMARY)
            ctrl = ft.TextField(value=str(current_val), width=140, border_color=PRIMARY,
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE, hint_text="#RRGGBB")
            def update_preview(e):
                try: preview.bgcolor = ctrl.value
                except Exception: pass
                mark_unsaved(e)
            ctrl.on_change = update_preview
            field_refs[key] = ("color", ctrl)
            return ft.Row([ft.Text(label, color=ft.colors.WHITE70, size=13, expand=True),
                           preview, ctrl], spacing=8)

        else:
            ctrl = ft.TextField(value=str(current_val), border_color=PRIMARY,
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE,
                                keyboard_type=ft.KeyboardType.NUMBER if ftype == "number" else ft.KeyboardType.TEXT,
                                expand=True, on_change=mark_unsaved)
            field_refs[key] = ("text", ctrl)
            return ft.Row([ft.Text(label, color=ft.colors.WHITE70, size=13, width=220), ctrl], spacing=12)

    accordion = ft.ExpansionPanelList(
        expand_icon_color=PRIMARY, elevation=0,
        divider_color=ft.colors.WHITE12, controls=[],
    )

    def _rebuild_form():
        accordion.controls.clear()
        for group in CONFIG_GROUPS:
            field_controls = [_build_field(*f) for f in group["fields"]]
            accordion.controls.append(ft.ExpansionPanel(
                header=ft.ListTile(
                    leading=ft.Icon(group["icon"], color=PRIMARY),
                    title=ft.Text(group["title"], color=ft.colors.WHITE,
                                  weight=ft.FontWeight.W_600, size=14),
                ),
                content=ft.Container(
                    bgcolor=BG_SURFACE, padding=ft.padding.all(16),
                    border_radius=ft.border_radius.only(bottom_left=10, bottom_right=10),
                    content=ft.Column(spacing=12, controls=field_controls),
                ),
                bgcolor=BG_CARD, expanded=False,
            ))
        page.update()

    def save_all(e=None):
        try:
            configs = []
            for key, (ftype, ctrl) in field_refs.items():
                val = ("true" if ctrl.value else "false") if ftype == "bool" else str(ctrl.value or "")
                configs.append({"key": key, "value": val, "description": None, "category": "general"})
            api.bulk_update_config(configs)
            app_state["config"] = api.get_config_map()
            unsaved_badge.visible = False
            _show_snack("✅ Configuración guardada exitosamente")
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def reset_defaults(e=None):
        def confirm(_):
            try:
                api.init_config(); load_config()
                _show_snack("✅ Configuración restablecida a valores por defecto")
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.dialog.open = False; page.update()
        dlg = ft.AlertDialog(
            title=ft.Text("Restablecer configuración"),
            content=ft.Text("¿Restablecer todos los valores a su configuración por defecto?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                ft.ElevatedButton("Restablecer", on_click=confirm,
                                  style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    def test_printer(e=None):
        try:
            from services.printer import TicketPrinter
            tp = TicketPrinter(api.get_config_map())
            sale = {"folio": "TEST-0001",
                    "items": [{"product_name": "Producto de prueba", "quantity": 1,
                               "unit_price": 99.99, "subtotal": 99.99, "discount_pct": 0}],
                    "subtotal": 99.99, "tax_amount": 0, "discount_amount": 0, "total": 99.99,
                    "payment_method": "cash", "payment_amount": 100, "change_amount": 0.01}
            ok = tp.print_ticket(sale)
            _show_snack("✅ Ticket de prueba enviado" if ok else "⚠️ Impresora no disponible (modo consola)",
                        SUCCESS if ok else WARNING)
        except Exception as ex:
            _show_snack(f"Error: {ex}", ERROR)

    # ─────────────────────────────────────────────────────────────────────────
    # PESTAÑA 2 – Administración de Cajas Registradoras
    # ─────────────────────────────────────────────────────────────────────────

    registers_data: list = []
    registers_list  = ft.ListView(expand=True, spacing=8, padding=8)
    reg_status_text = ft.Text("", color=ft.colors.WHITE54, size=12)

    def load_registers(e=None):
        nonlocal registers_data
        try:
            registers_data = api.get_all_registers()
            _render_registers()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def _render_registers():
        registers_list.controls.clear()

        if not registers_data:
            registers_list.controls.append(ft.Container(
                alignment=ft.alignment.center, padding=40,
                content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Icon(ft.icons.POINT_OF_SALE_OUTLINED, size=56, color=ft.colors.WHITE24),
                    ft.Text("No hay cajas registradoras", color=ft.colors.WHITE54, size=15),
                    ft.Text("Crea la primera caja para empezar a operar.",
                            color=ft.colors.WHITE38, size=12),
                ]),
            ))
            reg_status_text.value = "0 cajas"
            page.update()
            return

        for reg in registers_data:
            is_active = reg.get("is_active", True)

            def make_edit(r):   return lambda _: open_register_dialog(r)
            def make_toggle(r): return lambda _: toggle_register(r)
            def make_delete(r): return lambda _: delete_register(r)

            # Verificar si la caja tiene sesión abierta (no se puede eliminar)
            badge = ft.Container(
                content=ft.Text("Activa" if is_active else "Inactiva",
                                size=10, color=ft.colors.WHITE),
                bgcolor=SUCCESS + "55" if is_active else BG_SURFACE,
                border_radius=4, padding=ft.padding.symmetric(2, 8),
            )

            registers_list.controls.append(ft.Container(
                bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, (SUCCESS if is_active else ft.colors.WHITE12) + ("44" if is_active else "")),
                padding=ft.padding.symmetric(horizontal=16, vertical=14),
                content=ft.Row([
                    # Ícono de estado
                    ft.Container(
                        width=44, height=44, border_radius=22,
                        bgcolor=(PRIMARY + "33") if is_active else BG_SURFACE,
                        border=ft.border.all(2, PRIMARY if is_active else ft.colors.WHITE24),
                        alignment=ft.alignment.center,
                        content=ft.Icon(
                            ft.icons.POINT_OF_SALE if is_active else ft.icons.MONEY_OFF,
                            color=PRIMARY if is_active else ft.colors.WHITE38,
                            size=22,
                        ),
                    ),
                    # Info
                    ft.Column(expand=True, spacing=4, controls=[
                        ft.Row([
                            ft.Text(reg.get("name", ""), color=ft.colors.WHITE, size=15,
                                    weight=ft.FontWeight.W_600),
                            badge,
                            ft.Text(f"ID: {reg.get('id','')}", color=ft.colors.WHITE38, size=11),
                        ], spacing=8),
                        ft.Row([
                            ft.Icon(ft.icons.LOCATION_ON, size=13, color=ft.colors.WHITE38),
                            ft.Text(reg.get("location") or "Sin ubicación",
                                    size=12, color=ft.colors.WHITE54),
                        ], spacing=4) if reg.get("location") else ft.Container(),
                        ft.Row([
                            ft.Icon(ft.icons.PRINT, size=13, color=ft.colors.WHITE38),
                            ft.Text(f"Impresora: {reg.get('printer_name') or 'No configurada'}",
                                    size=12, color=ft.colors.WHITE54),
                        ], spacing=4),
                    ]),
                    # Acciones
                    ft.Row(spacing=4, controls=[
                        ft.IconButton(ft.icons.EDIT_OUTLINED, icon_color=PRIMARY_LT,
                                      icon_size=20, on_click=make_edit(reg), tooltip="Editar"),
                        ft.IconButton(
                            ft.icons.TOGGLE_ON if is_active else ft.icons.TOGGLE_OFF,
                            icon_color=SUCCESS if is_active else ERROR,
                            icon_size=22, tooltip="Activar / Desactivar",
                            on_click=make_toggle(reg),
                        ),
                        ft.IconButton(
                            ft.icons.DELETE_FOREVER,
                            icon_color=ft.colors.RED_700,
                            icon_size=20, tooltip="Eliminar caja",
                            on_click=make_delete(reg),
                        ),
                    ]),
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        reg_status_text.value = (
            f"{sum(1 for r in registers_data if r.get('is_active'))} activa(s) · "
            f"{sum(1 for r in registers_data if not r.get('is_active'))} inactiva(s)"
        )
        page.update()

    def open_register_dialog(reg: dict = None):
        is_edit = reg is not None

        f_name     = ft.TextField(
            label="Nombre de la caja *",
            hint_text="Ej: Caja Principal, Caja 1, Caja Express...",
            value=reg.get("name", "") if is_edit else "",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
            autofocus=True,
        )
        f_location = ft.TextField(
            label="Ubicación / Descripción",
            hint_text="Ej: Área de ventas, Mostrador principal...",
            value=reg.get("location", "") if is_edit else "",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
        )
        f_printer  = ft.TextField(
            label="Nombre de impresora (opcional)",
            hint_text="Ej: TM-T20III, POS-80, Térmica-Caja1...",
            value=reg.get("printer_name", "") if is_edit else "",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
        )

        # Configuración de impresora específica por caja
        printer_note = ft.Container(
            bgcolor=PRIMARY + "1A", border_radius=8,
            padding=ft.padding.all(10),
            content=ft.Row([
                ft.Icon(ft.icons.INFO_OUTLINE, color=PRIMARY_LT, size=16),
                ft.Text(
                    "La impresora global se configura en 'Impresora y Cajón'.\n"
                    "El nombre aquí es solo para identificar qué impresora\n"
                    "está físicamente conectada a esta caja.",
                    size=11, color=ft.colors.WHITE54,
                ),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
        )

        err_text = ft.Text("", color=ERROR, size=12)

        def save(e):
            err_text.value = ""
            if not f_name.value.strip():
                err_text.value = "El nombre de la caja es obligatorio"
                page.update()
                return
            try:
                payload = {
                    "name":         f_name.value.strip(),
                    "location":     f_location.value.strip() or "",
                    "printer_name": f_printer.value.strip() or None,
                }
                if is_edit:
                    api.update_register(reg["id"], payload)
                    _show_snack(f"✅ Caja '{payload['name']}' actualizada")
                else:
                    api.create_register(payload)
                    _show_snack(f"✅ Caja '{payload['name']}' creada exitosamente")
                dlg.open = False
                page.update()
                load_registers()
            except APIError as ex:
                err_text.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.POINT_OF_SALE, color=PRIMARY),
                ft.Text("Editar Caja" if is_edit else "Nueva Caja Registradora",
                        weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=420,
                content=ft.Column(spacing=14, controls=[
                    f_name,
                    f_location,
                    f_printer,
                    printer_note,
                    err_text,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton(
                    "Guardar", icon=ft.icons.SAVE, on_click=save,
                    style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                ),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def toggle_register(reg: dict):
        """Activa o desactiva una caja (soft delete / restore)."""
        new_state = not reg.get("is_active", True)
        action    = "activar" if new_state else "desactivar"

        def confirm(_):
            try:
                api.update_register(reg["id"], {"is_active": new_state})
                _show_snack(
                    f"✅ Caja '{reg.get('name','')}' {'activada' if new_state else 'desactivada'}"
                )
                load_registers()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.dialog.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"{'Activar' if new_state else 'Desactivar'} caja"),
            content=ft.Column(spacing=8, controls=[
                ft.Text(f"¿Deseas {action} la caja «{reg.get('name', '')}»?",
                        color=ft.colors.WHITE70),
                ft.Text(
                    "Las sesiones activas no se verán afectadas." if not new_state else
                    "La caja volverá a estar disponible para apertura de sesiones.",
                    color=ft.colors.WHITE54, size=12,
                ),
            ]),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(page.dialog, "open", False) or page.update()),
                ft.ElevatedButton(
                    "Confirmar", on_click=confirm,
                    style=ft.ButtonStyle(
                        bgcolor=SUCCESS if new_state else ERROR,
                        color=ft.colors.WHITE,
                    ),
                ),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def delete_register(reg: dict):
        name = reg.get("name", "")

        def confirm(_):
            try:
                api.delete_register(reg["id"])
                _show_snack(f"🗑  Caja '{name}' eliminada permanentemente")
                load_registers()
                page.dialog.open = False
                page.update()
            except APIError as ex:
                page.dialog.open = False
                page.update()
                if ex.status_code == 409:
                    _open_fallback_dialog(reg)
                else:
                    _show_snack(str(ex), ERROR)

        def _open_fallback_dialog(r: dict):
            def deactivate(_):
                try:
                    api.update_register(r["id"], {"is_active": False})
                    _show_snack(f"Caja '{r.get('name','')}' desactivada")
                    load_registers()
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
                                f"'{r.get('name','')}' tiene historial de sesiones de caja. "
                                "Eliminarla rompería esos registros.",
                                size=13, color=ft.colors.WHITE70,
                            ),
                        ),
                        ft.Text(
                            "¿Deseas desactivarla en su lugar?\n"
                            "No aparecerá en la apertura de turnos pero el historial se conserva.",
                            size=13, color=ft.colors.WHITE70,
                        ),
                    ]),
                ),
                actions=[
                    ft.TextButton("Cancelar",
                                  on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                    ft.ElevatedButton(
                        "Desactivar caja", icon=ft.icons.TOGGLE_OFF,
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
                ft.Text("Eliminar caja", weight=ft.FontWeight.BOLD, color=ERROR),
            ], spacing=8),
            content=ft.Container(
                width=400,
                content=ft.Column(spacing=12, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8,
                        padding=ft.padding.all(12),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.POINT_OF_SALE, color=ft.colors.WHITE60, size=16),
                                ft.Text(name, size=14, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=6),
                            ft.Text(f"ID: {reg.get('id','—')}  •  {reg.get('location','Sin ubicación')}",
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
                                "• La caja desaparece del sistema permanentemente\n"
                                "• Si tiene historial de sesiones, se sugerirá desactivar en su lugar\n"
                                "• Las cajas con sesión abierta no se pueden eliminar\n"
                                "• Esta acción no se puede deshacer",
                                size=12, color=ft.colors.WHITE54,
                            ),
                        ]),
                    ),
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
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

    # ── Panel de estadísticas de cajas ────────────────────────────────────────

    def _stats_panel():
        total   = len(registers_data)
        activas = sum(1 for r in registers_data if r.get("is_active"))
        return ft.Row(spacing=10, controls=[
            ft.Container(
                expand=True, bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, PRIMARY + "44"), padding=16,
                content=ft.Column(spacing=4, controls=[
                    ft.Row([ft.Icon(ft.icons.POINT_OF_SALE, color=PRIMARY, size=18),
                            ft.Text("Total de cajas", color=ft.colors.WHITE60, size=12)], spacing=6),
                    ft.Text(str(total), size=28, color=PRIMARY_LT, weight=ft.FontWeight.BOLD),
                ]),
            ),
            ft.Container(
                expand=True, bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, SUCCESS + "44"), padding=16,
                content=ft.Column(spacing=4, controls=[
                    ft.Row([ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE, color=SUCCESS, size=18),
                            ft.Text("Cajas activas", color=ft.colors.WHITE60, size=12)], spacing=6),
                    ft.Text(str(activas), size=28, color=SUCCESS, weight=ft.FontWeight.BOLD),
                ]),
            ),
            ft.Container(
                expand=True, bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, WARNING + "44"), padding=16,
                content=ft.Column(spacing=4, controls=[
                    ft.Row([ft.Icon(ft.icons.PAUSE_CIRCLE_OUTLINE, color=WARNING, size=18),
                            ft.Text("Cajas inactivas", color=ft.colors.WHITE60, size=12)], spacing=6),
                    ft.Text(str(total - activas), size=28, color=WARNING, weight=ft.FontWeight.BOLD),
                ]),
            ),
        ])

    stats_container = ft.Container()   # se rellena después de cargar datos

    def refresh_registers(e=None):
        load_registers()
        stats_container.content = _stats_panel()
        page.update()

    # ─────────────────────────────────────────────────────────────────────────
    # Carga inicial
    # ─────────────────────────────────────────────────────────────────────────
    load_config()
    load_registers()
    stats_container.content = _stats_panel()

    # ─────────────────────────────────────────────────────────────────────────
    # Layout con Tabs
    # ─────────────────────────────────────────────────────────────────────────

    # Encabezado común
    header = ft.Container(
        bgcolor=BG_CARD,
        padding=ft.padding.symmetric(horizontal=20, vertical=14),
        content=ft.Row([
            ft.Icon(ft.icons.SETTINGS, color=PRIMARY, size=26),
            ft.Text("Configuración del Sistema", size=20, color=ft.colors.WHITE,
                    weight=ft.FontWeight.BOLD, expand=True),
        ], spacing=12),
    )

    # ── Tab 1: Configuración general ──────────────────────────────────────────
    tab_config = ft.Tab(
        text="Configuración",
        icon=ft.icons.TUNE,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=16, vertical=8),
                    content=ft.Row([
                        unsaved_badge,
                        ft.Container(expand=True),
                        ft.OutlinedButton(
                            "Probar impresora", icon=ft.icons.PRINT,
                            on_click=test_printer,
                            style=ft.ButtonStyle(color=WARNING, side=ft.BorderSide(1, WARNING)),
                        ),
                        ft.OutlinedButton(
                            "Restablecer", icon=ft.icons.RESTORE,
                            on_click=reset_defaults,
                            style=ft.ButtonStyle(color=ERROR, side=ft.BorderSide(1, ERROR)),
                        ),
                        ft.ElevatedButton(
                            "Guardar cambios", icon=ft.icons.SAVE,
                            on_click=save_all,
                            style=ft.ButtonStyle(bgcolor=SUCCESS, color=ft.colors.WHITE),
                        ),
                    ], spacing=10),
                ),
                ft.Container(
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=16, vertical=4),
                    content=ft.ListView(
                        expand=True, spacing=8,
                        controls=[
                            ft.Text(
                                "Los cambios se aplican inmediatamente tras guardar. "
                                "Algunos ajustes requieren reiniciar la aplicación.",
                                color=ft.colors.WHITE38, size=12,
                            ),
                            accordion,
                        ],
                    ),
                ),
            ],
        ),
    )

    # ── Tab 2: Cajas registradoras ────────────────────────────────────────────
    tab_registers = ft.Tab(
        text="Cajas Registradoras",
        icon=ft.icons.POINT_OF_SALE,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                # Barra de acciones
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                    content=ft.Row([
                        ft.Text("Administración de Cajas", size=16, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, expand=True),
                        reg_status_text,
                        ft.IconButton(
                            ft.icons.REFRESH, icon_color=PRIMARY,
                            on_click=refresh_registers, tooltip="Actualizar",
                        ),
                        ft.ElevatedButton(
                            "Nueva caja", icon=ft.icons.ADD,
                            on_click=lambda _: open_register_dialog(),
                            style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                        ),
                    ], spacing=10),
                ),
                # Estadísticas
                ft.Container(
                    padding=ft.padding.only(left=16, right=16, bottom=10),
                    content=stats_container,
                ),
                # Nota informativa
                ft.Container(
                    margin=ft.margin.symmetric(horizontal=16),
                    bgcolor=BG_SURFACE, border_radius=8,
                    padding=ft.padding.all(10),
                    content=ft.Row([
                        ft.Icon(ft.icons.INFO_OUTLINE, color=PRIMARY_LT, size=16),
                        ft.Text(
                            "Cada caja puede tener su propia impresora. Las cajas inactivas no "
                            "aparecen en la pantalla de apertura de turno. No es posible eliminar "
                            "permanentemente una caja con historial de ventas.",
                            size=12, color=ft.colors.WHITE54, expand=True,
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                ),
                ft.Container(height=8),
                # Lista de cajas
                ft.Container(
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=16),
                    content=registers_list,
                ),
            ],
        ),
    )


    # ── Tab 3: Atajos de Teclado ──────────────────────────────────────────────

    HOTKEY_GROUPS = [
        ("🛒 Punto de Venta", [
            ("hotkey.pos.cobrar",              "Ir a cobrar"),
            ("hotkey.pos.refresh",             "Actualizar catálogo"),
            ("hotkey.pos.clear_search",        "Limpiar búsqueda"),
        ]),
        ("💳 Pantalla de Cobro", [
            ("hotkey.payment.confirm",         "Confirmar venta"),
            ("hotkey.payment.back",            "Volver al POS"),
            ("hotkey.payment.method_cash",     "Método: Efectivo"),
            ("hotkey.payment.method_card",     "Método: Tarjeta"),
            ("hotkey.payment.method_transfer", "Método: Transferencia"),
            ("hotkey.payment.method_mixed",    "Método: Mixto"),
            ("hotkey.payment.exact",           "Monto exacto"),
            ("hotkey.payment.backspace",       "Borrar último dígito"),
            ("hotkey.payment.clear",           "Borrar monto completo"),
        ]),
        ("✅ Pantalla de Éxito", [
            ("hotkey.success.new_sale",        "Nueva venta"),
            ("hotkey.success.print",           "Reimprimir ticket"),
        ]),
    ]

    # Valores por defecto de cada hotkey
    HOTKEY_DEFAULTS = {
        "hotkey.pos.cobrar":              "F12",
        "hotkey.pos.refresh":             "F5",
        "hotkey.pos.clear_search":        "Escape",
        "hotkey.payment.confirm":         "F12",
        "hotkey.payment.back":            "Escape",
        "hotkey.payment.method_cash":     "F1",
        "hotkey.payment.method_card":     "F2",
        "hotkey.payment.method_transfer": "F3",
        "hotkey.payment.method_mixed":    "F4",
        "hotkey.payment.exact":           "F9",
        "hotkey.payment.backspace":       "Backspace",
        "hotkey.payment.clear":           "Delete",
        "hotkey.success.new_sale":        "Enter",
        "hotkey.success.print":           "P",
    }

    # Nombres amigables para teclas
    KEY_LABELS = {
        "Escape":"Esc", "Enter":"Enter", "Numpad Enter":"⌨ Enter",
        "Backspace":"⌫ Bksp", "Delete":"Del", "Tab":"Tab", "Space":"Espacio",
        **{f"F{i}": f"F{i}" for i in range(1, 13)},
        **{f"Numpad {i}": f"Num {i}" for i in range(10)},
        "Numpad Decimal":"Num .", "Numpad Enter":"Num Enter",
    }
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        KEY_LABELS[c] = c
    for c in "abcdefghijklmnopqrstuvwxyz":
        KEY_LABELS[c] = c.upper()

    def _key_label(key: str) -> str:
        return KEY_LABELS.get(key, key)

    hotkeys_list = ft.ListView(expand=True, spacing=12, padding=ft.padding.all(8))

    def load_hotkeys():
        try:
            # Asegurar que los hotkeys por defecto existen en la BD
            # (necesario si el servidor se actualizó pero no se reinicializó la config)
            raw = api.get_configs(category="hotkeys")
            existing_keys = {c["key"] for c in raw}
            missing = [
                {"key": k, "value": v, "description": None, "category": "hotkeys"}
                for k, v in HOTKEY_DEFAULTS.items()
                if k not in existing_keys
            ]
            if missing:
                api.bulk_update_config(missing)
                raw = api.get_configs(category="hotkeys")   # recargar tras insertar
            hk_map = {c["key"]: c["value"] for c in raw}
            _render_hotkeys(hk_map)
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def _render_hotkeys(hk_map: dict):
        hotkeys_list.controls.clear()
        for group_title, hotkeys in HOTKEY_GROUPS:
            hotkeys_list.controls.append(ft.Container(
                padding=ft.padding.only(top=8, bottom=4),
                content=ft.Text(group_title, size=14, color=ft.colors.WHITE70,
                                weight=ft.FontWeight.BOLD),
            ))
            for hk_key, hk_label in hotkeys:
                current = hk_map.get(hk_key, HOTKEY_DEFAULTS.get(hk_key, "—"))
                default = HOTKEY_DEFAULTS.get(hk_key, "—")
                is_custom = current != default

                def make_capture(key, label, cur):
                    return lambda _: open_key_capture(key, label, cur)

                def make_reset(key, default_val):
                    def fn(_):
                        try:
                            api.update_config(key, default_val)
                            app_state.setdefault("config", {})[key] = default_val
                            _show_snack(f"✅ '{_key_label(default_val)}' restaurado")
                            load_hotkeys()
                        except APIError as ex:
                            _show_snack(str(ex), ERROR)
                    return fn

                hotkeys_list.controls.append(ft.Container(
                    bgcolor=BG_CARD, border_radius=8,
                    border=ft.border.all(1, PRIMARY + "33" if is_custom else ft.colors.WHITE12),
                    padding=ft.padding.symmetric(horizontal=14, vertical=10),
                    content=ft.Row([
                        ft.Text(hk_label, color=ft.colors.WHITE, size=13, expand=True),
                        # Badge de tecla actual
                        ft.Container(
                            bgcolor=(PRIMARY + "44") if is_custom else BG_SURFACE,
                            border_radius=6,
                            border=ft.border.all(1, PRIMARY_LT if is_custom else ft.colors.WHITE24),
                            padding=ft.padding.symmetric(4, 12),
                            content=ft.Text(
                                _key_label(current), size=13, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER,
                            ),
                            width=110,
                        ),
                        # Indicador si es personalizado
                        ft.Container(
                            visible=is_custom,
                            bgcolor=PRIMARY + "22",
                            border_radius=4,
                            padding=ft.padding.symmetric(2, 6),
                            content=ft.Text("personalizado", size=9, color=PRIMARY_LT),
                        ),
                        ft.ElevatedButton(
                            "Cambiar", icon=ft.icons.KEYBOARD,
                            height=34,
                            on_click=make_capture(hk_key, hk_label, current),
                            style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=ft.colors.WHITE),
                        ),
                        ft.IconButton(
                            ft.icons.RESTORE,
                            icon_color=ft.colors.WHITE38 if not is_custom else WARNING,
                            icon_size=18,
                            tooltip="Restaurar valor por defecto",
                            disabled=not is_custom,
                            on_click=make_reset(hk_key, default),
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ))
        page.update()

    def open_key_capture(hk_key: str, hk_label: str, current_val: str):
        """Diálogo de captura de tecla en tiempo real."""
        captured = {"key": None}
        original_handler = page.on_keyboard_event

        status  = ft.Text("Presiona la tecla que quieres asignar…",
                          size=15, color=ft.colors.WHITE70,
                          text_align=ft.TextAlign.CENTER)
        key_badge = ft.Container(
            bgcolor=BG_SURFACE, border_radius=10,
            border=ft.border.all(2, ft.colors.WHITE24),
            padding=ft.padding.symmetric(16, 32),
            alignment=ft.alignment.center,
            content=ft.Text("—", size=28, weight=ft.FontWeight.BOLD,
                            color=ft.colors.WHITE54, text_align=ft.TextAlign.CENTER),
        )
        save_btn = ft.ElevatedButton(
            "Guardar", icon=ft.icons.SAVE,
            disabled=True,
            style=ft.ButtonStyle(bgcolor=SUCCESS, color=ft.colors.WHITE),
        )

        def on_capture(e: ft.KeyboardEvent):
            k = e.key
            # Ignorar modificadores solos
            if k in ("Shift", "Control", "Alt", "Meta", "CapsLock",
                     "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
                     "AltLeft", "AltRight"):
                return
            captured["key"] = k
            key_badge.content = ft.Text(
                _key_label(k), size=28, weight=ft.FontWeight.BOLD,
                color=PRIMARY_LT, text_align=ft.TextAlign.CENTER,
            )
            key_badge.border = ft.border.all(2, PRIMARY)
            key_badge.bgcolor = PRIMARY + "22"
            status.value = "Tecla detectada — confirma o presiona otra"
            save_btn.disabled = False
            page.update()

        page.on_keyboard_event = on_capture

        def save(_):
            if not captured["key"]:
                return
            try:
                api.update_config(hk_key, captured["key"])
                app_state.setdefault("config", {})[hk_key] = captured["key"]
                _show_snack(
                    f"✅ '{hk_label}' → {_key_label(captured['key'])}"
                )
                load_hotkeys()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.on_keyboard_event = original_handler
            dlg.open = False
            page.update()

        def cancel(_):
            page.on_keyboard_event = original_handler
            dlg.open = False
            page.update()

        save_btn.on_click = save

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.KEYBOARD, color=PRIMARY),
                ft.Text(f"Asignar atajo: {hk_label}", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=340, height=200,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=14,
                    controls=[
                        ft.Text(
                            f"Actual: {_key_label(current_val)}",
                            size=12, color=ft.colors.WHITE38,
                        ),
                        key_badge,
                        status,
                    ],
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cancel),
                save_btn,
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def reset_all_hotkeys(e=None):
        """Restaura todos los atajos a sus valores por defecto."""
        def confirm(_):
            try:
                configs = [
                    {"key": k, "value": v, "description": None, "category": "hotkeys"}
                    for k, v in HOTKEY_DEFAULTS.items()
                ]
                api.bulk_update_config(configs)
                for k, v in HOTKEY_DEFAULTS.items():
                    app_state.setdefault("config", {})[k] = v
                _show_snack("✅ Todos los atajos restaurados a sus valores por defecto")
                load_hotkeys()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.dialog.open = False
            page.update()
        dlg = ft.AlertDialog(
            title=ft.Text("Restaurar atajos"),
            content=ft.Text("¿Restaurar todos los atajos de teclado a sus valores por defecto?"),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                ft.ElevatedButton("Restaurar todo", on_click=confirm,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    load_hotkeys()

    tab_hotkeys = ft.Tab(
        text="Atajos de Teclado",
        icon=ft.icons.KEYBOARD,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                    content=ft.Row([
                        ft.Text("Atajos de Teclado", size=16, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, expand=True),
                        ft.TextButton(
                            "Restaurar todos",
                            icon=ft.icons.RESTORE,
                            on_click=reset_all_hotkeys,
                            style=ft.ButtonStyle(color=WARNING),
                        ),
                        ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                      on_click=lambda _: load_hotkeys(),
                                      tooltip="Recargar"),
                    ]),
                ),
                ft.Container(
                    bgcolor=BG_SURFACE, border_radius=8,
                    margin=ft.margin.symmetric(horizontal=16),
                    padding=ft.padding.all(10),
                    content=ft.Row([
                        ft.Icon(ft.icons.INFO_OUTLINE, color=PRIMARY_LT, size=16),
                        ft.Text(
                            "Haz clic en 'Cambiar' y presiona la tecla que quieres asignar. "
                            "Los cambios se aplican inmediatamente al Punto de Venta.",
                            size=12, color=ft.colors.WHITE54, expand=True,
                        ),
                    ], spacing=8),
                ),
                ft.Container(height=6),
                ft.Container(
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=16),
                    content=hotkeys_list,
                ),
            ],
        ),
    )


    # ── Tab 4: Administración de base de datos ────────────────────────────────

    db_stats_data: dict = {}
    stats_row     = ft.Row(spacing=10)
    last_op_text  = ft.Text("", color=ft.colors.WHITE54, size=12, italic=True)

    STAT_META = {
        "sales":          ("Ventas",                  ft.icons.RECEIPT_LONG,        PRIMARY_LT),
        "sale_items":     ("Líneas de venta",          ft.icons.LIST_ALT,            PRIMARY_LT),
        "sessions":       ("Sesiones de caja",         ft.icons.POINT_OF_SALE,       SUCCESS),
        "cash_movements": ("Movimientos de caja",      ft.icons.SWAP_VERT,           SUCCESS),
        "inv_movements":  ("Movim. de inventario",     ft.icons.INVENTORY,           WARNING),
    }

    def load_db_stats(e=None):
        nonlocal db_stats_data
        try:
            db_stats_data = api.get_db_stats()
            _render_stats()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def _render_stats():
        stats_row.controls.clear()
        for key, (label, icon, color) in STAT_META.items():
            count = db_stats_data.get(key, 0)
            stats_row.controls.append(ft.Container(
                expand=True, bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, color + "33"),
                padding=ft.padding.all(12),
                content=ft.Column(spacing=4, controls=[
                    ft.Row([ft.Icon(icon, color=color, size=16),
                            ft.Text(label, color=ft.colors.WHITE60, size=11)], spacing=6),
                    ft.Text(f"{count:,}", size=22, color=color,
                            weight=ft.FontWeight.BOLD),
                ]),
            ))
        page.update()

    def _confirm_action(title: str, lines: list, action_label: str,
                        action_color: str, on_confirm, require_word: str = "BORRAR"):
        """Diálogo de confirmación de alta seguridad que requiere escribir una palabra."""
        f_word = ft.TextField(
            label=f'Escribe "{require_word}" para confirmar',
            color=ft.colors.WHITE, bgcolor=BG_SURFACE,
            border_color=ERROR, autofocus=True,
        )
        err_text = ft.Text("", color=ERROR, size=12)
        confirm_btn = ft.ElevatedButton(
            action_label, icon=ft.icons.DELETE_FOREVER,
            style=ft.ButtonStyle(bgcolor=action_color, color=ft.colors.WHITE),
        )

        def do_action(e):
            if f_word.value.strip().upper() != require_word:
                err_text.value = f'Debes escribir exactamente "{require_word}"'
                page.update()
                return
            confirm_btn.disabled = True
            loading = ft.ProgressRing(width=20, height=20, color=action_color)
            dlg.actions[1] = loading
            page.update()
            try:
                on_confirm()
                dlg.open = False
                page.update()
                load_db_stats()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
                dlg.open = False
                page.update()

        confirm_btn.on_click = do_action

        warning_items = [
            ft.Row([ft.Icon(ft.icons.FIBER_MANUAL_RECORD, size=8, color=ERROR),
                    ft.Text(line, size=12, color=ft.colors.WHITE70, expand=True)],
                   spacing=6)
            for line in lines
        ]

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=ERROR, size=22),
                ft.Text(title, weight=ft.FontWeight.BOLD, color=ERROR),
            ], spacing=8),
            content=ft.Container(
                width=440,
                content=ft.Column(spacing=12, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8,
                        padding=ft.padding.all(12),
                        content=ft.Column(spacing=6, controls=warning_items),
                    ),
                    f_word,
                    err_text,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                confirm_btn,
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # Acciones destructivas
    def action_delete_sales():
        def run():
            res = api.delete_all_sales()
            last_op_text.value = f"✅ {res.get('message','Ventas eliminadas')}"
            _show_snack(last_op_text.value)
        _confirm_action(
            title="Eliminar todas las ventas",
            lines=[
                "Se eliminarán TODAS las ventas y sus líneas de detalle",
                "El folio volverá a 0001 automáticamente",
                "Las sesiones de caja y el inventario actual se conservan",
                "Esta acción NO se puede deshacer",
            ],
            action_label="Sí, eliminar todas las ventas",
            action_color=ERROR,
            on_confirm=run,
        )

    def action_delete_sessions():
        def run():
            res = api.delete_all_sessions()
            last_op_text.value = f"✅ {res.get('message','Sesiones eliminadas')}"
            _show_snack(last_op_text.value)
        _confirm_action(
            title="Eliminar todas las sesiones de caja",
            lines=[
                "Se eliminarán TODAS las sesiones de caja y sus movimientos",
                "Elimina primero las ventas si éstas referencian las sesiones",
                "Esta acción NO se puede deshacer",
            ],
            action_label="Sí, eliminar todas las sesiones",
            action_color=ERROR,
            on_confirm=run,
        )

    def action_delete_inv_movements():
        def run():
            res = api.delete_inventory_movements()
            last_op_text.value = f"✅ {res.get('message','Movimientos eliminados')}"
            _show_snack(last_op_text.value)
        _confirm_action(
            title="Limpiar historial de inventario",
            lines=[
                "Se eliminará todo el historial de entradas y salidas de inventario",
                "El stock ACTUAL de cada producto NO cambia",
                "Esta acción NO se puede deshacer",
            ],
            action_label="Sí, limpiar historial",
            action_color=WARNING,
            on_confirm=run,
            require_word="LIMPIAR",
        )

    def action_force_migrate():
        """Aplica migraciones de schema pendientes sin reiniciar el backend."""
        def run():
            try:
                result = api.force_migrate()
                results = result.get("results", [])
                msgs = []
                for r in results:
                    if r["status"] == "applied":
                        msgs.append(f"✅ {r['migration']} aplicada")
                    elif r["status"] == "already_exists":
                        msgs.append(f"ℹ️  {r['migration']} ya existía")
                    else:
                        msgs.append(f"❌ {r['migration']}: {r.get('detail','error')}")
                msg = "  |  ".join(msgs) if msgs else "Sin migraciones pendientes"
                last_op_text.value = msg
                _show_snack(msg if "✅" in msg or "ℹ️" in msg else msg, 
                            SUCCESS if "✅" in msg else WARNING)
                load_db_stats()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
        _confirm_action(
            title="Forzar migraciones de base de datos",
            lines=[
                "Aplica columnas/tablas nuevas que el servidor no pudo añadir al arrancar",
                "No elimina ni modifica datos existentes",
                "Necesario después de actualizar el código sin reiniciar el backend",
            ],
            action_label="Aplicar migraciones",
            action_color=PRIMARY,
            on_confirm=run,
            require_word="MIGRAR",
        )

    def action_full_reset():
        def run():
            res = api.full_db_reset()
            last_op_text.value = f"✅ {res.get('message','Reset completo')}"
            _show_snack(last_op_text.value)
        _confirm_action(
            title="⚠  RESET COMPLETO DE OPERACIONES",
            lines=[
                "Se eliminarán TODAS las ventas, sesiones y movimientos",
                "Usuarios, productos, categorías y configuración se conservan",
                "El inventario ACTUAL no cambia",
                "El folio volverá a 0001",
                "ACCIÓN COMPLETAMENTE IRREVERSIBLE",
            ],
            action_label="Sí, ejecutar reset completo",
            action_color=ERROR,
            on_confirm=run,
            require_word="RESET",
        )

    load_db_stats()

    def _danger_btn(label, icon, on_click, color=ERROR, desc=""):
        return ft.Container(
            bgcolor=BG_CARD, border_radius=10,
            border=ft.border.all(1, color + "44"),
            padding=ft.padding.all(16),
            content=ft.Row([
                ft.Icon(icon, color=color, size=22),
                ft.Column(expand=True, spacing=2, controls=[
                    ft.Text(label, color=ft.colors.WHITE, size=14,
                            weight=ft.FontWeight.W_600),
                    ft.Text(desc, color=ft.colors.WHITE54, size=11),
                ]),
                ft.ElevatedButton(
                    "Ejecutar", on_click=on_click,
                    style=ft.ButtonStyle(
                        bgcolor=color + "22",
                        color=color,
                        side=ft.BorderSide(1, color),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    tab_database = ft.Tab(
        text="Base de Datos",
        icon=ft.icons.STORAGE,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                # Barra de acciones
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                    content=ft.Row([
                        ft.Text("Administración de Base de Datos", size=16,
                                color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, expand=True),
                        last_op_text,
                        ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                      on_click=load_db_stats, tooltip="Actualizar estadísticas"),
                    ]),
                ),
                # Panel de estadísticas
                ft.Container(
                    padding=ft.padding.only(left=16, right=16, bottom=12),
                    content=stats_row,
                ),
                ft.Container(
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=16),
                    content=ft.ListView(
                        expand=True, spacing=10,
                        controls=[
                            # Info
                            ft.Container(
                                bgcolor=PRIMARY + "1A", border_radius=8,
                                padding=ft.padding.all(12),
                                content=ft.Row([
                                    ft.Icon(ft.icons.INFO_OUTLINE, color=PRIMARY_LT, size=16),
                                    ft.Text(
                                        "Las operaciones de esta sección son permanentes e "
                                        "irreversibles. Se requiere escribir una palabra de "
                                        "confirmación antes de cada acción.",
                                        size=12, color=ft.colors.WHITE60, expand=True,
                                    ),
                                ], spacing=8),
                            ),
                            # Zona de operaciones
                            ft.Text("⚡ Operaciones de Datos", size=13,
                                    color=ft.colors.WHITE70, weight=ft.FontWeight.BOLD),
                            _danger_btn(
                                "Aplicar migraciones pendientes",
                                ft.icons.SYSTEM_UPDATE_ALT,
                                on_click=lambda _: action_force_migrate(),
                                color=PRIMARY,
                                desc="Añade columnas/tablas nuevas sin reiniciar el backend. Escribe MIGRAR.",
                            ),
                            _danger_btn(
                                "Limpiar historial de inventario",
                                ft.icons.INVENTORY,
                                on_click=lambda _: action_delete_inv_movements(),
                                color=WARNING,
                                desc="Borra el historial de movimientos. El stock actual no cambia.",
                            ),
                            _danger_btn(
                                "Eliminar todas las sesiones de caja",
                                ft.icons.POINT_OF_SALE,
                                on_click=lambda _: action_delete_sessions(),
                                color=ERROR,
                                desc="Borra sesiones y movimientos de caja. Elimina las ventas primero.",
                            ),
                            _danger_btn(
                                "Eliminar todas las ventas",
                                ft.icons.RECEIPT_LONG,
                                on_click=lambda _: action_delete_sales(),
                                color=ERROR,
                                desc="Borra todas las ventas. El folio vuelve a 0001. Ideal para resetear.",
                            ),
                            ft.Divider(color=ft.colors.WHITE12),
                            ft.Text("💀 Zona de Peligro", size=13,
                                    color=ERROR, weight=ft.FontWeight.BOLD),
                            _danger_btn(
                                "RESET COMPLETO DE OPERACIONES",
                                ft.icons.RESTORE_FROM_TRASH,
                                on_click=lambda _: action_full_reset(),
                                color=ERROR,
                                desc="Borra ventas, sesiones y movimientos en una sola operación. Escribe RESET.",
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )

    return ft.Container(
        expand=True, bgcolor=BG_DARK,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                header,
                ft.Tabs(
                    expand=True,
                    selected_index=0,
                    indicator_color=PRIMARY,
                    label_color=PRIMARY_LT,
                    unselected_label_color=ft.colors.WHITE54,
                    tabs=[tab_config, tab_registers, tab_hotkeys, tab_database],
                ),
            ],
        ),
    )
