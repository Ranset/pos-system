"""
Vista de Gestión de Productos y Categorías
"""
import flet as ft
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


def products_view(page: ft.Page, app_state: dict):
    cfg = app_state.get("config", {})
    currency = cfg.get("fiscal.currency_symbol", "$")
    is_manager = api.is_manager()

    products_data: list = []
    categories_data: list = []

    # ── Tabla de productos ────────────────────────────────────────────────────
    products_table = ft.DataTable(
        expand=True,
        border=ft.border.all(1, ft.colors.WHITE12),
        border_radius=8,
        heading_row_color=BG_SURFACE,
        heading_row_height=44,
        data_row_min_height=48,
        show_checkbox_column=False,
        columns=[
            ft.DataColumn(ft.Text("Código",    color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Nombre",    color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Categoría", color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Precio",    color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Costo",     color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("IVA %",     color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Stock",     color=ft.colors.WHITE70, size=12), numeric=True),
            ft.DataColumn(ft.Text("Estado",    color=ft.colors.WHITE70, size=12)),
            ft.DataColumn(ft.Text("Acciones",  color=ft.colors.WHITE70, size=12)),
        ],
        rows=[],
    )

    status_text = ft.Text("", color=ft.colors.WHITE54, size=12)

    # ── Controles de filtro creados directamente (sin ft.Ref) ─────────────────
    search_field = ft.TextField(
        hint_text="Buscar por nombre o código...",
        prefix_icon=ft.icons.SEARCH,
        expand=True,
        bgcolor=BG_SURFACE,
        border_color=PRIMARY,
        color=ft.colors.WHITE,
        hint_style=ft.TextStyle(color=ft.colors.WHITE38),
    )

    cat_dropdown = ft.Dropdown(
        label="Categoría",
        value="all",
        width=180,
        options=[ft.dropdown.Option("all", "Todas")],
        color=ft.colors.WHITE,
        border_color=PRIMARY,
    )

    # Toggle para mostrar productos inactivos
    show_inactive_switch = ft.Switch(
        label="Ver inactivos",
        value=False,
        active_color=WARNING,
        label_style=ft.TextStyle(color=ft.colors.WHITE70, size=12),
    )

    def _show_snack(msg: str, color: str = SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    # ── Cargar datos ──────────────────────────────────────────────────────────

    def load_products(e=None):
        try:
            search = (search_field.value or "").strip() or None
            cat_id = None
            if cat_dropdown.value and cat_dropdown.value != "all":
                try:
                    cat_id = int(cat_dropdown.value)
                except Exception:
                    pass
            show_inactive = show_inactive_switch.value
            active_only   = not show_inactive
            nonlocal products_data
            products_data = api.get_products(
                search=search,
                category_id=cat_id,
                active_only=active_only,
            )
            _render_products()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def load_categories():
        nonlocal categories_data
        try:
            categories_data = api.get_categories()
            cat_dropdown.options = [ft.dropdown.Option("all", "Todas")] + [
                ft.dropdown.Option(str(c["id"]), c["name"]) for c in categories_data
            ]
            cat_dropdown.value = "all"
            page.update()
        except Exception:
            pass

    def _render_products():
        products_table.rows.clear()
        active_count   = sum(1 for p in products_data if p.get("is_active", True))
        inactive_count = len(products_data) - active_count

        for p in products_data:
            inv       = p.get("inventory") or {}
            stock     = inv.get("quantity", 0)
            min_s     = inv.get("min_stock", 5)
            cat       = p.get("category") or {}
            is_active = p.get("is_active", True)

            # Filas inactivas visualmente atenuadas
            row_color = ft.colors.TRANSPARENT if is_active else ft.colors.with_opacity(0.04, ft.colors.RED)

            stock_color = (
                ERROR   if stock <= 0   else
                WARNING if stock <= min_s else
                SUCCESS
            )
            # Si está inactivo el stock no importa visualmente
            if not is_active:
                stock_color = ft.colors.WHITE24

            def make_edit(prod):   return lambda _: open_product_dialog(prod)
            def make_toggle(prod): return lambda _: toggle_product(prod)
            def make_stock(prod):  return lambda _: open_stock_dialog(prod)
            def make_delete(prod): return lambda _: delete_product(prod)

            # Tooltip descriptivo en el toggle
            toggle_tooltip = "Desactivar producto" if is_active else "Reactivar producto"

            products_table.rows.append(
                ft.DataRow(
                    color=row_color,
                    cells=[
                        ft.DataCell(ft.Text(
                            p.get("code", ""), size=12, font_family="monospace",
                            color=ft.colors.WHITE70 if is_active else ft.colors.WHITE30,
                        )),
                        ft.DataCell(ft.Row(spacing=6, controls=[
                            ft.Text(
                                p.get("name", ""), size=13, expand=True,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                color=ft.colors.WHITE if is_active else ft.colors.WHITE38,
                                italic=not is_active,
                            ),
                            # Badge "INACTIVO" sólo cuando el filtro muestra ambos
                            ft.Container(
                                visible=not is_active,
                                content=ft.Text("INACTIVO", size=9, color=ft.colors.WHITE),
                                bgcolor=ERROR + "77",
                                border_radius=3,
                                padding=ft.padding.symmetric(2, 5),
                            ),
                        ])),
                        ft.DataCell(ft.Container(
                            content=ft.Text(cat.get("name", "—"), size=11,
                                            color=ft.colors.WHITE if is_active else ft.colors.WHITE38),
                            bgcolor=(cat.get("color", PRIMARY) + ("33" if is_active else "15")),
                            border_radius=4,
                            padding=ft.padding.symmetric(4, 6),
                        )),
                        ft.DataCell(ft.Text(
                            f"{currency}{float(p.get('price', 0)):.2f}", size=13,
                            color=PRIMARY_LT if is_active else ft.colors.WHITE30,
                        )),
                        ft.DataCell(ft.Text(
                            f"{currency}{float(p.get('cost', 0)):.2f}", size=12,
                            color=ft.colors.WHITE54 if is_active else ft.colors.WHITE24,
                        )),
                        ft.DataCell(ft.Text(
                            f"{float(p.get('tax_rate', 0)) * 100:.0f}%", size=12,
                            color=ft.colors.WHITE70 if is_active else ft.colors.WHITE24,
                        )),
                        ft.DataCell(ft.Text(
                            f"{stock:.0f}", size=13, color=stock_color,
                            weight=ft.FontWeight.BOLD,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text("Activo" if is_active else "Inactivo",
                                            size=11, color=ft.colors.WHITE),
                            bgcolor=SUCCESS + "55" if is_active else ERROR + "44",
                            border_radius=4,
                            padding=ft.padding.symmetric(3, 6),
                        )),
                        ft.DataCell(ft.Row(spacing=0, controls=[
                            ft.IconButton(
                                ft.icons.EDIT_OUTLINED, icon_color=PRIMARY_LT,
                                icon_size=18, on_click=make_edit(p),
                                tooltip="Editar", disabled=not is_manager,
                            ),
                            ft.IconButton(
                                ft.icons.INVENTORY_OUTLINED,
                                icon_color=WARNING if is_active else ft.colors.WHITE24,
                                icon_size=18, on_click=make_stock(p),
                                tooltip="Ajustar stock",
                                disabled=not is_manager or not is_active,
                                visible= False
                            ),
                            ft.IconButton(
                                ft.icons.TOGGLE_ON if is_active else ft.icons.TOGGLE_OFF,
                                icon_color=SUCCESS if is_active else ERROR,
                                icon_size=20, on_click=make_toggle(p),
                                tooltip=toggle_tooltip,
                                disabled=not is_manager,
                            ),
                            ft.IconButton(
                                ft.icons.DELETE_FOREVER,
                                icon_color=ft.colors.RED_700 if api.is_manager() else ft.colors.WHITE12,
                                icon_size=18, on_click=make_delete(p),
                                tooltip="Eliminar permanentemente",
                                disabled=not api.is_manager(),
                            ),
                        ])),
                    ],
                )
            )

        # Contador con desglose activos/inactivos
        if show_inactive_switch.value:
            status_text.value = (
                f"{len(products_data)} producto(s)  —  "
                f"✅ {active_count} activo(s)  •  ❌ {inactive_count} inactivo(s)"
            )
        else:
            status_text.value = f"{active_count} producto(s) activo(s)"
        page.update()

    # ── Diálogo Producto ──────────────────────────────────────────────────────

    def open_product_dialog(product: dict = None):
        is_edit = product is not None

        # Anchos fijos para que las filas con 2/3 campos quepan dentro del
        # Container(width=500) del diálogo (expand=True dentro de un Column
        # con scroll provoca que los campos colapsen).
        HALF_W  = 235   # 2 campos por fila: 235*2 + spacing(10) = 480
        THIRD_W = 153   # 3 campos por fila: 153*3 + spacing(10*2) = 479

        f_code  = ft.TextField(label="Código / Barcode *",
                               value=product.get("code", "") if is_edit else "",
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_name  = ft.TextField(label="Nombre *",
                               value=product.get("name", "") if is_edit else "",
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_desc  = ft.TextField(label="Descripción",
                               value=product.get("description", "") if is_edit else "",
                               multiline=True, min_lines=2, max_lines=3,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        f_price = ft.TextField(label="Precio venta *",
                               value=str(product.get("price", "0")) if is_edit else "",
                               prefix_text=currency, keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_cost  = ft.TextField(label="Precio costo",
                               value=str(product.get("cost", "0")) if is_edit else "",
                               prefix_text=currency, keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_tax   = ft.TextField(label="Tasa IVA (0.16 = 16%)",
                               value=str(product.get("tax_rate", "0")) if is_edit else "0",
                               keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_disc  = ft.TextField(label="Descuento máx (%)",
                               value=str(product.get("discount_max", "0")) if is_edit else "0",
                               keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               width=HALF_W)
        f_cat   = ft.Dropdown(
            label="Categoría",
            value=str(product.get("category_id", "0")) if is_edit and product.get("category_id") else "0",
            options=[ft.dropdown.Option("0", "Sin categoría")] +
                    [ft.dropdown.Option(str(c["id"]), c["name"]) for c in categories_data],
            color=ft.colors.WHITE, border_color=PRIMARY,
        )
        f_frac  = ft.Checkbox(label="Venta fraccionada",
                              value=product.get("allow_fractional", False) if is_edit else False)
        f_stock = ft.TextField(label="Stock inicial", value="0",
                               keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               visible=not is_edit, width=THIRD_W)
        f_min_s = ft.TextField(label="Stock mínimo", value="5",
                               keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               visible=not is_edit, width=THIRD_W)
        f_max_s = ft.TextField(label="Stock máximo", value="100",
                               keyboard_type=ft.KeyboardType.NUMBER,
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
                               visible=not is_edit, width=THIRD_W)
        err_text = ft.Text("", color=ERROR, size=12)

        def save(e):
            err_text.value = ""
            if not f_code.value.strip() or not f_name.value.strip() or not f_price.value.strip():
                err_text.value = "Código, nombre y precio son obligatorios"
                page.update()
                return
            try:
                # Convertir cat_id de forma segura: "0" y cualquier no-numérico → None
                try:
                    cat_id = int(f_cat.value)
                    if cat_id == 0:
                        cat_id = None
                except (ValueError, TypeError):
                    cat_id = None
                payload = {
                    "code": f_code.value.strip(),
                    "name": f_name.value.strip(),
                    "description": f_desc.value.strip() or None,
                    "price": float(f_price.value),
                    "cost": float(f_cost.value or 0),
                    "tax_rate": float(f_tax.value or 0),
                    "discount_max": float(f_disc.value or 0),
                    "category_id": cat_id,
                    "allow_fractional": f_frac.value,
                }
                if not is_edit:
                    payload["initial_stock"] = float(f_stock.value or 0)
                    payload["min_stock"] = float(f_min_s.value or 5)
                    payload["max_stock"] = float(f_max_s.value or 100)
                    api.create_product(payload)
                    _show_snack("✅ Producto creado")
                else:
                    api.update_product(product["id"], payload)
                    _show_snack("✅ Producto actualizado")
                dlg.open = False
                page.update()
                load_products()
            except APIError as ex:
                err_text.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar Producto" if is_edit else "Nuevo Producto",
                           weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=500,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=10,
                    controls=[
                        ft.Row([f_code, f_name], spacing=10),
                        f_desc,
                        ft.Row([f_price, f_cost], spacing=10),
                        ft.Row([f_tax, f_disc], spacing=10),
                        f_cat, f_frac,
                        ft.Row([f_stock, f_min_s, f_max_s], spacing=10) if not is_edit else ft.Container(),
                        err_text,
                    ],
                ),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Guardar", icon=ft.icons.SAVE, on_click=save,
                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ── Diálogo Ajuste de Stock ───────────────────────────────────────────────

    def open_stock_dialog(product: dict):
        inv = product.get("inventory") or {}
        current_qty = inv.get("quantity", 0)

        f_qty    = ft.TextField(label="Cantidad (+ entrada / - salida)", value="0",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        f_type   = ft.Dropdown(
            label="Tipo",
            value="adjustment",
            options=[
                ft.dropdown.Option("in", "Entrada"),
                ft.dropdown.Option("out", "Salida"),
                ft.dropdown.Option("adjustment", "Ajuste"),
            ],
            color=ft.colors.WHITE, border_color=PRIMARY,
        )
        f_reason = ft.TextField(label="Motivo *",
                                hint_text="Ej: Compra proveedor, merma, ajuste...",
                                color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        err_text = ft.Text("", color=ERROR, size=12)

        def save_stock(e):
            if not f_reason.value.strip():
                err_text.value = "El motivo es obligatorio"
                page.update()
                return
            try:
                qty = float(f_qty.value or 0)
                if f_type.value == "out":
                    qty = -abs(qty)
                elif f_type.value == "in":
                    qty = abs(qty)
                api.adjust_stock({
                    "product_id": product["id"],
                    "quantity": qty,
                    "reason": f_reason.value.strip(),
                    "movement_type": f_type.value,
                })
                dlg.open = False
                page.update()
                load_products()
                _show_snack(f"✅ Stock actualizado: {product.get('name', '')}")
            except APIError as ex:
                err_text.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Ajuste de Stock – {product.get('name', '')}"),
            content=ft.Column(spacing=10, controls=[
                ft.Text(f"Stock actual: {current_qty:.0f}", color=PRIMARY_LT, size=15),
                f_type, f_qty, f_reason, err_text,
            ]),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Guardar", on_click=save_stock,
                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def toggle_product(product: dict):
        try:
            api.update_product(product["id"], {"is_active": not product.get("is_active", True)})
            load_products()
        except APIError as ex:
            _show_snack(str(ex), ERROR)

    def delete_product(product: dict):
        """Elimina permanentemente un producto (soft delete en el backend).
        Preserva el historial de ventas — el producto queda como registro
        en las ventas anteriores pero desaparece del catálogo."""
        name      = product.get("name", "")
        is_active = product.get("is_active", True)

        def confirm(_):
            try:
                api.delete_product(product["id"])
                _show_snack(f"🗑  Producto '{name}' eliminado")
                load_products()
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.dialog.open = False
            page.update()

        warning_active = ft.Container(
            visible=is_active,
            bgcolor=WARNING + "22", border_radius=8,
            padding=ft.padding.all(10),
            content=ft.Row([
                ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color=WARNING, size=18),
                ft.Text(
                    "El producto está activo. Desactívalo primero si solo "
                    "quieres ocultarlo del catálogo sin eliminarlo.",
                    size=12, color=ft.colors.WHITE70, expand=True,
                ),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
        )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.DELETE_FOREVER, color=ERROR, size=22),
                ft.Text("Eliminar producto", weight=ft.FontWeight.BOLD, color=ERROR),
            ], spacing=8),
            content=ft.Container(
                width=420,
                content=ft.Column(spacing=12, controls=[
                    ft.Container(
                        bgcolor=ERROR + "1A", border_radius=8,
                        padding=ft.padding.all(12),
                        content=ft.Column(spacing=6, controls=[
                            ft.Row([
                                ft.Icon(ft.icons.INVENTORY_2, color=ft.colors.WHITE60, size=16),
                                ft.Text(name, size=14, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=6),
                            ft.Text(f"Código: {product.get('code','—')}",
                                    size=12, color=ft.colors.WHITE54),
                        ]),
                    ),
                    warning_active,
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
                                "• El producto desaparece del catálogo y del POS\n"
                                "• Las ventas anteriores conservan su registro histórico\n"
                                "• El inventario asociado se elimina\n"
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

    # ── Pestaña Categorías ────────────────────────────────────────────────────

    cats_list = ft.ListView(expand=True, spacing=6, padding=8)

    def load_cats_list():
        cats_list.controls.clear()
        for cat in categories_data:
            def make_edit_cat(c):  return lambda _: open_cat_dialog(c)
            def make_del_cat(c):   return lambda _: delete_category(c)
            cats_list.controls.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=8,
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                content=ft.Row([
                    ft.Container(width=18, height=18, border_radius=9,
                                 bgcolor=cat.get("color", PRIMARY)),
                    ft.Text(cat.get("name", ""), expand=True, size=14, color=ft.colors.WHITE),
                    ft.Text(cat.get("description", ""), expand=True, size=12, color=ft.colors.WHITE54),
                    ft.IconButton(ft.icons.EDIT_OUTLINED, icon_color=PRIMARY_LT, icon_size=18,
                                  on_click=make_edit_cat(cat)),
                    ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=ERROR, icon_size=18,
                                  on_click=make_del_cat(cat)),
                ], spacing=10),
            ))
        page.update()

    def open_cat_dialog(cat: dict = None):
        is_edit = cat is not None
        f_name  = ft.TextField(label="Nombre *",
                               value=cat.get("name", "") if is_edit else "",
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        f_desc  = ft.TextField(label="Descripción",
                               value=cat.get("description", "") if is_edit else "",
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        f_color = ft.TextField(label="Color (#hex)",
                               value=cat.get("color", "#1565C0") if is_edit else "#1565C0",
                               color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY)
        err_t   = ft.Text("", color=ERROR, size=12)

        def save_cat(e):
            if not f_name.value.strip():
                err_t.value = "El nombre es obligatorio"
                page.update()
                return
            try:
                d = {"name": f_name.value.strip(),
                     "description": f_desc.value or None,
                     "color": f_color.value}
                if is_edit:
                    api.update_category(cat["id"], d)
                    _show_snack("✅ Categoría actualizada")
                else:
                    api.create_category(d)
                    _show_snack("✅ Categoría creada")
                dlg.open = False
                page.update()
                nonlocal categories_data
                categories_data = api.get_categories()
                load_categories()
                load_cats_list()
            except APIError as ex:
                err_t.value = str(ex)
                page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Categoría", weight=ft.FontWeight.BOLD),
            content=ft.Column(spacing=10, controls=[f_name, f_desc, f_color, err_t]),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Guardar", on_click=save_cat,
                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def delete_category(cat: dict):
        def confirm(_):
            try:
                api.update_category(cat["id"], {"is_active": False})
                nonlocal categories_data
                categories_data = api.get_categories()
                load_categories()
                load_cats_list()
                _show_snack("Categoría eliminada")
            except APIError as ex:
                _show_snack(str(ex), ERROR)
            page.dialog.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Eliminar categoría"),
            content=ft.Text(f'¿Eliminar "{cat.get("name", "")}"?'),
            actions=[
                ft.TextButton("No",
                              on_click=lambda _: setattr(page.dialog, "open", False) or page.update()),
                ft.ElevatedButton("Sí, eliminar", on_click=confirm,
                                  style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ── Conectar eventos de filtros ───────────────────────────────────────────
    search_field.on_submit        = load_products
    cat_dropdown.on_change        = load_products
    show_inactive_switch.on_change = load_products

    # ── Carga inicial (sin Ref, accede a controles directos) ──────────────────
    load_categories()
    load_products()
    load_cats_list()

    # ── Layout ────────────────────────────────────────────────────────────────

    tabs = ft.Tabs(
        expand=True,
        selected_index=0,
        indicator_color=PRIMARY,
        label_color=PRIMARY_LT,
        unselected_label_color=ft.colors.WHITE54,
        tabs=[
            ft.Tab(
                text="Productos",
                icon=ft.icons.INVENTORY_2,
                content=ft.Column(
                    expand=True, spacing=8,
                    controls=[
                        ft.Container(
                            padding=ft.padding.only(top=12, left=12, right=12, bottom=4),
                            content=ft.Row(
                                controls=[
                                    search_field,
                                    cat_dropdown,
                                    show_inactive_switch,
                                    ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                                  on_click=load_products, tooltip="Actualizar"),
                                    ft.ElevatedButton(
                                        "Nuevo producto", icon=ft.icons.ADD,
                                        on_click=lambda _: open_product_dialog(),
                                        disabled=not is_manager,
                                        style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                                    ),
                                ],
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ),
                        status_text,
                        ft.Container(
                            expand=True,
                            padding=ft.padding.symmetric(horizontal=12),
                            content=ft.ListView(expand=True, controls=[products_table]),
                        ),
                    ],
                ),
            ),
            ft.Tab(
                text="Categorías",
                icon=ft.icons.CATEGORY,
                content=ft.Column(
                    expand=True, spacing=8,
                    controls=[
                        ft.Container(
                            padding=ft.padding.all(12),
                            content=ft.Row([
                                ft.Text("Categorías de productos", size=16, color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD, expand=True),
                                ft.ElevatedButton(
                                    "Nueva categoría", icon=ft.icons.ADD,
                                    on_click=lambda _: open_cat_dialog(),
                                    disabled=not is_manager,
                                    style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                                ),
                            ]),
                        ),
                        ft.Container(expand=True,
                                     padding=ft.padding.symmetric(horizontal=12),
                                     content=cats_list),
                    ],
                ),
            ),
        ],
    )

    return ft.Container(expand=True, bgcolor=BG_DARK, content=tabs)
