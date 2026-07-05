"""
Vista de Inventario – Control de stock y movimientos
"""
from datetime import datetime
import flet as ft
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError
from components import loading_icon_button


MOVEMENT_LABELS = {
    "in":         ("Entrada", SUCCESS, ft.icons.ARROW_DOWNWARD),
    "out":        ("Salida", ERROR, ft.icons.ARROW_UPWARD),
    "adjustment": ("Ajuste", WARNING, ft.icons.SYNC_ALT),
}


def _format_datetime(value: str) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return value


def inventory_view(page: ft.Page, app_state: dict):
    cfg = app_state.get("config", {})
    currency = cfg.get("fiscal.currency_symbol", "$")
    is_manager = api.is_manager()

    all_products: list = []
    low_stock_data: list = []

    # ── Tabla inventario ──────────────────────────────────────────────────────
    inv_table = ft.DataTable(
        expand=True,
        border=ft.border.all(1, ft.colors.WHITE12),
        border_radius=8,
        heading_row_color=BG_SURFACE,
        heading_row_height=44,
        data_row_min_height=46,
        columns=[
            ft.DataColumn(ft.Text("Código",       color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Producto",     color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Categoría",    color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Stock actual", color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Mín",          color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Máx",          color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Estado",       color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Historial",    color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Ajustar",      color=ft.colors.WHITE70, size=12)),
        ],
        rows=[],
    )

    alert_count = ft.Text("", color=WARNING, size=13, weight=ft.FontWeight.BOLD)
    status_text = ft.Text("", color=ft.colors.WHITE54, size=12)

    # ── Control de búsqueda directo (sin ft.Ref) ──────────────────────────────
    search_field = ft.TextField(
        hint_text="Buscar producto...",
        prefix_icon=ft.icons.SEARCH,
        expand=True,
        bgcolor=BG_SURFACE,
        border_color=PRIMARY,
        color=ft.colors.WHITE,
        hint_style=ft.TextStyle(color=ft.colors.WHITE38),
    )

    low_list = ft.ListView(expand=True, spacing=6, padding=8)

    def _show_snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    def load_inventory(e=None):
        try:
            search = (search_field.value or "").strip() or None
            nonlocal all_products
            all_products = api.get_products(search=search)
            _render_table(all_products)
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def load_low_stock():
        try:
            nonlocal low_stock_data
            low_stock_data = api.get_low_stock()
            alert_count.value = (
                f"⚠  {len(low_stock_data)} producto(s) con stock bajo"
                if low_stock_data else ""
            )
            page.update()
        except Exception:
            pass

    def _render_table(products: list):
        inv_table.rows.clear()
        for p in products:
            inv   = p.get("inventory") or {}
            stock = float(inv.get("quantity", 0))
            min_s = float(inv.get("min_stock", 5))
            max_s = float(inv.get("max_stock", 100))
            cat   = p.get("category") or {}

            if stock <= 0:
                status_label, status_bg = "Sin stock", ERROR + "55"
            elif stock <= min_s:
                status_label, status_bg = "Stock bajo", WARNING + "55"
            else:
                status_label, status_bg = "Normal", SUCCESS + "55"

            stock_color = ERROR if stock <= 0 else WARNING if stock <= min_s else SUCCESS

            def make_adj(prod): return lambda _: open_adjust_dialog(prod)
            def make_hist(prod): return lambda _: open_history_dialog(prod)

            inv_table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(p.get("code", ""), size=12,
                                    color=ft.colors.WHITE60, font_family="monospace")),
                ft.DataCell(ft.Text(p.get("name", ""), size=13, color=ft.colors.WHITE,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                ft.DataCell(ft.Text(cat.get("name", "—"), size=12, color=ft.colors.WHITE60)),
                ft.DataCell(ft.Text(f"{stock:.2f}", size=14, color=stock_color,
                                    weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(f"{min_s:.0f}", size=12, color=ft.colors.WHITE54)),
                ft.DataCell(ft.Text(f"{max_s:.0f}", size=12, color=ft.colors.WHITE54)),
                ft.DataCell(ft.Container(
                    content=ft.Text(status_label, size=11, color=ft.colors.WHITE),
                    bgcolor=status_bg, border_radius=4,
                    padding=ft.padding.symmetric(3, 8),
                )),
                ft.DataCell(ft.IconButton(
                    ft.icons.HISTORY, icon_color=PRIMARY_LT, icon_size=20,
                    on_click=make_hist(p), tooltip="Historial de movimientos",
                )),
                ft.DataCell(ft.IconButton(
                    ft.icons.TUNE, icon_color=PRIMARY_LT, icon_size=20,
                    on_click=make_adj(p), tooltip="Ajustar stock",
                    disabled=not is_manager,
                )),
            ]))
        status_text.value = f"{len(products)} producto(s)"
        page.update()

    # ── Diálogo ajuste de stock ───────────────────────────────────────────────

    def open_adjust_dialog(product: dict):
        inv   = product.get("inventory") or {}
        stock = float(inv.get("quantity", 0))

        f_type   = ft.Dropdown(
            label="Tipo de movimiento",
            value="in",
            options=[
                ft.dropdown.Option("in",         "➕ Entrada de mercancía"),
                ft.dropdown.Option("out",        "➖ Salida / Merma"),
                ft.dropdown.Option("adjustment", "🔄 Ajuste de inventario"),
            ],
            color=ft.colors.WHITE, border_color=PRIMARY,
        )
        f_qty    = ft.TextField(label="Cantidad", value="1",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        f_reason = ft.TextField(label="Motivo *",
                                hint_text="Ej: Compra, merma, ajuste anual...",
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        result_text = ft.Text("", color=ft.colors.WHITE70, size=13)
        err_text    = ft.Text("", color=ERROR, size=12)

        def preview(e=None):
            try:
                qty = float(f_qty.value or 0)
                t   = f_type.value
                if t == "in":
                    new_stock = stock + qty
                    result_text.value = f"Stock resultante: {new_stock:.2f} (+ {qty:.2f})"
                    result_text.color = SUCCESS
                elif t == "out":
                    new_stock = stock - qty
                    result_text.value = f"Stock resultante: {new_stock:.2f} (- {qty:.2f})"
                    result_text.color = WARNING if new_stock > 0 else ERROR
                else:
                    result_text.value = f"Nuevo stock: {qty:.2f}"
                    result_text.color = PRIMARY_LT
                page.update()
            except Exception:
                pass

        f_qty.on_change  = preview
        f_type.on_change = preview
        preview()

        def save(e):
            err_text.value = ""
            if not f_reason.value.strip():
                err_text.value = "El motivo es obligatorio"
                page.update()
                return
            try:
                qty = float(f_qty.value or 0)
                t   = f_type.value
                if t == "out":
                    qty = -abs(qty)
                elif t == "adjustment":
                    qty = qty - stock      # diferencia respecto al stock actual
                api.adjust_stock({
                    "product_id": product["id"],
                    "quantity":   qty,
                    "reason":     f_reason.value.strip(),
                    "movement_type": t,
                })
                dlg.open = False
                page.update()
                load_inventory()
                load_low_stock()
                render_low_stock()
                _show_snack(f"✅ Stock actualizado: {product.get('name', '')}")
            except APIError as ex:
                err_text.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Ajuste de Inventario – {product.get('name', '')}"),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Container(
                        bgcolor=BG_SURFACE, border_radius=8,
                        padding=ft.padding.all(12),
                        content=ft.Row([
                            ft.Icon(ft.icons.INVENTORY, color=PRIMARY),
                            ft.Column([
                                ft.Text("Stock actual", color=ft.colors.WHITE54, size=11),
                                ft.Text(f"{stock:.2f}", color=ft.colors.WHITE, size=22,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=2),
                        ], spacing=12),
                    ),
                    f_type, f_qty, result_text, f_reason, err_text,
                ],
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Guardar ajuste", icon=ft.icons.SAVE, on_click=save,
                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ── Diálogo historial de movimientos ──────────────────────────────────────

    def open_history_dialog(product: dict):
        history_list = ft.ListView(spacing=6, padding=4, height=400)
        loading = ft.Row([ft.ProgressRing(width=18, height=18, color=PRIMARY), ft.Text("Cargando...", color=ft.colors.WHITE54)], spacing=10)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Historial de movimientos – {product.get('name', '')}"),
            content=ft.Container(width=560, content=ft.Column([loading, history_list], tight=True, spacing=10)),
            actions=[
                ft.TextButton("Cerrar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

        try:
            movements = api.get_inventory_movements(product["id"])
        except APIError as ex:
            loading.controls = [ft.Text(str(ex), color=ERROR, size=13)]
            page.update()
            return

        loading.controls = []
        if not movements:
            history_list.controls.append(
                ft.Container(
                    alignment=ft.alignment.center,
                    padding=20,
                    content=ft.Text("Sin movimientos registrados", color=ft.colors.WHITE54),
                )
            )
        for m in movements:
            mtype = m.get("movement_type", "adjustment")
            label, color, icon = MOVEMENT_LABELS.get(mtype, ("Movimiento", PRIMARY_LT, ft.icons.SWAP_VERT))
            qty   = float(m.get("quantity", 0))
            prev  = float(m.get("previous_quantity", 0))
            new   = float(m.get("new_quantity", 0))
            reason = m.get("reason") or "Sin motivo especificado"
            user_name = m.get("user_name")

            causa = reason
            if user_name and mtype == "adjustment":
                causa = f"{reason} (por {user_name})"
            elif user_name and not (m.get("reference_id")):
                causa = f"{reason} (por {user_name})"

            history_list.controls.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=8,
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                border=ft.border.all(1, ft.colors.WHITE12),
                content=ft.Row([
                    ft.Icon(icon, color=color, size=18),
                    ft.Column([
                        ft.Text(causa, color=ft.colors.WHITE, size=13,
                                weight=ft.FontWeight.W_500),
                        ft.Text(
                            f"{_format_datetime(m.get('created_at'))}  ·  "
                            f"Stock: {prev:.2f} → {new:.2f}",
                            color=ft.colors.WHITE54, size=11,
                        ),
                    ], spacing=2, expand=True),
                    ft.Container(
                        content=ft.Text(
                            f"{'+' if mtype != 'out' else '-'}{qty:.2f}",
                            color=color, size=13, weight=ft.FontWeight.BOLD,
                        ),
                        bgcolor=color + "22", border_radius=4,
                        padding=ft.padding.symmetric(3, 8),
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))
        page.update()

    # ── Panel de alertas ──────────────────────────────────────────────────────

    def render_low_stock():
        low_list.controls.clear()
        if not low_stock_data:
            low_list.controls.append(
                ft.Container(
                    alignment=ft.alignment.center,
                    padding=40,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE, color=SUCCESS, size=48),
                            ft.Text("Sin alertas de stock", color=ft.colors.WHITE54),
                        ],
                    ),
                )
            )
        for item in low_stock_data:
            stock = float(item.get("quantity", 0))
            min_s = float(item.get("min_stock", 0))
            pct   = (stock / min_s * 100) if min_s > 0 else 0
            color = ERROR if stock <= 0 else WARNING

            low_list.controls.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=8,
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                border=ft.border.all(1, color + "55"),
                content=ft.Column(spacing=6, controls=[
                    ft.Row([
                        ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=color, size=18),
                        ft.Text(item.get("name", ""), color=ft.colors.WHITE, size=14,
                                weight=ft.FontWeight.W_500, expand=True),
                        ft.Text(f"Código: {item.get('code', '')}", color=ft.colors.WHITE54, size=11),
                    ]),
                    ft.ProgressBar(value=pct / 100, color=color, bgcolor=ft.colors.WHITE12, height=6),
                    ft.Row([
                        ft.Text(f"Stock: {stock:.0f}", color=color, size=13,
                                weight=ft.FontWeight.BOLD),
                        ft.Text(f"Mín: {min_s:.0f}", color=ft.colors.WHITE54, size=12),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ]),
            ))
        page.update()

    def refresh_all(e=None):
        load_inventory()
        load_low_stock()
        render_low_stock()

    # Conectar evento de búsqueda
    search_field.on_submit = load_inventory

    # Carga inicial (accede a controles directos, no Ref)
    load_inventory()
    load_low_stock()
    render_low_stock()

    # ── Tabs ──────────────────────────────────────────────────────────────────

    tabs = ft.Tabs(
        expand=True,
        selected_index=0,
        indicator_color=PRIMARY,
        label_color=PRIMARY_LT,
        unselected_label_color=ft.colors.WHITE54,
        tabs=[
            ft.Tab(
                text="Inventario",
                icon=ft.icons.WAREHOUSE,
                content=ft.Column(
                    expand=True, spacing=6,
                    controls=[
                        ft.Container(
                            padding=ft.padding.only(top=10, left=12, right=12, bottom=4),
                            content=ft.Row(controls=[
                                search_field,           # control directo
                                loading_icon_button(page, ft.icons.REFRESH, refresh_all,
                                                    icon_color=PRIMARY, tooltip="Actualizar"),
                            ], spacing=10),
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=12),
                            content=ft.Row([status_text, ft.Container(expand=True), alert_count]),
                        ),
                        ft.Container(
                            expand=True,
                            padding=ft.padding.symmetric(horizontal=12),
                            content=ft.ListView(expand=True, controls=[inv_table]),
                        ),
                    ],
                ),
            ),
            ft.Tab(
                text="Alertas",
                icon=ft.icons.NOTIFICATIONS_ACTIVE,
                content=ft.Column(
                    expand=True, spacing=6,
                    controls=[
                        ft.Container(
                            padding=ft.padding.only(top=10, left=12, right=12, bottom=4),
                            content=ft.Row([
                                ft.Text("Productos con stock bajo", size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.colors.WHITE, expand=True),
                                loading_icon_button(
                                    page, ft.icons.REFRESH,
                                    lambda _: [load_low_stock(), render_low_stock()],
                                    icon_color=PRIMARY, tooltip="Actualizar"),
                            ]),
                        ),
                        ft.Container(expand=True,
                                     padding=ft.padding.symmetric(horizontal=12),
                                     content=low_list),
                    ],
                ),
            ),
        ],
    )

    return ft.Container(expand=True, bgcolor=BG_DARK, content=tabs)
