"""
Vista de Ventas – Resumen mensual de todas las ventas (Gerentes/Administradores)
"""
import calendar
import flet as ft
from datetime import date
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError
from components import loading_icon_button
from .pos import _fmt_dt


STATUS_LABELS = {
    "completed":      ("Completada",   SUCCESS),
    "cancelled":      ("Cancelada",    ERROR),
    "partial_return": ("Dev. parcial", WARNING),
    "refunded":       ("Reembolsada",  WARNING),
}
METHOD_LABELS = {
    "cash": "Efectivo", "card": "Tarjeta",
    "transfer": "Transferencia", "mixed": "Mixto",
}
MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def sales_view(page: ft.Page, app_state: dict):
    cfg      = app_state.get("config", {})
    currency = cfg.get("fiscal.currency_symbol", "$")
    tax_name = cfg.get("fiscal.tax_name", "IVA")

    if not api.is_manager():
        return ft.Container(
            expand=True, bgcolor=BG_DARK, alignment=ft.alignment.center,
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.icons.LOCK, size=64, color=ft.colors.WHITE24),
                ft.Text("Acceso restringido", size=18, color=ft.colors.WHITE54),
            ]),
        )

    today = date.today()
    state = {"year": today.year, "month": today.month, "sales": []}

    def _snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    # ── Filtros de mes/año ────────────────────────────────────────────────────
    month_dd = ft.Dropdown(
        value=str(state["month"]), width=160,
        color=ft.colors.WHITE, border_color=PRIMARY, bgcolor=BG_SURFACE,
        options=[ft.dropdown.Option(str(i + 1), MONTH_NAMES[i]) for i in range(12)],
    )
    year_dd = ft.Dropdown(
        value=str(state["year"]), width=110,
        color=ft.colors.WHITE, border_color=PRIMARY, bgcolor=BG_SURFACE,
        options=[ft.dropdown.Option(str(y)) for y in range(today.year, today.year - 6, -1)],
    )

    loading_text = ft.Text("Cargando ventas...", color=ft.colors.WHITE54, italic=True)
    sales_list   = ft.ListView(expand=True, spacing=6, padding=ft.padding.all(4))
    summary_count  = ft.Text("", size=13, color=ft.colors.WHITE70)
    summary_total  = ft.Text("", size=22, weight=ft.FontWeight.BOLD, color=PRIMARY_LT)
    summary_completed = ft.Text("", size=12, color=ft.colors.WHITE54)

    # ── Filtros de búsqueda ────────────────────────────────────────────────────
    search_field = ft.TextField(
        hint_text="Buscar por folio, cliente o producto...",
        prefix_icon=ft.icons.SEARCH,
        expand=True, height=44,
        color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
        hint_style=ft.TextStyle(color=ft.colors.WHITE38),
    )
    status_dd = ft.Dropdown(
        label="Estado", value="all", width=160, height=44,
        color=ft.colors.WHITE, border_color=PRIMARY, bgcolor=BG_SURFACE,
        options=[
            ft.dropdown.Option("all", "Todos"),
            ft.dropdown.Option("completed", "Completada"),
            ft.dropdown.Option("partial_return", "Dev. parcial"),
            ft.dropdown.Option("cancelled", "Cancelada"),
            ft.dropdown.Option("refunded", "Reembolsada"),
        ],
    )
    method_dd = ft.Dropdown(
        label="Método de pago", value="all", width=170, height=44,
        color=ft.colors.WHITE, border_color=PRIMARY, bgcolor=BG_SURFACE,
        options=[
            ft.dropdown.Option("all", "Todos"),
            ft.dropdown.Option("cash", "Efectivo"),
            ft.dropdown.Option("card", "Tarjeta"),
            ft.dropdown.Option("transfer", "Transferencia"),
            ft.dropdown.Option("mixed", "Mixto"),
        ],
    )
    cashier_dd = ft.Dropdown(
        label="Cajero", value="all", width=190, height=44,
        color=ft.colors.WHITE, border_color=PRIMARY, bgcolor=BG_SURFACE,
        options=[ft.dropdown.Option("all", "Todos")],
    )
    amount_min_field = ft.TextField(
        label="Monto mín.", width=110, height=44,
        keyboard_type=ft.KeyboardType.NUMBER,
        color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
    )
    amount_max_field = ft.TextField(
        label="Monto máx.", width=110, height=44,
        keyboard_type=ft.KeyboardType.NUMBER,
        color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
    )
    results_count_text = ft.Text("", size=11, color=ft.colors.WHITE38)

    # ── Carga de datos ─────────────────────────────────────────────────────────

    def _date_range():
        y, m = state["year"], state["month"]
        start = date(y, m, 1)
        last_day = calendar.monthrange(y, m)[1]
        end = date(y, m, last_day)
        return start.isoformat(), end.isoformat()

    def load_sales(e=None):
        try:
            state["year"]  = int(year_dd.value)
            state["month"] = int(month_dd.value)
        except (TypeError, ValueError):
            pass

        loading_text.value   = "Cargando ventas..."
        loading_text.visible = True
        sales_list.controls.clear()
        page.update()

        try:
            start, end = _date_range()
            sales = api.get_sales(params={"start_date": start, "end_date": end, "limit": 500})
            sales = sorted(sales, key=lambda s: s.get("created_at", ""), reverse=True)
            state["sales"] = sales
            _update_cashier_options(sales)
            loading_text.visible = False
            _render()
        except APIError as ex:
            loading_text.value = f"Error: {ex}"
            page.update()

    def _update_cashier_options(sales: list):
        """Reconstruye las opciones del filtro de cajero a partir de las ventas cargadas."""
        names = sorted({
            (s.get("cashier") or {}).get("full_name", "")
            for s in sales if (s.get("cashier") or {}).get("full_name")
        })
        current = cashier_dd.value
        cashier_dd.options = [ft.dropdown.Option("all", "Todos")] + [
            ft.dropdown.Option(name, name) for name in names
        ]
        # Mantener la selección si sigue siendo válida, si no volver a "Todos"
        cashier_dd.value = current if current in (["all"] + names) else "all"

    # ── Filtrado ────────────────────────────────────────────────────────────────

    def _matches_filters(sale: dict) -> bool:
        # Texto libre: folio, cliente, productos
        term = (search_field.value or "").strip().lower()
        if term:
            haystacks = [
                sale.get("folio", ""),
                sale.get("customer_name") or "",
                sale.get("customer_tax_id") or "",
            ]
            haystacks += [it.get("product_name", "") for it in sale.get("items", [])]
            haystacks += [it.get("product_code", "") for it in sale.get("items", [])]
            if not any(term in h.lower() for h in haystacks):
                return False

        # Estado
        if status_dd.value and status_dd.value != "all":
            if sale.get("status", "completed") != status_dd.value:
                return False

        # Método de pago
        if method_dd.value and method_dd.value != "all":
            if sale.get("payment_method", "") != method_dd.value:
                return False

        # Cajero
        if cashier_dd.value and cashier_dd.value != "all":
            if (sale.get("cashier") or {}).get("full_name", "") != cashier_dd.value:
                return False

        # Rango de monto
        total = float(sale.get("total", 0))
        try:
            if amount_min_field.value and total < float(amount_min_field.value):
                return False
        except ValueError:
            pass
        try:
            if amount_max_field.value and total > float(amount_max_field.value):
                return False
        except ValueError:
            pass

        return True

    def _filtered_sales() -> list:
        return [s for s in state["sales"] if _matches_filters(s)]

    def apply_filters(e=None):
        _render()

    def clear_filters(e=None):
        search_field.value     = ""
        status_dd.value        = "all"
        method_dd.value        = "all"
        cashier_dd.value       = "all"
        amount_min_field.value = ""
        amount_max_field.value = ""
        _render()

    search_field.on_change      = apply_filters
    search_field.on_submit      = apply_filters
    status_dd.on_change          = apply_filters
    method_dd.on_change          = apply_filters
    cashier_dd.on_change         = apply_filters
    amount_min_field.on_change   = apply_filters
    amount_max_field.on_change   = apply_filters

    def _render():
        sales_list.controls.clear()
        all_sales = state["sales"]
        sales = _filtered_sales()

        total_neto = sum(
            float(s.get("total", 0))
            for s in sales if s.get("status") != "cancelled"
        )
        n_completed = sum(1 for s in sales if s.get("status") != "cancelled")
        n_cancelled = sum(1 for s in sales if s.get("status") == "cancelled")

        summary_count.value = f"{len(sales)} venta(s) en {MONTH_NAMES[state['month']-1]} {state['year']}"
        summary_total.value = f"{currency}{total_neto:.2f}"
        summary_completed.value = (
            f"{n_completed} válida(s)" + (f" · {n_cancelled} cancelada(s)" if n_cancelled else "")
        )

        if len(sales) != len(all_sales):
            results_count_text.value = f"Mostrando {len(sales)} de {len(all_sales)} venta(s) — filtros activos"
        else:
            results_count_text.value = ""

        if not sales:
            sales_list.controls.append(
                ft.Container(
                    alignment=ft.alignment.center, padding=40,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.icons.RECEIPT_LONG, size=48, color=ft.colors.WHITE24),
                            ft.Text(
                                "Sin ventas que coincidan con los filtros"
                                if all_sales else "Sin ventas en este mes",
                                color=ft.colors.WHITE54,
                            ),
                        ],
                    ),
                )
            )
        else:
            for sale in sales:
                sales_list.controls.append(_sale_row(sale))
        page.update()

    # ── Fila de venta ──────────────────────────────────────────────────────────

    def _sale_row(sale: dict):
        status   = sale.get("status", "completed")
        s_label, s_color = STATUS_LABELS.get(status, (status, ft.colors.WHITE54))
        folio    = sale.get("folio", "—")
        total    = float(sale.get("total", 0))
        items    = sale.get("items", [])
        method   = METHOD_LABELS.get(sale.get("payment_method", ""), "—")
        created  = _fmt_dt(sale.get("created_at", ""), "%d/%m/%Y  %H:%M")
        cashier  = (sale.get("cashier") or {}).get("full_name", "")
        is_done  = status != "cancelled"

        return ft.Container(
            bgcolor=BG_SURFACE if is_done else BG_DARK,
            border_radius=8,
            border=ft.border.all(1, (s_color + "44") if not is_done else ft.colors.WHITE12),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            ink=True,
            on_click=lambda _, s=sale: _open_detail_dialog(s),
            content=ft.Row([
                ft.Column(expand=True, spacing=3, controls=[
                    ft.Row([
                        ft.Text(folio, size=14, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                        ft.Container(
                            content=ft.Text(s_label, size=10, color=ft.colors.WHITE),
                            bgcolor=s_color + "55", border_radius=4,
                            padding=ft.padding.symmetric(2, 6),
                        ),
                        ft.Text(f"• {method}", size=11, color=ft.colors.WHITE54),
                    ], spacing=6),
                    ft.Row([
                        ft.Icon(ft.icons.ACCESS_TIME, size=12, color=ft.colors.WHITE38),
                        ft.Text(created, size=11, color=ft.colors.WHITE54),
                        ft.Text("•", color=ft.colors.WHITE24),
                        ft.Icon(ft.icons.PERSON, size=12, color=ft.colors.WHITE38),
                        ft.Text(cashier, size=11, color=ft.colors.WHITE54),
                        ft.Text("•", color=ft.colors.WHITE24),
                        ft.Text(f"{len(items)} artículo(s)", size=11, color=ft.colors.WHITE54),
                    ], spacing=4),
                ]),
                ft.Text(f"{currency}{total:.2f}", size=16,
                        color=PRIMARY_LT if is_done else ft.colors.WHITE38,
                        weight=ft.FontWeight.BOLD),
                ft.Icon(ft.icons.CHEVRON_RIGHT, color=ft.colors.WHITE24, size=20),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
        )

    # ── Diálogo de aprobación de supervisor ───────────────────────────────────

    def _open_supervisor_dialog(title: str, on_approved):
        f_user = ft.TextField(label="Usuario del supervisor",
                              color=ft.colors.WHITE, bgcolor=BG_SURFACE,
                              border_color=PRIMARY, autofocus=True)
        f_pass = ft.TextField(label="Contraseña", password=True, can_reveal_password=True,
                              color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        err_t  = ft.Text("", color=ERROR, size=12)

        def verify(e):
            if not f_user.value.strip() or not f_pass.value:
                err_t.value = "Usuario y contraseña son obligatorios"; page.update(); return
            try:
                r = api.verify_supervisor(f_user.value.strip(), f_pass.value)
                sup_dlg.open = False; page.update()
                on_approved(r["supervisor_id"], r["full_name"])
            except APIError as ex:
                err_t.value = str(ex); page.update()

        f_user.on_submit = verify
        f_pass.on_submit = verify

        sup_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.VERIFIED_USER, color=WARNING),
                ft.Text(title, weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=380,
                content=ft.Column(spacing=10, controls=[
                    ft.Container(
                        bgcolor=WARNING + "1A", border_radius=8, padding=10,
                        content=ft.Row([
                            ft.Icon(ft.icons.LOCK, color=WARNING, size=16),
                            ft.Text("Se requiere aprobación de Gerente o Administrador.",
                                    size=12, color=ft.colors.WHITE70, expand=True),
                        ], spacing=8),
                    ),
                    f_user, f_pass, err_t,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(sup_dlg, "open", False) or page.update()),
                ft.ElevatedButton("Verificar y aprobar", icon=ft.icons.VERIFIED_USER,
                                  on_click=verify,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = sup_dlg; sup_dlg.open = True; page.update()

    # ── Diálogo de cancelación ─────────────────────────────────────────────────

    def _open_cancel_dialog(sale: dict):
        folio = sale.get('folio', '')
        f_reason = ft.TextField(
            label="Motivo de cancelación *",
            hint_text="Ej: Error en producto, solicitud del cliente...",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=ERROR, autofocus=True,
        )
        err_text = ft.Text("", color=ERROR, size=12)

        def request_cancel(e):
            if not f_reason.value.strip():
                err_text.value = "El motivo es obligatorio"; page.update(); return
            cancel_dlg.open = False; page.update()
            _open_supervisor_dialog(
                f"Aprobar cancelación — {folio}",
                lambda sup_id, sup_name: _do_cancel(sup_id, sup_name),
            )

        def _do_cancel(sup_id, sup_name):
            try:
                api.cancel_sale(sale["id"], f_reason.value.strip(), supervisor_id=sup_id)
                load_sales()
                _snack(f"✅ Venta {folio} cancelada · Aprobado por {sup_name}")
            except APIError as ex:
                _snack(str(ex), ERROR)

        cancel_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.CANCEL, color=ERROR),
                ft.Text(f"Cancelar venta {folio}", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=420,
                content=ft.Column(spacing=10, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8, padding=10,
                        content=ft.Row([
                            ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=ERROR, size=18),
                            ft.Text(
                                "Revertirá el inventario de todos los productos. "
                                "Requerirá aprobación de gerente.",
                                size=12, color=ft.colors.WHITE70, expand=True,
                            ),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                    ),
                    ft.Row([
                        ft.Text("Total a revertir:", color=ft.colors.WHITE70),
                        ft.Text(f"{currency}{float(sale.get('total',0)):.2f}",
                                color=ERROR, weight=ft.FontWeight.BOLD, size=16),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    f_reason, err_text,
                ]),
            ),
            actions=[
                ft.TextButton("No cancelar",
                              on_click=lambda _: setattr(cancel_dlg, "open", False) or page.update()),
                ft.ElevatedButton("Continuar →",
                                  icon=ft.icons.ARROW_FORWARD,
                                  on_click=request_cancel,
                                  style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = cancel_dlg; cancel_dlg.open = True; page.update()

    # ── Diálogo de devolución ──────────────────────────────────────────────────

    def _open_return_dialog(sale: dict):
        folio = sale.get('folio', '')
        items = sale.get("items", [])
        return_state = {}
        for item in items:
            chk = ft.Checkbox(value=False, fill_color=PRIMARY)
            qty = ft.TextField(
                value=str(int(item.get("quantity", 1))),
                width=55, text_align=ft.TextAlign.CENTER,
                keyboard_type=ft.KeyboardType.NUMBER,
                border_color=PRIMARY, color=ft.colors.WHITE,
                bgcolor=BG_DARK, text_size=13,
                content_padding=ft.padding.symmetric(4, 6),
                disabled=True,
            )

            def make_toggle(c, q):
                def fn(e): q.disabled = not c.value; page.update()
                return fn
            chk.on_change = make_toggle(chk, qty)
            return_state[item.get("id")] = {"item": item, "chk": chk, "qty": qty}

        f_reason = ft.TextField(
            label="Motivo de la devolución *",
            hint_text="Ej: Producto defectuoso, cambio de artículo...",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=WARNING,
        )
        chk_cash = ft.Checkbox(
            label="Devolver en efectivo (descuenta del físico en caja)",
            value=True,
            fill_color=SUCCESS,
            check_color=ft.colors.WHITE,
        )
        err_t = ft.Text("", color=ERROR, size=12)

        item_rows = []
        for sid, st in return_state.items():
            it = st["item"]
            item_rows.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                content=ft.Row([
                    st["chk"],
                    ft.Text(it.get("product_name", "")[:28], size=13,
                            color=ft.colors.WHITE, expand=True),
                    ft.Text(f"Disp: {it.get('quantity',0):.0f}", size=11,
                            color=ft.colors.WHITE54, width=60),
                    ft.Text("Dev:", size=11, color=ft.colors.WHITE54),
                    st["qty"],
                    ft.Text(f"{currency}{float(it.get('subtotal',0)):.2f}",
                            size=13, color=PRIMARY_LT, width=72,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        def request_return(e):
            selected = [
                {"sale_item_id": sid,
                 "quantity": float(st["qty"].value or st["item"]["quantity"])}
                for sid, st in return_state.items() if st["chk"].value
            ]
            if not selected:
                err_t.value = "Selecciona al menos un artículo"; page.update(); return
            if not f_reason.value.strip():
                err_t.value = "El motivo es obligatorio"; page.update(); return
            is_cash = chk_cash.value
            ret_dlg.open = False; page.update()
            _open_supervisor_dialog(
                f"Aprobar devolución — {folio}",
                lambda sup_id, sup_name: _do_return(sup_id, sup_name, selected, is_cash),
            )

        def _do_return(sup_id, sup_name, selected, is_cash):
            try:
                r = api.process_return(
                    sale["id"], sup_id, selected,
                    f_reason.value.strip(),
                    is_cash_return=is_cash,
                )
                total_dev = float(r.get("total_returned", 0))
                cash_dev  = float(r.get("cash_returned", 0))
                load_sales()
                medio = "efectivo" if is_cash else "tarjeta/transferencia"
                drawer_msg = ""
                if is_cash and cash_dev > 0:
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
                _snack(
                    f"✅ Devolución {folio}: {currency}{total_dev:.2f} en {medio} · "
                    f"Aprobado por {sup_name}{drawer_msg}"
                )
            except APIError as ex:
                _snack(str(ex), ERROR)

        ret_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.ASSIGNMENT_RETURN, color=WARNING),
                ft.Text(f"Devolución — {folio}", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=520,
                content=ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, controls=[
                    ft.Container(
                        bgcolor=WARNING + "1A", border_radius=8, padding=10,
                        content=ft.Row([
                            ft.Icon(ft.icons.INFO_OUTLINE, color=WARNING, size=16),
                            ft.Text(
                                "Marca los artículos a devolver y ajusta la cantidad. "
                                "Se reintegrará el inventario y requerirá aprobación.",
                                size=12, color=ft.colors.WHITE70, expand=True,
                            ),
                        ], spacing=8),
                    ),
                    ft.Text("Artículos de la venta:", size=12,
                            color=ft.colors.WHITE70, weight=ft.FontWeight.W_600),
                    *item_rows,
                    ft.Divider(color=ft.colors.WHITE12),
                    chk_cash,
                    ft.Container(
                        bgcolor=SUCCESS + "11", border_radius=6,
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        content=ft.Text(
                            "Activo: el importe se resta del efectivo en caja.\n"
                            "Inactivo: devolución por tarjeta/transferencia, no afecta la caja.",
                            size=11, color=ft.colors.WHITE54,
                        ),
                    ),
                    f_reason, err_t,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(ret_dlg, "open", False) or page.update()),
                ft.ElevatedButton("Continuar →",
                                  icon=ft.icons.ARROW_FORWARD,
                                  on_click=request_return,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = ret_dlg; ret_dlg.open = True; page.update()

    # ── Diálogo de detalle de venta ───────────────────────────────────────────

    def _open_detail_dialog(sale: dict):
        # Recargar la venta completa por si los datos del listado están desactualizados
        try:
            sale = api.get_sale(sale["id"])
        except APIError:
            pass

        status = sale.get("status", "completed")
        is_cancellable = status in ("completed", "partial_return")
        is_returnable  = status in ("completed", "partial_return")

        try:
            sale_returns = api.get_sale_returns(sale["id"])
        except Exception:
            sale_returns = []

        total_original = float(sale.get("total", 0))
        total_devuelto = sum(r.get("total_returned", 0) for r in sale_returns)
        total_neto     = total_original - total_devuelto

        items_list = ft.Column(spacing=4, controls=[
            ft.Container(
                bgcolor=BG_SURFACE, border_radius=6,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                content=ft.Row([
                    ft.Text(item.get("product_name", ""), size=12,
                            color=ft.colors.WHITE, expand=True),
                    ft.Text(f"{item.get('quantity',0):.0f} ×", size=11, color=ft.colors.WHITE54),
                    ft.Text(f"{currency}{float(item.get('unit_price',0)):.2f}",
                            size=11, color=ft.colors.WHITE54, width=70,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(f"{currency}{float(item.get('subtotal',0)):.2f}",
                            size=13, color=PRIMARY_LT, weight=ft.FontWeight.BOLD, width=80,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=6),
            )
            for item in sale.get("items", [])
        ])

        s_label, s_color = STATUS_LABELS.get(status, (status, ft.colors.WHITE54))
        method = METHOD_LABELS.get(sale.get("payment_method", ""), "—")
        cashier = (sale.get("cashier") or {}).get("full_name", "—")
        created = _fmt_dt(sale.get("created_at", ""))

        # Sección de devoluciones (visible solo si hay alguna)
        returns_section = []
        if sale_returns:
            returns_section.append(ft.Divider(color=ft.colors.WHITE12))
            returns_section.append(ft.Row([
                ft.Icon(ft.icons.ASSIGNMENT_RETURN, color=WARNING, size=16),
                ft.Text("Devoluciones registradas",
                        size=12, color=WARNING, weight=ft.FontWeight.BOLD),
            ], spacing=6))
            for ret in sale_returns:
                ret_date = _fmt_dt(ret.get("created_at", ""))
                ret_items = ret.get("items", [])
                returns_section.append(ft.Container(
                    bgcolor=WARNING + "11", border_radius=6,
                    border=ft.border.all(1, WARNING + "44"),
                    padding=ft.padding.all(8),
                    content=ft.Column(spacing=4, controls=[
                        ft.Row([
                            ft.Text(ret_date, size=11, color=ft.colors.WHITE54, expand=True),
                            ft.Text(f"Aprobó: {ret.get('supervisor','—')}",
                                    size=11, color=ft.colors.WHITE38),
                        ]),
                        *[
                            ft.Row([
                                ft.Text(f"↩ {it['product_name']}", size=12,
                                        color=ft.colors.WHITE70, expand=True),
                                ft.Text(f"{it['quantity']:.0f} ×", size=11,
                                        color=ft.colors.WHITE54),
                                ft.Text(f"-{currency}{it['subtotal']:.2f}",
                                        size=12, color=WARNING, width=80,
                                        text_align=ft.TextAlign.RIGHT),
                            ], spacing=6)
                            for it in ret_items
                        ],
                        ft.Row([
                            ft.Text(f"Motivo: {ret.get('reason','—')}",
                                    size=11, color=ft.colors.WHITE38, expand=True),
                            ft.Text(f"-{currency}{ret.get('total_returned',0):.2f}",
                                    size=13, color=WARNING, weight=ft.FontWeight.BOLD),
                        ]),
                    ]),
                ))
            returns_section.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=6,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                content=ft.Column(spacing=4, controls=[
                    ft.Row([
                        ft.Text("Total devuelto:", color=WARNING),
                        ft.Text(f"-{currency}{total_devuelto:.2f}",
                                color=WARNING, weight=ft.FontWeight.BOLD),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([
                        ft.Text("TOTAL NETO:", color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, size=13),
                        ft.Text(f"{currency}{total_neto:.2f}",
                                color=PRIMARY_LT, weight=ft.FontWeight.BOLD, size=15),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ]),
            ))

        # Sección de cancelación (si aplica)
        cancel_section = []
        if status == "cancelled" and sale.get("notes"):
            cancel_section.append(ft.Divider(color=ft.colors.WHITE12))
            cancel_section.append(ft.Container(
                bgcolor=ERROR + "11", border_radius=6,
                border=ft.border.all(1, ERROR + "44"),
                padding=ft.padding.all(8),
                content=ft.Row([
                    ft.Icon(ft.icons.CANCEL, color=ERROR, size=16),
                    ft.Text(sale.get("notes", ""), size=12, color=ft.colors.WHITE70, expand=True),
                ], spacing=8),
            ))

        def do_reprint(_):
            try:
                from services.printer import TicketPrinter
                tp = TicketPrinter(api.get_config_map())
                if not tp.enabled:
                    _snack("⚠ La impresión automática está deshabilitada (Configuración → Impresora y Cajón)", WARNING)
                elif tp.print_ticket(sale):
                    _snack("✅ Ticket enviado a impresora")
                else:
                    _snack(f"Error impresora: {tp.last_error}", ERROR)
            except Exception as ex:
                _snack(f"Error impresora: {ex}", ERROR)

        def do_pdf(_):
            try:
                from services.printer import TicketPrinter
                tp = TicketPrinter(api.get_config_map())
                path = tp.print_ticket_pdf(sale)
                if path:
                    _snack(f"✅ PDF guardado: {path}")
                else:
                    _snack("⚠ Instala fpdf2:  pip install fpdf2", WARNING)
            except Exception as ex:
                _snack(f"Error PDF: {ex}", ERROR)

        detail_dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Text(f"Venta {sale.get('folio','')}", weight=ft.FontWeight.BOLD, expand=True),
                ft.Container(
                    content=ft.Text(s_label, size=10, color=ft.colors.WHITE),
                    bgcolor=s_color + "55", border_radius=4,
                    padding=ft.padding.symmetric(2, 8),
                ),
            ], spacing=8),
            content=ft.Container(
                width=520,
                content=ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, controls=[
                    # Info general
                    ft.Container(
                        bgcolor=BG_SURFACE, border_radius=6,
                        padding=ft.padding.symmetric(horizontal=10, vertical=8),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.ACCESS_TIME, size=13, color=ft.colors.WHITE38),
                                ft.Text(created, size=12, color=ft.colors.WHITE70, expand=True),
                                ft.Text(f"• {method}", size=12, color=ft.colors.WHITE70),
                            ], spacing=6),
                            ft.Row([
                                ft.Icon(ft.icons.PERSON, size=13, color=ft.colors.WHITE38),
                                ft.Text(f"Cajero: {cashier}", size=12, color=ft.colors.WHITE70, expand=True),
                            ], spacing=6),
                            ft.Row([
                                ft.Icon(ft.icons.PERSON_OUTLINE, size=13, color=ft.colors.WHITE38),
                                ft.Text(f"Cliente: {sale.get('customer_name') or '—'}",
                                        size=12, color=ft.colors.WHITE70, expand=True),
                            ], spacing=6) if sale.get("customer_name") else ft.Container(),
                        ]),
                    ),
                    items_list,
                    ft.Divider(color=ft.colors.WHITE12),
                    ft.Row([ft.Text("Subtotal:", color=ft.colors.WHITE70),
                            ft.Text(f"{currency}{float(sale.get('subtotal',0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text(f"{tax_name}:", color=ft.colors.WHITE70),
                            ft.Text(f"{currency}{float(sale.get('tax_amount',0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Descuento:", color=ft.colors.WHITE70),
                            ft.Text(f"-{currency}{float(sale.get('discount_amount',0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN) if float(sale.get("discount_amount", 0)) else ft.Container(),
                    ft.Row([ft.Text(f"Comisión {method} ({float(sale.get('commission_pct',0) or 0):g}%):",
                                    color=ft.colors.WHITE70),
                            ft.Text(f"{'-' if float(sale.get('commission_amount',0) or 0) < 0 else '+'}"
                                    f"{currency}{abs(float(sale.get('commission_amount',0) or 0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN) if float(sale.get("commission_amount", 0) or 0) else ft.Container(),
                    ft.Row([ft.Text("TOTAL ORIGINAL:", color=ft.colors.WHITE,
                                   weight=ft.FontWeight.BOLD),
                            ft.Text(f"{currency}{total_original:.2f}",
                                    color=PRIMARY_LT, weight=ft.FontWeight.BOLD, size=16)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Pago recibido:", color=ft.colors.WHITE70),
                            ft.Text(f"{currency}{float(sale.get('payment_amount',0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Cambio:", color=ft.colors.WHITE70),
                            ft.Text(f"{currency}{float(sale.get('change_amount',0)):.2f}",
                                    color=ft.colors.WHITE)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(f"Notas: {sale.get('notes','—')}", size=11,
                            color=ft.colors.WHITE54) if sale.get("notes") and status != "cancelled" else ft.Container(),
                    *cancel_section,
                    *returns_section,
                ]),
            ),
            actions=[
                ft.ElevatedButton(
                    "Reimprimir", icon=ft.icons.PRINT,
                    on_click=do_reprint,
                    style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=ft.colors.WHITE,
                                          side=ft.BorderSide(1, ft.colors.WHITE24)),
                ),
                ft.ElevatedButton(
                    "PDF", icon=ft.icons.PICTURE_AS_PDF,
                    on_click=do_pdf,
                    style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=PRIMARY_LT,
                                          side=ft.BorderSide(1, PRIMARY)),
                ),
                ft.ElevatedButton(
                    "Devolución", icon=ft.icons.ASSIGNMENT_RETURN,
                    disabled=not is_returnable,
                    on_click=lambda _: (setattr(detail_dlg, "open", False) or page.update(),
                                        _open_return_dialog(sale)),
                    style=ft.ButtonStyle(
                        bgcolor=WARNING if is_returnable else BG_SURFACE,
                        color=ft.colors.BLACK if is_returnable else ft.colors.WHITE38,
                    ),
                ),
                ft.ElevatedButton(
                    "Cancelar venta", icon=ft.icons.CANCEL,
                    disabled=not is_cancellable,
                    on_click=lambda _: (setattr(detail_dlg, "open", False) or page.update(),
                                        _open_cancel_dialog(sale)),
                    style=ft.ButtonStyle(
                        bgcolor=ERROR if is_cancellable else BG_SURFACE,
                        color=ft.colors.WHITE if is_cancellable else ft.colors.WHITE38,
                    ),
                ),
                ft.TextButton("Cerrar",
                              on_click=lambda _: setattr(detail_dlg, "open", False) or page.update()),
            ],
        )
        page.dialog = detail_dlg
        detail_dlg.open = True
        page.update()

    # ── Carga inicial ───────────────────────────────────────────────────────────
    load_sales()

    # ── Layout ───────────────────────────────────────────────────────────────────
    return ft.Container(
        expand=True, bgcolor=BG_DARK,
        content=ft.Column(expand=True, spacing=0, controls=[
            ft.Container(
                bgcolor=BG_CARD,
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                content=ft.Row([
                    ft.Icon(ft.icons.RECEIPT_LONG, color=PRIMARY, size=26),
                    ft.Text("Ventas", size=20, weight=ft.FontWeight.BOLD,
                            color=ft.colors.WHITE, expand=True),
                    month_dd, year_dd,
                    ft.ElevatedButton(
                        "Filtrar", icon=ft.icons.FILTER_ALT,
                        on_click=load_sales,
                        style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                    ),
                    loading_icon_button(page, ft.icons.REFRESH, load_sales,
                                        icon_color=PRIMARY, tooltip="Actualizar"),
                ], spacing=10),
            ),
            ft.Container(
                bgcolor=BG_CARD,
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                content=ft.Column(spacing=6, controls=[
                    ft.Row([
                        search_field, status_dd, method_dd, cashier_dd,
                        amount_min_field, amount_max_field,
                        ft.IconButton(ft.icons.FILTER_ALT_OFF, icon_color=ft.colors.WHITE54,
                                      on_click=clear_filters, tooltip="Limpiar filtros"),
                    ], spacing=8),
                    results_count_text,
                ]),
            ),
            ft.Container(
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                content=ft.Row([
                    ft.Column(spacing=2, controls=[
                        summary_count,
                        summary_completed,
                    ]),
                    ft.Container(expand=True),
                    ft.Column(horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0, controls=[
                        ft.Text("Total", size=11, color=ft.colors.WHITE54),
                        summary_total,
                    ]),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(horizontal=16),
                content=ft.Column(expand=True, spacing=8, controls=[
                    loading_text,
                    ft.Container(expand=True, content=sales_list),
                ]),
            ),
        ]),
    )
