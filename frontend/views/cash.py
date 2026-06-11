"""
Vista de Caja – Apertura, cierre, movimientos y sesiones
"""
import flet as ft
from datetime import datetime, timezone
from views.pos import _fmt_dt   # reutilizar el helper de conversión UTC→local
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


def cash_view(page: ft.Page, app_state: dict):
    cfg      = app_state.get("config", {})
    currency = cfg.get("fiscal.currency_symbol", "$")
    is_mgr   = api.is_manager()

    active_sessions: list = []
    registers: list       = []
    history: list         = []

    # ─── Panel de sesión activa ───────────────────────────────────────────────

    session_panel   = ft.Column(expand=True, spacing=10)
    history_list    = ft.ListView(expand=True, spacing=8, padding=8)
    status_text     = ft.Text("", color=ft.colors.WHITE54, size=12)

    def _show_snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    def load_data(e=None):
        try:
            nonlocal active_sessions, registers, history
            all_sessions = api.get_active_sessions()

            def same_user(s: dict) -> bool:
                try:
                    my_id = (api.current_user or {}).get("id")
                    return int((s.get("cashier") or {}).get("id", -1)) == int(my_id)
                except (TypeError, ValueError):
                    return False

            if is_mgr:
                # Gerentes y administradores ven todas las cajas abiertas
                active_sessions = all_sessions
            else:
                # Cajeros solo ven las sesiones que ellos mismos abrieron
                active_sessions = [s for s in all_sessions if same_user(s)]

            registers = api.get_registers()
            if is_mgr:
                history = api.get_sessions()
            _render_sessions()
            _render_history()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    # ─── Render sesiones activas ──────────────────────────────────────────────

    def _render_sessions():
        session_panel.controls.clear()

        if not active_sessions:
            msg_title = ("No hay cajas abiertas" if is_mgr
                         else "No tienes una caja abierta")
            msg_sub   = ("Abre una sesión de caja para empezar a operar." if is_mgr
                         else "Abre tu sesión de caja para empezar a operar.")
            session_panel.controls.append(ft.Container(
                bgcolor=BG_CARD, border_radius=12,
                padding=40,
                alignment=ft.alignment.center,
                content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, controls=[
                    ft.Icon(ft.icons.POINT_OF_SALE_OUTLINED, size=64, color=ft.colors.WHITE24),
                    ft.Text(msg_title, size=18, color=ft.colors.WHITE54),
                    ft.Text(msg_sub, color=ft.colors.WHITE38, size=13),
                    ft.ElevatedButton(
                        "Abrir caja", icon=ft.icons.LOCK_OPEN,
                        on_click=lambda _: open_open_dialog(),
                        style=ft.ButtonStyle(bgcolor=SUCCESS, color=ft.colors.WHITE),
                    ),
                ]),
            ))
        else:
            for s in active_sessions:
                _add_session_card(s)
            # Solo gerentes/admins pueden abrir cajas adicionales
            if is_mgr:
                session_panel.controls.append(
                    ft.ElevatedButton(
                        "Abrir otra caja", icon=ft.icons.ADD_BOX,
                        on_click=lambda _: open_open_dialog(),
                        style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                    )
                )
        page.update()

    def _set_active_session(s: dict):
        """Asigna la sesión seleccionada como la activa para el Punto de Venta."""
        app_state["session_id"]   = s["id"]
        app_state["session_info"] = {
            "id":       s["id"],
            "register": s["register"]["name"],
            "cashier":  s["cashier"]["full_name"],
        }
        _render_sessions()   # refrescar tarjetas para actualizar indicador
        _show_snack(f"✅ Caja activa en POS: {s['register']['name']} "
                    f"(Cajero: {s['cashier']['full_name']})")

    def _add_session_card(s: dict):
        sid  = s["id"]
        reg  = s["register"]
        cash = s["cashier"]
        amt  = float(s.get("opening_amount", 0))
        opened = _fmt_dt(s.get("opened_at", ""))

        is_active_pos = (app_state.get("session_id") == sid)  # ¿es la caja activa en POS?

        def make_close(session_id):   return lambda _: open_close_dialog(session_id)
        def make_move(session_id):    return lambda _: open_movement_dialog(session_id)
        def make_summary(session_id): return lambda _: open_session_summary(session_id)
        def make_use_pos(sess):       return lambda _: _set_active_session(sess)

        # Indicador de caja activa en POS
        pos_badge = ft.Container(
            bgcolor=PRIMARY + "22", border_radius=6,
            padding=ft.padding.symmetric(3, 10),
            border=ft.border.all(1, PRIMARY + "88"),
            content=ft.Row([
                ft.Icon(ft.icons.POINT_OF_SALE, color=PRIMARY_LT, size=12),
                ft.Text("EN USO POS", color=PRIMARY_LT, size=11,
                        weight=ft.FontWeight.BOLD),
            ], spacing=4),
            visible=is_active_pos,
        )

        # Botón "Usar en POS" (solo gerentes, solo si no es ya la activa)
        use_pos_btn = ft.ElevatedButton(
            "Usar en POS", icon=ft.icons.POINT_OF_SALE,
            on_click=make_use_pos(s),
            visible=(is_mgr and not is_active_pos),
            style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
        )

        # Borde: verde normal, PRIMARY si es la caja activa en POS
        border_color = (PRIMARY + "CC") if is_active_pos else (SUCCESS + "88")

        session_panel.controls.append(ft.Container(
            bgcolor=BG_CARD,
            border_radius=12,
            border=ft.border.all(2, border_color),
            padding=20,
            content=ft.Column(spacing=10, controls=[
                ft.Row([
                    ft.Container(
                        bgcolor=SUCCESS + "22", border_radius=8,
                        padding=ft.padding.symmetric(6, 12),
                        content=ft.Row([
                            ft.Icon(ft.icons.CIRCLE, color=SUCCESS, size=10),
                            ft.Text("CAJA ABIERTA", color=SUCCESS, size=12,
                                    weight=ft.FontWeight.BOLD),
                        ], spacing=6),
                    ),
                    ft.Container(width=8),
                    pos_badge,
                    ft.Container(expand=True),
                    ft.Text(f"Sesión #{sid}", color=ft.colors.WHITE38, size=12),
                ]),
                ft.Row([
                    ft.Column(expand=1, spacing=4, controls=[
                        ft.Text("Caja", color=ft.colors.WHITE54, size=11),
                        ft.Text(reg.get("name",""), color=ft.colors.WHITE, size=16,
                                weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Column(expand=1, spacing=4, controls=[
                        ft.Text("Cajero", color=ft.colors.WHITE54, size=11),
                        ft.Text(cash.get("full_name",""), color=ft.colors.WHITE, size=14),
                    ]),
                    ft.Column(expand=1, spacing=4, controls=[
                        ft.Text("Fondo inicial", color=ft.colors.WHITE54, size=11),
                        ft.Text(f"{currency}{amt:.2f}", color=PRIMARY_LT, size=16,
                                weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Column(expand=1, spacing=4, controls=[
                        ft.Text("Apertura", color=ft.colors.WHITE54, size=11),
                        ft.Text(opened, color=ft.colors.WHITE70, size=13),
                    ]),
                ]),
                ft.Row(spacing=10, controls=[
                    ft.ElevatedButton(
                        "Ver resumen", icon=ft.icons.SUMMARIZE,
                        on_click=make_summary(sid),
                        style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=PRIMARY_LT,
                                             side=ft.BorderSide(1, PRIMARY)),
                    ),
                    ft.ElevatedButton(
                        "Registrar movimiento", icon=ft.icons.SWAP_VERT,
                        on_click=make_move(sid),
                        style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK),
                    ),
                    use_pos_btn,
                    ft.ElevatedButton(
                        "Cerrar caja", icon=ft.icons.LOCK,
                        on_click=make_close(sid),
                        style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE),
                    ),
                ]),
            ]),
        ))

    # ─── Diálogo: Abrir caja ──────────────────────────────────────────────────

    def open_open_dialog():
        # Si no hay cajas configuradas en la BD mostrar mensaje de ayuda
        if not registers:
            dlg_err = ft.AlertDialog(
                title=ft.Row([ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=WARNING),
                               ft.Text("Sin cajas configuradas", weight=ft.FontWeight.BOLD)],
                              spacing=8),
                content=ft.Column(spacing=10, controls=[
                    ft.Text(
                        "No hay cajas registradoras activas en el sistema.\n"
                        "El backend debería haberlas creado automáticamente al iniciar.\n\n"
                        "Verifica que el servidor esté corriendo correctamente y\n"
                        "recarga la vista con el botón de actualizar.",
                        color=ft.colors.WHITE70, size=13,
                    ),
                ]),
                actions=[
                    ft.ElevatedButton(
                        "Actualizar",
                        icon=ft.icons.REFRESH,
                        on_click=lambda _: [
                            setattr(dlg_err, "open", False),
                            load_data(),
                            page.update(),
                        ],
                        style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                    ),
                ],
            )
            page.dialog = dlg_err
            dlg_err.open = True
            page.update()
            return

        # Dropdown con on_change explícito para garantizar interactividad en Flet 0.21.x
        selected_reg = {"value": str(registers[0]["id"])}

        f_reg = ft.Dropdown(
            label="Seleccionar caja *",
            value=str(registers[0]["id"]),
            options=[ft.dropdown.Option(str(r["id"]), r["name"]) for r in registers],
            color=ft.colors.WHITE,
            bgcolor=BG_SURFACE,
            border_color=PRIMARY,
            focused_border_color=PRIMARY_LT,
            on_change=lambda e: selected_reg.update({"value": e.control.value}),
        )
        f_amount = ft.TextField(
            label="Fondo inicial en efectivo", value="0",
            prefix_text=currency, keyboard_type=ft.KeyboardType.NUMBER,
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
        )
        f_notes  = ft.TextField(
            label="Notas (opcional)",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
        )
        err_text = ft.Text("", color=ERROR, size=12)

        def save(e):
            reg_id = selected_reg.get("value") or f_reg.value
            if not reg_id:
                err_text.value = "Selecciona una caja"
                page.update()
                return
            try:
                api.open_session({
                    "register_id": int(reg_id),
                    "opening_amount": float(f_amount.value or 0),
                    "notes": f_notes.value or None,
                })
                # Reasignar la sesión activa del usuario actual
                my_id    = (api.current_user or {}).get("id")
                sessions = api.get_active_sessions()
                my_sessions = [s for s in sessions
                               if (s.get("cashier") or {}).get("id") == my_id]
                if my_sessions:
                    chosen = my_sessions[0]
                    app_state["session_id"]   = chosen["id"]
                    app_state["session_info"] = {
                        "id":       chosen["id"],
                        "register": chosen["register"]["name"],
                        "cashier":  chosen["cashier"]["full_name"],
                    }
                dlg.open = False
                page.update()
                load_data()
                _show_snack("✅ Caja abierta exitosamente")
            except APIError as ex:
                err_text.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.icons.LOCK_OPEN, color=SUCCESS),
                           ft.Text("Apertura de Caja", weight=ft.FontWeight.BOLD)], spacing=8),
            content=ft.Container(
                width=380,
                content=ft.Column(spacing=12, controls=[
                    ft.Text("Configura el turno de caja para comenzar a operar.",
                            color=ft.colors.WHITE70, size=13),
                    f_reg, f_amount, f_notes, err_text,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Abrir caja", icon=ft.icons.LOCK_OPEN, on_click=save,
                                  style=ft.ButtonStyle(bgcolor=SUCCESS, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ─── Helper: construir panel de resumen de sesión ─────────────────────────

    def _build_summary_panel(summary: dict, sess: dict) -> ft.Container:
        """Panel reutilizable con el resumen completo de una sesión."""
        expected      = float(summary.get("expected_in_register",
                              sess.get("expected_amount") or 0))
        revenue       = float(summary.get("total_revenue", 0))
        total_ret     = float(summary.get("total_returned", 0))
        cash_revenue  = float(summary.get("cash_revenue", 0))
        card_revenue  = float(summary.get("card_revenue", 0))
        transfer_rev  = float(summary.get("transfer_revenue", 0))
        mixed_revenue = float(summary.get("mixed_revenue", 0))
        cash_net      = float(summary.get("cash_net", 0))
        cash_in       = float(summary.get("cash_in", 0))
        cash_out      = float(summary.get("cash_out", 0))
        opening       = float(summary.get("opening_amount",
                              sess.get("opening_amount") or 0))
        total_s       = int(summary.get("total_sales", 0))

        def row(label, value, color=ft.colors.WHITE, size=12, bold=False):
            return ft.Row([
                ft.Text(label, color=ft.colors.WHITE54, size=size),
                ft.Text(value, color=color, size=size,
                        weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        items = [
            ft.Text("Resumen del turno", color=ft.colors.WHITE70, size=12,
                    weight=ft.FontWeight.BOLD),
            row("Total ventas:", str(total_s), ft.colors.WHITE, bold=True),
            row("Total ingresos:", f"{currency}{revenue:.2f}", ft.colors.WHITE, bold=True),
        ]
        if total_ret:
            items.append(row("  ↩ Devoluciones:", f"-{currency}{total_ret:.2f}", WARNING))
        items += [
            ft.Divider(color=ft.colors.WHITE12, height=6),
            ft.Text("Desglose por método de pago:", color=ft.colors.WHITE38, size=11),
        ]
        if cash_revenue:
            items.append(row(f"  💵 Efectivo:", f"{currency}{cash_revenue:.2f}", SUCCESS))
        if card_revenue:
            items.append(row(f"  💳 Tarjeta:", f"{currency}{card_revenue:.2f}", PRIMARY_LT))
        if transfer_rev:
            items.append(row(f"  🏦 Transferencia:", f"{currency}{transfer_rev:.2f}", PRIMARY_LT))
        if mixed_revenue:
            items.append(row(f"  🔀 Mixto (total):", f"{currency}{mixed_revenue:.2f}", ft.colors.WHITE70))
        items += [
            ft.Divider(color=ft.colors.WHITE12, height=6),
            ft.Text("Efectivo físico en caja:", color=ft.colors.WHITE38, size=11),
            row(f"  Fondo de apertura:", f"{currency}{opening:.2f}", ft.colors.WHITE54),
            row(f"  + Efectivo neto de ventas:", f"{currency}{cash_net:.2f}", SUCCESS),
        ]
        if cash_in:
            items.append(row(f"  + Entradas manuales:", f"{currency}{cash_in:.2f}", SUCCESS))
        if cash_out:
            items.append(row(f"  − Salidas manuales:", f"{currency}{cash_out:.2f}", WARNING))
        items += [
            ft.Divider(color=ft.colors.WHITE12),
            row("Esperado en caja:", f"{currency}{expected:.2f}", PRIMARY_LT, size=14, bold=True),
        ]
        return ft.Container(
            bgcolor=BG_SURFACE, border_radius=8, padding=14,
            content=ft.Column(spacing=6, controls=items),
        ), expected

    # ─── Diálogo: Ver resumen (sin cierre, sin cajón) ────────────────────────

    def open_session_summary(session_id: int):
        """Muestra el resumen de la sesión activa SIN cerrarla ni abrir el cajón."""
        try:
            sess    = api.get_session(session_id)
            summary = api.get_session_report(session_id)
        except APIError as ex:
            _show_snack(str(ex), ERROR); return

        summary_panel, _ = _build_summary_panel(summary, sess)
        reg  = sess.get("register", {})
        cash = sess.get("cashier", {})
        opened = _fmt_dt(sess.get("opened_at", ""))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.SUMMARIZE, color=PRIMARY),
                ft.Column(spacing=2, expand=True, controls=[
                    ft.Text("Resumen de Sesión", weight=ft.FontWeight.BOLD),
                    ft.Text(f"{reg.get('name','')} · {cash.get('full_name','')} · Desde {opened}",
                            size=11, color=ft.colors.WHITE54),
                ]),
            ], spacing=8),
            content=ft.Container(width=480, content=summary_panel),
            actions=[
                ft.TextButton("Cerrar",
                              on_click=lambda _: setattr(dlg,'open',False) or page.update()),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    # ─── Diálogo: Cerrar caja (flujo en 2 pasos) ─────────────────────────────

    def open_close_dialog(session_id: int):
        """Paso 1: confirmación simple antes de ejecutar el cierre irreversible."""

        def on_confirm(_):
            confirm_dlg.open = False
            page.update()
            _execute_close(session_id)

        confirm_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.LOCK, color=ERROR, size=22),
                ft.Text("Confirmar cierre de caja", weight=ft.FontWeight.BOLD, color=ERROR),
            ], spacing=8),
            content=ft.Container(
                width=400,
                content=ft.Column(spacing=10, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8, padding=12,
                        content=ft.Column(spacing=6, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=WARNING, size=18),
                                ft.Text("Esta acción es IRREVERSIBLE.",
                                        color=WARNING, weight=ft.FontWeight.BOLD, size=13),
                            ], spacing=8),
                            ft.Text(
                                "Al confirmar:\n"
                                "  1. La sesión de caja se cerrará\n"
                                "  2. Se imprimirá el ticket de cierre\n"
                                "  3. El cajón de dinero se abrirá\n"
                                "  4. Se mostrará el formulario de conteo físico",
                                size=12, color=ft.colors.WHITE70,
                            ),
                        ]),
                    ),
                    ft.Text("¿Confirmas el cierre de esta sesión?",
                            color=ft.colors.WHITE, size=13),
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(confirm_dlg,'open',False) or page.update()),
                ft.ElevatedButton(
                    "Sí, cerrar caja", icon=ft.icons.LOCK,
                    on_click=on_confirm,
                    style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE),
                ),
            ],
        )
        page.dialog = confirm_dlg; confirm_dlg.open = True; page.update()

    def _execute_close(session_id: int):
        """Paso 2: cierra la sesión → imprime → abre cajón → muestra conteo físico."""
        try:
            sess    = api.get_session(session_id)
            summary = api.get_session_report(session_id)
        except APIError as ex:
            _show_snack(str(ex), ERROR); return

        summary_panel, expected = _build_summary_panel(summary, sess)

        # ── Cerrar la sesión con el monto esperado (actualizable después) ────
        try:
            api.close_session(session_id, {
                "closing_amount": expected,
                "notes": None,
            })
        except APIError as ex:
            _show_snack(str(ex), ERROR); return

        # Actualizar estado de la app
        if app_state.get("session_id") == session_id:
            app_state["session_id"] = None

        # ── Imprimir ticket de cierre y abrir cajón ─────────────────────────
        try:
            from services.printer import TicketPrinter
            tp = TicketPrinter(api.get_config_map())
            sess_closed = api.get_session(session_id)
            if tp.enabled and not tp.print_session_close(sess_closed, summary):
                _show_snack(f"⚠ No se pudo imprimir el corte: {tp.last_error}", WARNING)
            tp.open_drawer()
        except Exception as ex:
            _show_snack(f"⚠ No se pudo imprimir el corte: {ex}", WARNING)

        load_data()

        # ── Mostrar resumen + conteo físico con desglose de denominaciones ────
        COINS = [0.50, 1, 2, 5, 10]
        BILLS = [20, 50, 100, 200, 500, 1000]

        # Estado de cada denominación: {valor: {qty: TextField, sub: Text}}
        denom_state: dict = {}
        for d in COINS + BILLS:
            qty_f = ft.TextField(
                value="",
                hint_text="0",
                width=58,
                text_align=ft.TextAlign.CENTER,
                keyboard_type=ft.KeyboardType.NUMBER,
                border_color=PRIMARY + "88",
                focused_border_color=PRIMARY,
                color=ft.colors.WHITE,
                bgcolor=BG_DARK,
                text_size=14,
                content_padding=ft.padding.symmetric(4, 6),
            )
            sub_t = ft.Text(
                "—", size=12, color=ft.colors.WHITE38, width=76,
                text_align=ft.TextAlign.RIGHT,
            )
            denom_state[d] = {"qty": qty_f, "sub": sub_t}

        # Total del conteo de denominaciones
        denom_total_text = ft.Text(
            f"{currency}0.00", size=20, color=PRIMARY_LT,
            weight=ft.FontWeight.BOLD,
        )

        # Campo de conteo (puede llenarse manual o automáticamente)
        f_count = ft.TextField(
            label="Conteo físico total en caja",
            value=f"{expected:.2f}",
            prefix_text=currency,
            keyboard_type=ft.KeyboardType.NUMBER,
            hint_text="Escribe o usa el total del desglose →",
        )
        f_notes_close = ft.TextField(
            label="Notas del cierre (opcional)",
            multiline=True, min_lines=2,
        )
        diff_text = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=SUCCESS)

        def update_diff(e=None):
            try:
                conteo = float(f_count.value or 0)
                diff   = conteo - expected
                diff_text.value = f"Diferencia: {currency}{diff:+.2f}"
                diff_text.color = (SUCCESS if diff == 0
                                   else WARNING if abs(diff) < 10
                                   else ERROR)
            except Exception:
                diff_text.value = ""
            page.update()

        def recalc_denoms(e=None):
            """Recalcula subtotales y actualiza el campo de conteo total."""
            grand = 0.0
            for valor, ds in denom_state.items():
                try:
                    qty = int(ds["qty"].value or 0)
                except ValueError:
                    qty = 0
                sub = qty * valor
                grand += sub
                if qty > 0:
                    ds["sub"].value = f"{currency}{sub:.2f}"
                    ds["sub"].color = ft.colors.WHITE70
                else:
                    ds["sub"].value = "—"
                    ds["sub"].color = ft.colors.WHITE24
            denom_total_text.value = f"{currency}{grand:.2f}"
            # Auto-rellenar el campo de conteo físico
            f_count.value = f"{grand:.2f}"
            update_diff()

        for ds in denom_state.values():
            ds["qty"].on_change  = recalc_denoms
            ds["qty"].on_submit  = recalc_denoms

        f_count.on_change = update_diff

        def _denom_row(valor: float) -> ft.Row:
            ds     = denom_state[valor]
            label  = (f"{currency}{valor:.2f}" if valor < 1
                      else f"{currency}{int(valor)}")
            is_bill = valor >= 20
            badge_color = ft.colors.BLUE_GREY_400
            return ft.Row([
                ft.Container(
                    width=56, height=26, border_radius=4,
                    bgcolor=badge_color + "33",
                    border=ft.border.all(1, badge_color + "88"),
                    alignment=ft.alignment.center,
                    content=ft.Text(label, size=12, color=ft.colors.WHITE,
                                    weight=ft.FontWeight.W_600),
                ),
                ds["qty"],
                ds["sub"],
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        coin_rows = [_denom_row(d) for d in COINS]
        bill_rows = [_denom_row(d) for d in BILLS]

        def use_denom_total(e=None):
            """Copia el total del desglose al campo de conteo."""
            recalc_denoms()

        right_col = ft.Container(
            expand=True,
            content=ft.Column(
                spacing=8, scroll=ft.ScrollMode.AUTO,
                controls=[
                    # Encabezado
                    ft.Row([
                        ft.Icon(ft.icons.CALCULATE, color=PRIMARY_LT, size=16),
                        ft.Text("Desglose por denominación",
                                size=13, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6),
                    ft.Divider(color=ft.colors.WHITE12, height=4),

                    # Monedas y Billetes lado a lado
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            # Monedas
                            ft.Container(
                                expand=True,
                                bgcolor=ft.colors.BLUE_GREY_900, border_radius=6,
                                padding=ft.padding.all(8),
                                content=ft.Column(spacing=6, controls=[
                                    ft.Row([
                                        ft.Icon(ft.icons.GENERATING_TOKENS,
                                                color=ft.colors.BLUE_GREY_400, size=14),
                                        ft.Text("MONEDAS", size=10,
                                                color=ft.colors.BLUE_GREY_300,
                                                weight=ft.FontWeight.BOLD),
                                    ], spacing=4),
                                    *coin_rows,
                                ]),
                            ),
                            # Billetes
                            ft.Container(
                                expand=True,
                                bgcolor=ft.colors.BLUE_GREY_900, border_radius=6,
                                padding=ft.padding.all(8),
                                content=ft.Column(spacing=6, controls=[
                                    ft.Row([
                                        ft.Icon(ft.icons.ATTACH_MONEY,
                                                color=ft.colors.BLUE_GREY_400, size=14),
                                        ft.Text("BILLETES", size=10,
                                                color=ft.colors.BLUE_GREY_300,
                                                weight=ft.FontWeight.BOLD),
                                    ], spacing=4),
                                    *bill_rows,
                                ]),
                            ),
                        ],
                    ),

                    # Total del desglose
                    ft.Container(
                        bgcolor=PRIMARY + "1A", border_radius=8,
                        border=ft.border.all(1, PRIMARY + "55"),
                        padding=ft.padding.symmetric(horizontal=10, vertical=8),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Text("Total del desglose:",
                                        color=ft.colors.WHITE70, size=12, expand=True),
                                denom_total_text,
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.ElevatedButton(
                                "↑ Usar como conteo físico",
                                icon=ft.icons.ARROW_UPWARD,
                                expand=True, height=36,
                                on_click=use_denom_total,
                                style=ft.ButtonStyle(
                                    bgcolor=PRIMARY + "44", color=PRIMARY_LT,
                                    side=ft.BorderSide(1, PRIMARY),
                                    shape=ft.RoundedRectangleBorder(radius=6),
                                ),
                            ),
                        ]),
                    ),
                ],
            ),
        )

        left_col = ft.Container(
            width=360,
            content=ft.Column(
                spacing=8, scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Container(
                        bgcolor=SUCCESS + "1A", border_radius=8, padding=10,
                        content=ft.Row([
                            ft.Icon(ft.icons.INFO_OUTLINE, color=SUCCESS, size=16),
                            ft.Text(
                                "Caja cerrada · Ticket impreso · Cajón abierto. "
                                "Cuenta el efectivo.",
                                size=11, color=ft.colors.WHITE70, expand=True,
                            ),
                        ], spacing=8),
                    ),
                    summary_panel,
                    ft.Divider(color=ft.colors.WHITE12),
                    f_count,
                    diff_text,
                    f_notes_close,
                ],
            ),
        )

        def save_count(_):
            try:
                conteo = float(f_count.value or expected)
                api.update_physical_count(session_id, conteo)
                if f_notes_close.value.strip():
                    try:
                        api.close_session(session_id,
                                          {"closing_amount": conteo,
                                           "notes": f_notes_close.value.strip()})
                    except Exception:
                        pass
                _show_snack(f"✅ Conteo físico registrado: {currency}{conteo:.2f}")
                count_dlg.open = False; page.update()
                load_data()
            except APIError as ex:
                _show_snack(str(ex), ERROR)

        def download_close_pdf(_):
            try:
                from services.printer import TicketPrinter
                tp = TicketPrinter(api.get_config_map())
                sess_for_pdf = api.get_session(session_id)
                summary_for_pdf = api.get_session_report(session_id)
                path = tp.print_session_close_pdf(sess_for_pdf, summary_for_pdf)
                if path:
                    _show_snack(f"✅ PDF guardado: {path}")
                else:
                    _show_snack("⚠ Instala fpdf2:  pip install fpdf2", WARNING)
            except Exception as ex:
                _show_snack(f"Error PDF: {ex}", ERROR)

        count_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.CHECK_CIRCLE, color=SUCCESS, size=22),
                ft.Text("Caja cerrada — Conteo físico", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=860,
                height=560,
                content=ft.Row(
                    expand=True, spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[left_col, ft.VerticalDivider(width=1, color=ft.colors.WHITE12), right_col],
                ),
            ),
            actions=[
                ft.TextButton("Cerrar sin guardar",
                              on_click=lambda _: setattr(count_dlg,'open',False) or page.update()),
                ft.ElevatedButton(
                    "📄 PDF cierre", icon=ft.icons.PICTURE_AS_PDF,
                    on_click=download_close_pdf,
                    style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=PRIMARY_LT,
                                         side=ft.BorderSide(1, PRIMARY)),
                ),
                ft.ElevatedButton(
                    "Guardar conteo", icon=ft.icons.SAVE,
                    on_click=save_count,
                    style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                ),
            ],
        )
        page.dialog = count_dlg; count_dlg.open = True; page.update()

    # ─── Diálogo: Movimiento de efectivo ──────────────────────────────────────

    def open_movement_dialog(session_id: int):
        f_type   = ft.Dropdown(
            label="Tipo de movimiento *",
            value="expense",
            options=[
                ft.dropdown.Option("income",  "➕ Entrada (depósito)"),
                ft.dropdown.Option("expense", "➖ Salida (retiro)"),
            ],
        )
        f_amount = ft.TextField(label="Monto *", prefix_text=currency,
                                keyboard_type=ft.KeyboardType.NUMBER)
        f_reason = ft.TextField(label="Motivo *",
                                hint_text="Ej: Retiro de fondo, pago de servicio, cambio...")
        err_text = ft.Text("", color=ERROR, size=12)

        def save(e):
            if not f_amount.value or not f_reason.value.strip():
                err_text.value = "Monto y motivo son obligatorios"; page.update(); return
            try:
                api.add_cash_movement(session_id, {
                    "movement_type": f_type.value,
                    "amount": float(f_amount.value),
                    "reason": f_reason.value.strip(),
                })
                dlg.open = False; page.update()
                # Abrir cajón: el movimiento justifica su apertura.
                # Usar una instancia con la configuración real (la global
                # `printer` se crea con config vacía y nunca se actualiza,
                # por lo que enabled=False y solo simula la apertura).
                drawer_msg = ""
                try:
                    from services.printer import TicketPrinter
                    tp = TicketPrinter(api.get_config_map())
                    if tp.enabled and tp.open_drawer_enabled:
                        if tp.open_drawer():
                            drawer_msg = " · Cajón abierto"
                        else:
                            drawer_msg = f" · ⚠ No se pudo abrir el cajón: {tp.last_error}"
                except Exception as ex:
                    drawer_msg = f" · ⚠ No se pudo abrir el cajón: {ex}"
                tipo = "Entrada" if f_type.value == "income" else "Salida"
                _show_snack(
                    f"✅ {tipo} de {currency}{float(f_amount.value):.2f} registrada"
                    f"{drawer_msg}"
                )
                load_data()
            except APIError as ex:
                err_text.value = str(ex); page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Movimiento de Efectivo", weight=ft.FontWeight.BOLD),
            content=ft.Column(spacing=10, controls=[f_type, f_amount, f_reason, err_text]),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: setattr(dlg,'open',False) or page.update()),
                ft.ElevatedButton("Registrar", icon=ft.icons.SAVE, on_click=save,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = dlg; dlg.open = True; page.update()

    # ─── Historial ────────────────────────────────────────────────────────────

    def _render_history():
        history_list.controls.clear()
        for s in history:
            status   = s.get("status","")
            is_open  = status == "open"
            reg      = s.get("register", {})
            cashier  = s.get("cashier", {})
            opened   = _fmt_dt(s.get("opened_at", ""))
            closed   = _fmt_dt(s.get("closed_at") or "") if s.get("closed_at") else "—"
            opening  = float(s.get("opening_amount", 0))
            closing  = s.get("closing_amount")
            diff     = s.get("difference")

            diff_color = (
                SUCCESS if diff is not None and abs(float(diff)) < 0.01 else
                WARNING if diff is not None and abs(float(diff)) < 50 else ERROR
            ) if diff is not None else ft.colors.WHITE38

            history_list.controls.append(ft.Container(
                bgcolor=BG_CARD, border_radius=10,
                border=ft.border.all(1, SUCCESS+"44" if is_open else ft.colors.WHITE12),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                content=ft.Row([
                    ft.Container(
                        width=10, height=10, border_radius=5,
                        bgcolor=SUCCESS if is_open else ft.colors.WHITE24,
                    ),
                    ft.Column(expand=True, spacing=3, controls=[
                        ft.Row([
                            ft.Text(reg.get("name",""), color=ft.colors.WHITE, size=14,
                                    weight=ft.FontWeight.W_600),
                            ft.Container(
                                content=ft.Text("ABIERTA" if is_open else "CERRADA",
                                                size=10, color=ft.colors.WHITE),
                                bgcolor=SUCCESS+"55" if is_open else BG_SURFACE,
                                border_radius=4, padding=ft.padding.symmetric(2, 6),
                            ),
                        ], spacing=8),
                        ft.Row([
                            ft.Icon(ft.icons.PERSON, size=12, color=ft.colors.WHITE38),
                            ft.Text(cashier.get("full_name",""), size=12, color=ft.colors.WHITE54),
                            ft.Text("·", color=ft.colors.WHITE24),
                            ft.Text(f"Apertura: {opened}", size=12, color=ft.colors.WHITE38),
                            ft.Text("·", color=ft.colors.WHITE24),
                            ft.Text(f"Cierre: {closed}", size=12, color=ft.colors.WHITE38),
                        ], spacing=4),
                    ]),
                    ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                        ft.Text(f"Fondo: {currency}{opening:.2f}", size=11, color=ft.colors.WHITE54),
                        ft.Text(
                            f"Cierre: {currency}{float(closing):.2f}" if closing else "—",
                            size=12, color=ft.colors.WHITE70,
                        ),
                        ft.Text(
                            f"Diff: {currency}{float(diff):+.2f}" if diff is not None else "",
                            size=12, color=diff_color, weight=ft.FontWeight.BOLD,
                        ),
                    ]),
                ], spacing=12),
            ))
        status_text.value = f"{len(history)} sesión(es)"
        page.update()

    # Carga inicial
    load_data()

    # ─── Layout ───────────────────────────────────────────────────────────────

    tabs = ft.Tabs(
        expand=True, selected_index=0,
        indicator_color=PRIMARY,
        label_color=PRIMARY_LT,
        unselected_label_color=ft.colors.WHITE54,
        tabs=[
            ft.Tab(
                text="Sesiones Activas",
                icon=ft.icons.POINT_OF_SALE,
                content=ft.Column(
                    expand=True, spacing=0,
                    controls=[
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=12, vertical=10),
                            content=ft.Row([
                                ft.Text("Control de Cajas", size=18, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD, expand=True),
                                ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                              on_click=load_data, tooltip="Actualizar"),
                            ]),
                        ),
                        ft.Container(
                            expand=True,
                            padding=ft.padding.symmetric(horizontal=12),
                            content=ft.ListView(expand=True, controls=[session_panel], spacing=10),
                        ),
                    ],
                ),
            ),
            ft.Tab(
                text="Historial",
                icon=ft.icons.HISTORY,
                content=ft.Column(
                    expand=True, spacing=0,
                    controls=[
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=12, vertical=10),
                            content=ft.Row([
                                ft.Text("Historial de Sesiones", size=18, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD, expand=True),
                                status_text,
                                ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                              on_click=load_data, tooltip="Actualizar"),
                            ]),
                        ),
                        ft.Container(expand=True, padding=ft.padding.symmetric(horizontal=12),
                                     content=history_list),
                    ],
                ),
            ),
        ],
    )

    return ft.Container(expand=True, bgcolor=BG_DARK, content=tabs)
