"""
Vista POS – Flujo completo de venta
Estados: 'pos' → 'payment' → 'success'
"""
import flet as ft
from decimal import Decimal
from datetime import datetime, timezone
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_dt(utc_str: str, fmt: str = "%d/%m/%Y  %H:%M") -> str:
    """Convierte un timestamp UTC devuelto por la API a la hora local del sistema.

    El backend almacena `created_at` con `datetime.utcnow()` (naive UTC).
    Esta función lo parsea, añade tzinfo=UTC y convierte a la zona local
    con `.astimezone()`, que usa la configuración del sistema operativo.
    Compatible con Python 3.7+.
    """
    if not utc_str:
        return "—"
    try:
        # Quitar microsegundos y sufijo 'Z' si lo hubiera
        clean = utc_str.split(".")[0].replace("Z", "").replace("T", " ")
        dt_utc = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)   # marcar como UTC
        dt_local = dt_utc.astimezone()                  # convertir a local
        return dt_local.strftime(fmt)
    except Exception:
        # Fallback: mostrar crudo sin conversión
        return utc_str[:16].replace("T", " ")

def _dec(val) -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _safe_focus(field) -> None:
    """Intenta dar foco a un control de Flet.
    Silencia AssertionError si el control no está montado en la página,
    lo que puede ocurrir durante transiciones de pantalla."""
    try:
        field.focus()
    except (AssertionError, Exception):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Vista principal
# ─────────────────────────────────────────────────────────────────────────────

def pos_view(page: ft.Page, app_state: dict):
    cfg      = app_state.get("config", {})
    currency = cfg.get("fiscal.currency_symbol", "$")
    tax_name = cfg.get("fiscal.tax_name", "IVA")
    allow_neg = cfg.get("pos.allow_negative_stock", "false") == "true"
    allow_price_edit = cfg.get("pos.allow_price_edit", "false") == "true"
    max_disc_pct = float(cfg.get("pos.max_discount_pct", "10"))

    # ── Estado compartido ─────────────────────────────────────────────────────
    cart:      list = []   # {product, qty, unit_price, discount_pct}
    last_sale: dict = {}   # respuesta de la API tras completar la venta
    state = {"mode": "pos"}

    # Handler único para todos los modos del POS.
    # Se puebla en cada _build_*; el dispatcher global lo invoca según state["mode"].
    kb_callbacks: dict = {}

    # Debounce: ignora UN evento de teclado justo después de cada cambio de modo.
    # Evita que el keyup/repeat de la tecla que disparó la transición
    # ejecute acciones en el nuevo modo (ej: F12 va a cobrar Y luego confirma).
    _debounce = {"skip": False}

    def _pos_dispatcher(e: ft.KeyboardEvent):
        """Handler global del POS — NUNCA se reemplaza entre modos."""
        if not app_state.get("pos_active"):
            return
        if _debounce["skip"]:
            _debounce["skip"] = False
            return          # descarta el primer evento tras una transición
        handler = kb_callbacks.get(state["mode"])
        if handler:
            handler(e)

    # Contenedor raíz que hace el swap entre pantallas
    root = ft.Container(expand=True, bgcolor=BG_DARK)

    def _snack(msg: str, color: str = SUCCESS):
        page.snack_bar = ft.SnackBar(
            ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True
        )
        page.update()

    def _switch(mode: str):
        state["mode"] = mode
        _debounce["skip"] = True    # descarta el próximo evento de teclado
        if mode == "pos":
            root.content = _build_pos()
        elif mode == "payment":
            root.content = _build_payment()
        elif mode == "success":
            root.content = _build_success()
        # Siempre apuntar al dispatcher único — no al handler del modo
        page.on_keyboard_event = _pos_dispatcher
        page.update()

    # ─────────────────────────────────────────────────────────────────────────
    # ── PANTALLA POS ──────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _build_pos():
        # Invalidar el handler anterior mientras se reconstruye la pantalla.
        # Evita que _pos_dispatcher llame a un handler con controles ya desvinculados.
        kb_callbacks["pos"] = None
        # ── Controles de carrito ──────────────────────────────────────────────
        cart_list      = ft.ListView(expand=True, spacing=2,
                                     padding=ft.padding.symmetric(horizontal=6))
        subtotal_label = ft.Text("0.00",  size=16, color=ft.colors.WHITE70)
        tax_label      = ft.Text("0.00",  size=13, color=ft.colors.WHITE54)
        total_label    = ft.Text(f"{currency}0.00", size=26,
                                 weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        count_label    = ft.Text("0 artículo(s)", size=11, color=ft.colors.WHITE54)

        def calc_totals():
            sub = Decimal("0"); tax = Decimal("0")
            for ci in cart:
                price = _dec(ci["unit_price"]); qty = _dec(ci["qty"])
                disc  = _dec(ci["discount_pct"]) / 100
                line  = price * qty * (1 - disc)
                sub  += line
                tax  += line * _dec(ci["product"].get("tax_rate", 0))
            total = sub + tax
            subtotal_label.value = f"{float(sub):.2f}"
            tax_label.value      = f"{tax_name}: {currency}{float(tax):.2f}"
            total_label.value    = f"{currency}{float(total):.2f}"
            count_label.value    = f"{sum(ci['qty'] for ci in cart):.0f} artículo(s)"
            return sub, tax, total

        def rebuild_cart():
            cart_list.controls.clear()
            for idx, ci in enumerate(cart):
                p     = ci["product"]
                price = ci["unit_price"]
                qty   = ci["qty"]
                disc  = ci["discount_pct"]
                line  = price * qty * (1 - disc / 100)

                # ── Closures para cada índice ─────────────────────────────────
                def make_remove(i):
                    def rm(_): cart.pop(i); rebuild_cart()
                    return rm

                def make_delta(i, d):
                    def fn(_):
                        cart[i]["qty"] = max(1, cart[i]["qty"] + d)
                        rebuild_cart()
                    return fn

                def make_qty_confirm(i):
                    """Abre diálogo para editar cantidad exacta."""
                    def fn(_):
                        f = ft.TextField(
                            label="Nueva cantidad",
                            value=str(int(cart[i]["qty"])),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            color=ft.colors.WHITE, bgcolor=BG_SURFACE,
                            border_color=PRIMARY, width=200, autofocus=True,
                        )
                        err = ft.Text("", color=ERROR, size=11)
                        def save(e):
                            try:
                                v = float(f.value or 1)
                                if v <= 0: raise ValueError
                                cart[i]["qty"] = v
                                page.dialog.open = False
                                rebuild_cart()
                            except ValueError:
                                err.value = "Cantidad inválida"
                                page.update()
                        f.on_submit = save
                        dlg = ft.AlertDialog(
                            modal=True,
                            title=ft.Text(f"Cantidad: {cart[i]['product']['name'][:24]}"),
                            content=ft.Column([f, err], spacing=8, tight=True),
                            actions=[
                                ft.TextButton("Cancelar",
                                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                                ft.ElevatedButton("OK", on_click=save,
                                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
                            ],
                        )
                        page.dialog = dlg; dlg.open = True; page.update()
                    return fn

                def make_disc_confirm(i):
                    """Abre diálogo para editar descuento."""
                    def fn(_):
                        f = ft.TextField(
                            label=f"Descuento % (0 – {max_disc_pct:.0f})",
                            value=str(int(cart[i]["discount_pct"])),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            color=ft.colors.WHITE, bgcolor=BG_SURFACE,
                            border_color=WARNING, width=200, autofocus=True,
                            suffix_text="%",
                        )
                        err = ft.Text("", color=ERROR, size=11)
                        def save(e):
                            try:
                                v = float(f.value or 0)
                                v = max(0, min(v, max_disc_pct))
                                cart[i]["discount_pct"] = v
                                page.dialog.open = False
                                rebuild_cart()
                            except ValueError:
                                err.value = "Valor inválido"
                                page.update()
                        f.on_submit = save
                        dlg = ft.AlertDialog(
                            modal=True,
                            title=ft.Text(f"Descuento: {cart[i]['product']['name'][:24]}"),
                            content=ft.Column([f, err], spacing=8, tight=True),
                            actions=[
                                ft.TextButton("Cancelar",
                                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                                ft.ElevatedButton("OK", on_click=save,
                                                  style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
                            ],
                        )
                        page.dialog = dlg; dlg.open = True; page.update()
                    return fn

                def make_price_confirm(i):
                    """Abre diálogo para editar precio (si está habilitado)."""
                    def fn(_):
                        f = ft.TextField(
                            label="Precio unitario",
                            value=f"{cart[i]['unit_price']:.2f}",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            color=ft.colors.WHITE, bgcolor=BG_SURFACE,
                            border_color=PRIMARY_LT, width=200, autofocus=True,
                            prefix_text=currency,
                        )
                        err = ft.Text("", color=ERROR, size=11)
                        def save(e):
                            try:
                                v = float(f.value or 0)
                                if v <= 0: raise ValueError
                                cart[i]["unit_price"] = v
                                page.dialog.open = False
                                rebuild_cart()
                            except ValueError:
                                err.value = "Precio inválido"
                                page.update()
                        f.on_submit = save
                        dlg = ft.AlertDialog(
                            modal=True,
                            title=ft.Text(f"Precio: {cart[i]['product']['name'][:24]}"),
                            content=ft.Column([f, err], spacing=8, tight=True),
                            actions=[
                                ft.TextButton("Cancelar",
                                              on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                                ft.ElevatedButton("OK", on_click=save,
                                                  style=ft.ButtonStyle(bgcolor=PRIMARY_LT, color=ft.colors.BLACK)),
                            ],
                        )
                        page.dialog = dlg; dlg.open = True; page.update()
                    return fn

                # Etiqueta de precio (toca para editar si está habilitado)
                price_label = ft.TextButton(
                    f"{currency}{price:.2f}",
                    on_click=make_price_confirm(idx) if allow_price_edit else None,
                    style=ft.ButtonStyle(
                        color=PRIMARY_LT if allow_price_edit else ft.colors.WHITE70,
                        padding=ft.padding.all(0),
                    ),
                    tooltip="Toca para editar precio" if allow_price_edit else None,
                )

                # Badge de descuento (toca para editar)
                disc_badge = ft.TextButton(
                    f"-{disc:.0f}%" if disc > 0 else "Desc.",
                    on_click=make_disc_confirm(idx),
                    style=ft.ButtonStyle(
                        color=WARNING if disc > 0 else ft.colors.WHITE38,
                        bgcolor=WARNING + "22" if disc > 0 else ft.colors.TRANSPARENT,
                        padding=ft.padding.symmetric(0, 4),
                    ),
                    tooltip=f"Descuento: {disc:.0f}% — toca para editar",
                )

                # Botón de cantidad (toca para escribir cantidad exacta)
                qty_btn = ft.TextButton(
                    f"{qty:.0f}",
                    on_click=make_qty_confirm(idx),
                    style=ft.ButtonStyle(
                        color=ft.colors.WHITE,
                        bgcolor=BG_DARK,
                        shape=ft.RoundedRectangleBorder(radius=4),
                        padding=ft.padding.symmetric(0, 8),
                    ),
                    tooltip="Toca para escribir cantidad exacta",
                )

                cart_list.controls.append(ft.Container(
                    bgcolor=BG_SURFACE, border_radius=6,
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    content=ft.Column(spacing=3, controls=[
                        # Fila 1: nombre + precio + eliminar
                        ft.Row([
                            ft.Text(p.get("name", "")[:26], size=13,
                                    color=ft.colors.WHITE, weight=ft.FontWeight.W_500,
                                    expand=True, no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            price_label,
                            ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=ERROR,
                                          icon_size=16, on_click=make_remove(idx),
                                          tooltip="Quitar del carrito"),
                        ], spacing=2),
                        # Fila 2: -/qty/+ | descuento | subtotal
                        ft.Row([
                            ft.IconButton(ft.icons.REMOVE_CIRCLE_OUTLINE, icon_color=WARNING,
                                          icon_size=18, on_click=make_delta(idx, -1),
                                          tooltip="Reducir cantidad"),
                            qty_btn,
                            ft.IconButton(ft.icons.ADD_CIRCLE_OUTLINE, icon_color=SUCCESS,
                                          icon_size=18, on_click=make_delta(idx, 1),
                                          tooltip="Aumentar cantidad"),
                            disc_badge,
                            ft.Container(expand=True),
                            ft.Text(f"{currency}{line:.2f}", size=14,
                                    color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ]),
                ))

            calc_totals()
            page.update()

        def add_to_cart(product: dict, qty: float = 1.0):
            for ci in cart:
                if ci["product"]["id"] == product["id"]:
                    ci["qty"] += qty
                    rebuild_cart()
                    return
            inv   = product.get("inventory") or {}
            stock = inv.get("quantity", 9999)
            if not allow_neg and stock < qty:
                _snack(f"Stock insuficiente: {stock:.0f} disponible(s)", ERROR)
                return
            cart.append({
                "product":      product,
                "qty":          qty,
                "unit_price":   float(product.get("price", 0)),
                "discount_pct": 0.0,
            })
            rebuild_cart()

        # ── Buscador y grid de productos ──────────────────────────────────────
        search_field = ft.TextField(
            hint_text="Código de barras o nombre del producto...",
            prefix_icon=ft.icons.SEARCH,
            expand=True,
            border_color=PRIMARY, focused_border_color=PRIMARY_LT,
            color=ft.colors.WHITE, bgcolor=BG_SURFACE,
            hint_style=ft.TextStyle(color=ft.colors.WHITE38),
            autofocus=True,
        )
        product_grid = ft.GridView(
            expand=True, runs_count=4, max_extent=155,
            spacing=8, run_spacing=8, padding=8,
        )
        cat_row = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=6)

        def load_products(search=None, category_id=None):
            try:
                products = api.get_products(search=search, category_id=category_id)
                product_grid.controls.clear()
                for p in products[:40]:
                    inv   = p.get("inventory") or {}
                    stock = float(inv.get("quantity", 0))
                    no_stock = stock <= 0 and not allow_neg
                    cat   = p.get("category") or {}
                    cc    = cat.get("color", PRIMARY)

                    def make_click(prod):
                        return lambda _: add_to_cart(prod)

                    product_grid.controls.append(ft.Container(
                        bgcolor=BG_CARD if not no_stock else BG_SURFACE,
                        border_radius=10,
                        border=ft.border.all(1, cc if not no_stock else ft.colors.WHITE12),
                        padding=10, on_click=make_click(p) if not no_stock else None,
                        ink=not no_stock, tooltip=f"Stock: {stock:.0f}",
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
                            controls=[
                                ft.Container(width=34, height=34, border_radius=17,
                                             bgcolor=cc + "33", alignment=ft.alignment.center,
                                             content=ft.Icon(ft.icons.INVENTORY_2_OUTLINED,
                                                             color=cc, size=18)),
                                ft.Text(p.get("name","")[:22], size=11, text_align=ft.TextAlign.CENTER,
                                        max_lines=2, color=ft.colors.WHITE if not no_stock else ft.colors.WHITE38),
                                ft.Text(f"{currency}{float(p.get('price',0)):.2f}", size=13,
                                        color=PRIMARY_LT if not no_stock else ft.colors.WHITE24,
                                        weight=ft.FontWeight.BOLD),
                                ft.Text(f"Stock: {stock:.0f}", size=10,
                                        color=SUCCESS if stock > 5 else WARNING if stock > 0 else ERROR),
                            ],
                        ),
                    ))
                page.update()
            except APIError as ex:
                _snack(str(ex), ERROR)

        def load_categories():
            try:
                cats = api.get_categories()
                cat_row.controls.clear()
                cat_row.controls.append(
                    ft.TextButton("Todos", style=ft.ButtonStyle(color=ft.colors.WHITE),
                                  on_click=lambda _: load_products())
                )
                for cat in cats:
                    def mk(cid):
                        return lambda _: load_products(category_id=cid)
                    cat_row.controls.append(
                        ft.TextButton(cat.get("name",""),
                                      style=ft.ButtonStyle(color=cat.get("color", PRIMARY)),
                                      on_click=mk(cat["id"]))
                    )
                page.update()
            except Exception:
                pass

        def search_or_scan(e=None):
            term = (search_field.value or "").strip()
            if not term:
                load_products()
                _safe_focus(search_field)
                return
            try:
                p = api.get_product_by_barcode(term)
                add_to_cart(p)
                search_field.value = ""
                page.update()
            except APIError:
                load_products(search=term)
            finally:
                # Devolver el foco al campo de búsqueda siempre,
                # independientemente del resultado (código de barras, nombre, error)
                _safe_focus(search_field)

        search_field.on_submit = search_or_scan

        def clear_cart(e=None):
            def confirm(_):
                cart.clear(); rebuild_cart()
                page.dialog.open = False; page.update()
            dlg = ft.AlertDialog(
                title=ft.Text("Limpiar carrito"),
                content=ft.Text("¿Eliminar todos los artículos del carrito?"),
                actions=[
                    ft.TextButton("No", on_click=lambda _: setattr(page.dialog,"open",False) or page.update()),
                    ft.ElevatedButton("Sí, limpiar", on_click=confirm,
                                      style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
                ],
            )
            page.dialog = dlg; dlg.open = True; page.update()

        def _open_session_selector(on_selected=None):
            """Diálogo para que el gerente/admin elija qué caja usar en POS."""
            try:
                sessions = api.get_active_sessions()
            except Exception:
                sessions = []

            if not sessions:
                _snack("⚠ No hay cajas abiertas. Abre una sesión en el menú Caja.", WARNING)
                return

            def make_pick(s):
                def pick(_):
                    app_state["session_id"]   = s["id"]
                    app_state["session_info"] = {
                        "id":       s["id"],
                        "register": s["register"]["name"],
                        "cashier":  s["cashier"]["full_name"],
                    }
                    sel_dlg.open = False; page.update()
                    _snack(f"✅ Caja activa: {s['register']['name']} "
                           f"(Cajero: {s['cashier']['full_name']})")
                    if on_selected:
                        on_selected()
                return pick

            current_sid = app_state.get("session_id")
            rows = []
            for s in sessions:
                is_active = (s["id"] == current_sid)
                rows.append(ft.Container(
                    bgcolor=(PRIMARY + "22") if is_active else BG_SURFACE,
                    border_radius=8,
                    border=ft.border.all(2 if is_active else 1,
                                         PRIMARY if is_active else ft.colors.WHITE12),
                    padding=ft.padding.all(12),
                    content=ft.Row([
                        ft.Column(expand=True, spacing=2, controls=[
                            ft.Text(s["register"]["name"], size=14,
                                    color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Cajero: {s['cashier']['full_name']}",
                                    size=12, color=ft.colors.WHITE54),
                            ft.Text(f"Sesión #{s['id']} · Apertura: {_fmt_dt(s.get('opened_at',''))}",
                                    size=11, color=ft.colors.WHITE38),
                        ]),
                        ft.Container(
                            content=ft.Text("EN USO", size=10, color=PRIMARY_LT,
                                            weight=ft.FontWeight.BOLD),
                            bgcolor=PRIMARY + "33", border_radius=4,
                            padding=ft.padding.symmetric(3, 8),
                            visible=is_active,
                        ),
                        ft.ElevatedButton(
                            "Seleccionar", icon=ft.icons.POINT_OF_SALE,
                            disabled=is_active,
                            on_click=make_pick(s),
                            style=ft.ButtonStyle(
                                bgcolor=PRIMARY if not is_active else BG_SURFACE,
                                color=ft.colors.WHITE if not is_active else ft.colors.WHITE38,
                            ),
                        ),
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ))

            sel_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.icons.POINT_OF_SALE, color=PRIMARY),
                    ft.Text("Seleccionar caja para POS", weight=ft.FontWeight.BOLD),
                ], spacing=8),
                content=ft.Container(
                    width=520,
                    content=ft.Column(
                        spacing=8, scroll=ft.ScrollMode.AUTO,
                        controls=[
                            ft.Text("Elige qué caja usar para el Punto de Venta:",
                                    size=12, color=ft.colors.WHITE70),
                            *rows,
                        ],
                    ),
                ),
                actions=[
                    ft.TextButton("Cerrar",
                                  on_click=lambda _: setattr(sel_dlg,"open",False) or page.update()),
                ],
            )
            page.dialog = sel_dlg; sel_dlg.open = True; page.update()

        def go_to_payment(e=None):
            if state["mode"] != "pos":        # ya en cobro o éxito → ignorar
                return
            if not cart:
            #     _snack("El carrito está vacío", WARNING)
                return
            session_id = app_state.get("session_id")
            if cfg.get("pos.require_session","true") == "true" and not session_id:
                if api.is_manager():
                    # Gerente sin caja: mostrar selector en lugar de error
                    _open_session_selector(on_selected=lambda: _switch("payment"))
                else:
                    _snack("⚠  Debes abrir una caja antes de cobrar (menú Caja)", WARNING)
                return
            _switch("payment")

        # ── Historial de ventas con cancelación ──────────────────────────────

        def open_sales_history(e=None):
            """Modal con ventas recientes del turno, con opción de cancelar."""
            is_mgr = api.is_manager()
            loading_text = ft.Text("Cargando ventas...", color=ft.colors.WHITE54, italic=True)
            sales_list    = ft.ListView(expand=True, spacing=6, padding=ft.padding.all(4))

            STATUS_LABELS = {
                "completed": ("Completada", SUCCESS),
                "cancelled": ("Cancelada",  ERROR),
                "refunded":  ("Reembolsada", WARNING),
            }
            METHOD_LABELS = {
                "cash": "Efectivo", "card": "Tarjeta",
                "transfer": "Transferencia", "mixed": "Mixto",
            }

            def load_sales():
                loading_text.visible = True
                sales_list.controls.clear()
                page.update()
                try:
                    params = {}
                    sid = app_state.get("session_id")
                    if sid:
                        params["session_id"] = sid
                    all_sales = api.get_sales(params=params or None)

                    loading_text.visible = False
                    if not all_sales:
                        sales_list.controls.append(
                            ft.Container(
                                alignment=ft.alignment.center, padding=40,
                                content=ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Icon(ft.icons.RECEIPT_LONG, size=48, color=ft.colors.WHITE24),
                                        ft.Text("Sin ventas en este turno", color=ft.colors.WHITE54),
                                    ],
                                ),
                            )
                        )
                    else:
                        for sale in all_sales:
                            _add_sale_row(sale)
                    page.update()
                except APIError as ex:
                    loading_text.visible = False
                    loading_text.value = f"Error: {ex}"
                    loading_text.visible = True
                    page.update()

            def _add_sale_row(sale: dict):
                status   = sale.get("status", "completed")
                s_label, s_color = STATUS_LABELS.get(status, (status, ft.colors.WHITE54))
                folio    = sale.get("folio", "—")
                total    = float(sale.get("total", 0))
                items    = sale.get("items", [])
                method   = METHOD_LABELS.get(sale.get("payment_method", ""), "—")
                created  = _fmt_dt(sale.get("created_at", ""), "%d/%m/%Y  %H:%M")
                cashier  = (sale.get("cashier") or {}).get("full_name", "")
                is_done  = status == "completed"

                def make_cancel(s):
                    def fn(_):
                        _open_cancel_dialog(s)
                    return fn

                def make_detail(s):
                    def fn(_):
                        _open_detail_dialog(s)
                    return fn

                sales_list.controls.append(ft.Container(
                    bgcolor=BG_SURFACE if is_done else BG_DARK,
                    border_radius=8,
                    border=ft.border.all(1, (s_color + "44") if not is_done else ft.colors.WHITE12),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    content=ft.Row([
                        # Columna info
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
                        # Total
                        ft.Text(f"{currency}{total:.2f}", size=16,
                                color=PRIMARY_LT if is_done else ft.colors.WHITE38,
                                weight=ft.FontWeight.BOLD),
                        # Acciones
                        ft.Row(spacing=0, controls=[
                            ft.IconButton(ft.icons.RECEIPT_OUTLINED, icon_color=PRIMARY_LT,
                                          icon_size=18, on_click=make_detail(sale),
                                          tooltip="Ver detalle"),
                            ft.IconButton(
                                ft.icons.CANCEL_OUTLINED,
                                icon_color=ERROR if is_done and is_mgr else ft.colors.WHITE24,
                                icon_size=18,
                                on_click=make_cancel(sale) if is_done and is_mgr else None,
                                tooltip="Cancelar venta" if is_mgr else "Solo gerentes pueden cancelar",
                                disabled=not is_done or not is_mgr,
                                visible=False
                            ),
                        ]),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                ))

            def _open_supervisor_dialog(title: str, on_approved):
                """Diálogo reutilizable para aprobación de gerente/admin.
                on_approved(supervisor_id, supervisor_name) se llama si las creds son válidas."""
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
                                      on_click=lambda _: setattr(sup_dlg,"open",False) or page.update()),
                        ft.ElevatedButton("Verificar y aprobar", icon=ft.icons.VERIFIED_USER,
                                          on_click=verify,
                                          style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
                    ],
                )
                page.dialog = sup_dlg; sup_dlg.open = True; page.update()

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
                                      on_click=lambda _: setattr(cancel_dlg,"open",False) or page.update()),
                        ft.ElevatedButton("Continuar →",
                                          icon=ft.icons.ARROW_FORWARD,
                                          on_click=request_cancel,
                                          style=ft.ButtonStyle(bgcolor=ERROR, color=ft.colors.WHITE)),
                    ],
                )
                page.dialog = cancel_dlg; cancel_dlg.open = True; page.update()

            def _open_return_dialog(sale: dict):
                folio = sale.get('folio', '')
                items = sale.get("items", [])
                # Checkboxes y qty fields por artículo
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
                            ft.Text(it.get("product_name","")[:28], size=13,
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
                        # Abrir cajón si la devolución entrega efectivo físico
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
                                      on_click=lambda _: setattr(ret_dlg,"open",False) or page.update()),
                        ft.ElevatedButton("Continuar →",
                                          icon=ft.icons.ARROW_FORWARD,
                                          on_click=request_return,
                                          style=ft.ButtonStyle(bgcolor=WARNING, color=ft.colors.BLACK)),
                    ],
                )
                page.dialog = ret_dlg; ret_dlg.open = True; page.update()

            def _open_detail_dialog(sale: dict):
                status = sale.get("status", "completed")
                is_cancellable = status in ("completed", "partial_return")
                is_returnable  = status in ("completed", "partial_return")

                # Intentar cargar devoluciones de esta venta
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

                STATUS_LABELS = {
                    "completed":      ("Completada",      SUCCESS),
                    "cancelled":      ("Cancelada",        ERROR),
                    "partial_return": ("Dev. parcial",    WARNING),
                    "refunded":       ("Reembolsada",     WARNING),
                }
                s_label, s_color = STATUS_LABELS.get(status, (status, ft.colors.WHITE54))

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
                    # Total neto
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
                        width=500,
                        content=ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, controls=[
                            items_list,
                            ft.Divider(color=ft.colors.WHITE12),
                            ft.Row([ft.Text("Subtotal:", color=ft.colors.WHITE70),
                                    ft.Text(f"{currency}{float(sale.get('subtotal',0)):.2f}",
                                            color=ft.colors.WHITE)],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([ft.Text(f"{cfg.get('fiscal.tax_name','IVA')}:",
                                           color=ft.colors.WHITE70),
                                    ft.Text(f"{currency}{float(sale.get('tax_amount',0)):.2f}",
                                            color=ft.colors.WHITE)],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([ft.Text("TOTAL ORIGINAL:", color=ft.colors.WHITE,
                                           weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{currency}{total_original:.2f}",
                                            color=PRIMARY_LT, weight=ft.FontWeight.BOLD, size=16)],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([ft.Text("Cambio:", color=ft.colors.WHITE70),
                                    ft.Text(f"{currency}{float(sale.get('change_amount',0)):.2f}",
                                            color=ft.colors.WHITE)],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(f"Notas: {sale.get('notes','—')}", size=11,
                                    color=ft.colors.WHITE54) if sale.get("notes") else ft.Container(),
                            # Sección de devoluciones (dinámica)
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
                            on_click=lambda _: (setattr(detail_dlg,"open",False) or page.update(),
                                                _open_return_dialog(sale)),
                            style=ft.ButtonStyle(
                                bgcolor=WARNING if is_returnable else BG_SURFACE,
                                color=ft.colors.BLACK if is_returnable else ft.colors.WHITE38,
                            ),
                        ),
                        ft.ElevatedButton(
                            "Cancelar venta", icon=ft.icons.CANCEL,
                            disabled=not is_cancellable,
                            on_click=lambda _: (setattr(detail_dlg,"open",False) or page.update(),
                                                _open_cancel_dialog(sale)),
                            style=ft.ButtonStyle(
                                bgcolor=ERROR if is_cancellable else BG_SURFACE,
                                color=ft.colors.WHITE if is_cancellable else ft.colors.WHITE38,
                            ),
                        ),
                        ft.TextButton("Cerrar",
                                      on_click=lambda _: setattr(detail_dlg,"open",False) or page.update()),
                    ],
                )
                page.dialog = detail_dlg
                detail_dlg.open = True
                page.update()

            # ── Diálogo principal de historial ────────────────────────────────
            history_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.icons.RECEIPT_LONG, color=PRIMARY),
                    ft.Text("Ventas del turno", weight=ft.FontWeight.BOLD, expand=True),
                    ft.Container(
                        bgcolor=WARNING + "22", border_radius=6,
                        padding=ft.padding.symmetric(3, 8),
                        visible=not is_mgr,
                        content=ft.Text("Solo ver — cancelar requiere Gerente",
                                        size=10, color=WARNING),
                    ),
                ], spacing=8),
                content=ft.Container(
                    width=680, height=480,
                    content=ft.Column(expand=True, spacing=8, controls=[
                        loading_text,
                        ft.Container(expand=True, content=sales_list),
                    ]),
                ),
                actions=[
                    ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                  on_click=lambda _: load_sales(),
                                  tooltip="Recargar"),
                    ft.Container(expand=True),
                    ft.TextButton("Cerrar",
                                  on_click=lambda _: setattr(history_dlg,"open",False) or page.update()),
                ],
            )
            page.dialog = history_dlg
            history_dlg.open = True
            page.update()
            load_sales()

        load_categories()
        load_products()
        rebuild_cart()

        # Barra de info de sesión
        session_info = app_state.get("session_info") or {}
        session_badge = ft.Container()
        if session_info:
            session_badge = ft.Container(
                bgcolor=SUCCESS + "22", border_radius=6,
                padding=ft.padding.symmetric(3, 10),
                content=ft.Row([
                    ft.Icon(ft.icons.CIRCLE, color=SUCCESS, size=8),
                    ft.Text(f"Caja: {session_info.get('register','')}", size=11, color=SUCCESS),
                ], spacing=5),
            )

        # Botón "Cambiar caja" solo para gerentes/admins
        change_session_btn = ft.Container()
        if api.is_manager():
            change_session_btn = ft.IconButton(
                icon=ft.icons.SWAP_HORIZ,
                icon_color=PRIMARY_LT,
                tooltip="Cambiar caja activa en POS",
                on_click=lambda _: _open_session_selector(),
                visible= False
            )

        left = ft.Container(
            expand=3, bgcolor=BG_DARK,
            content=ft.Column(expand=True, spacing=0, controls=[
                ft.Container(bgcolor=BG_CARD,
                             padding=ft.padding.symmetric(horizontal=12, vertical=8),
                             content=ft.Row([
                                 search_field,
                                 ft.IconButton(ft.icons.QR_CODE_SCANNER, icon_color=PRIMARY,
                                               on_click=search_or_scan, tooltip="Escanear / Buscar"),
                                 ft.IconButton(ft.icons.REFRESH, icon_color=ft.colors.WHITE38,
                                               on_click=lambda _: load_products(),
                                               tooltip="Recargar catálogo de productos"),
                                 session_badge,
                                 change_session_btn,
                             ])),
                ft.Container(bgcolor=BG_CARD,
                             padding=ft.padding.symmetric(horizontal=8, vertical=4),
                             content=cat_row),
                ft.Container(expand=True, padding=4, content=product_grid),
            ]),
        )

        # ── Panel derecho usando Stack con posicionamiento absoluto ─────────────
        # Esto garantiza visibilidad del carrito, totales y COBRAR independiente
        # del sistema de expand de Flet/Flutter.
        HEADER_H  = 56    # px — cabecera "Carrito"
        TOTALS_H  = 108   # px — subtotal + iva + total
        BUTTONS_H = 134   # px — botón COBRAR + limpiar/actualizar
        BOTTOM_H  = TOTALS_H + BUTTONS_H   # sección inferior total

        right = ft.Container(
            expand=1,
            bgcolor=BG_CARD,
            content=ft.Stack(
                expand=True,
                controls=[
                    # ── 1. Cabecera del carrito (top) ─────────────────────────
                    ft.Container(
                        top=0, left=0, right=0, height=HEADER_H,
                        bgcolor=PRIMARY,
                        padding=ft.padding.symmetric(horizontal=16, vertical=10),
                        content=ft.Row([
                            ft.Row([
                                ft.Icon(ft.icons.SHOPPING_CART, color=ft.colors.WHITE),
                                ft.Text("Carrito", color=ft.colors.WHITE, size=16,
                                        weight=ft.FontWeight.BOLD),
                            ], spacing=8),
                            count_label,
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ),
                    # ── 2. Lista del carrito (middle — scroll) ────────────────
                    ft.Container(
                        top=HEADER_H, bottom=BOTTOM_H, left=0, right=0,
                        content=cart_list,
                    ),
                    # ── 3. Totales (sobre los botones) ────────────────────────
                    ft.Container(
                        bottom=BUTTONS_H, left=0, right=0, height=TOTALS_H,
                        bgcolor=BG_SURFACE,
                        padding=ft.padding.symmetric(horizontal=16, vertical=10),
                        content=ft.Column(spacing=4, controls=[
                            ft.Row([
                                ft.Text("Subtotal:", color=ft.colors.WHITE70, size=13),
                                subtotal_label,
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([tax_label], alignment=ft.MainAxisAlignment.END),
                            ft.Divider(color=ft.colors.WHITE24),
                            ft.Row([
                                ft.Text("TOTAL", color=ft.colors.WHITE, size=18,
                                        weight=ft.FontWeight.BOLD),
                                total_label,
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ]),
                    ),
                    # ── 4. Botones de acción (bottom) ─────────────────────────
                    ft.Container(
                        bottom=0, left=0, right=0, height=BUTTONS_H,
                        bgcolor=BG_CARD,
                        padding=ft.padding.symmetric(horizontal=12, vertical=10),
                        content=ft.Column(spacing=8, controls=[
                            ft.ElevatedButton(
                                "COBRAR", icon=ft.icons.POINT_OF_SALE,
                                expand=True, height=56,
                                on_click=go_to_payment,
                                style=ft.ButtonStyle(
                                    bgcolor=SUCCESS, color=ft.colors.WHITE,
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                            ),
                            ft.Row(spacing=8, controls=[
                                ft.OutlinedButton(
                                    "Limpiar", icon=ft.icons.DELETE_SWEEP,
                                    expand=True, height=36, on_click=clear_cart,
                                    style=ft.ButtonStyle(
                                        color=ERROR, side=ft.BorderSide(1, ERROR),
                                    ),
                                ),
                                ft.OutlinedButton(
                                    "Historial", icon=ft.icons.RECEIPT_LONG,
                                    expand=True, height=36,
                                    on_click=open_sales_history,
                                    style=ft.ButtonStyle(
                                        color=WARNING, side=ft.BorderSide(1, WARNING),
                                    ),
                                ),
                            ]),
                        ]),
                    ),
                ],
            ),
        )

        # ── Hotkeys pantalla POS (leídos desde configuración) ────────────────
        def _pos_keyboard(e: ft.KeyboardEvent):
            if not app_state.get("pos_active") or state["mode"] != "pos":
                return                      # ignorar si no es la vista/modo activo
            c = app_state.get("config", {})
            k = e.key
            if k == c.get("hotkey.pos.cobrar", "F12"):
                go_to_payment()
            elif k == c.get("hotkey.pos.refresh", "F5"):
                load_products()
                _safe_focus(search_field)
            elif k == c.get("hotkey.pos.clear_search", "Escape") and not e.ctrl:
                if search_field.value:
                    search_field.value = ""
                    load_products()
                _safe_focus(search_field)

        kb_callbacks["pos"] = _pos_keyboard

        return ft.Row(
            expand=True, spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[left, right],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ── PANTALLA DE COBRO ─────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _build_payment():
        kb_callbacks["payment"] = None  # invalidar handler anterior durante rebuild
        # Recalcular totales desde el carrito actual
        sub = Decimal("0"); tax = Decimal("0")
        for ci in cart:
            price = _dec(ci["unit_price"]); qty = _dec(ci["qty"])
            disc  = _dec(ci["discount_pct"]) / 100
            line  = price * qty * (1 - disc)
            sub  += line
            tax  += line * _dec(ci["product"].get("tax_rate", 0))
        total_val = sub + tax

        # ── Estado del cobro ──────────────────────────────────────────────────
        pay_state = {
            "method":    "cash",   # cash | card | transfer | mixed
            "amount_str": "",      # lo que va escribiendo el cajero
            "cash_amount": Decimal("0"),
            "card_amount": Decimal("0"),
        }

        # ── Controles de datos del cliente ────────────────────────────────────
        f_customer = ft.TextField(
            label="Nombre del cliente (opcional)",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
            prefix_icon=ft.icons.PERSON_OUTLINE,
        )
        f_tax_id = ft.TextField(
            label="RFC / NIT (opcional)",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
            prefix_icon=ft.icons.BADGE_OUTLINED,
        )
        f_discount = ft.TextField(
            label="Descuento adicional", value="0",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=WARNING,
            prefix_text=currency, keyboard_type=ft.KeyboardType.NUMBER,
            suffix_text="en total",
            width=160,
        )
        f_notes = ft.TextField(
            label="Notas de la venta (opcional)", color=ft.colors.WHITE,
            bgcolor=BG_SURFACE, border_color=PRIMARY, multiline=True, min_lines=1, max_lines=2,
        )

        # ── Display del monto cobrado y cambio ────────────────────────────────
        amount_display = ft.Text("$0.00", size=36, weight=ft.FontWeight.BOLD,
                                 color=PRIMARY_LT, text_align=ft.TextAlign.CENTER)
        change_display = ft.Text("Cambio: $0.00", size=22, weight=ft.FontWeight.BOLD,
                                 color=SUCCESS, text_align=ft.TextAlign.CENTER)
        total_display  = ft.Text(f"TOTAL  {currency}{float(total_val):.2f}",
                                 size=20, weight=ft.FontWeight.BOLD,
                                 color=ft.colors.WHITE, text_align=ft.TextAlign.CENTER)

        # Para pago mixto
        f_card_amount = ft.TextField(
            label="Monto con tarjeta",
            value="0.00", width=160,
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY,
            prefix_text=currency, keyboard_type=ft.KeyboardType.NUMBER,
            visible=False,
        )

        # Campo de referencia para Tarjeta / Transferencia
        f_reference = ft.TextField(
            label="Referencia / N° de aprobación",
            hint_text="Ej: 123456, auth-ABC...",
            color=ft.colors.WHITE, bgcolor=BG_SURFACE, border_color=PRIMARY_LT,
            prefix_icon=ft.icons.TAG,
            visible=False,
        )

        confirm_btn = ft.ElevatedButton(
            "CONFIRMAR VENTA", icon=ft.icons.CHECK_CIRCLE,
            expand=True, height=60,
            style=ft.ButtonStyle(bgcolor=SUCCESS, color=ft.colors.WHITE,
                                 shape=ft.RoundedRectangleBorder(radius=10)),
        )
        loading_ring = ft.ProgressRing(visible=False, width=24, height=24, color=SUCCESS)

        def _get_total_with_discount() -> Decimal:
            try:
                disc = _dec(f_discount.value or "0")
            except Exception:
                disc = Decimal("0")
            return max(total_val - disc, Decimal("0"))

        def _update_change():
            total_d = _get_total_with_discount()
            method  = pay_state["method"]
            if method == "cash":
                try:
                    paid = _dec(pay_state["amount_str"] or "0")
                except Exception:
                    paid = Decimal("0")
                pay_state["cash_amount"] = paid
                change = paid - total_d
                amount_display.value = f"{currency}{float(paid):.2f}"
                if paid == 0:
                    change_display.value = f"Monto recibido: {currency}0.00"
                    change_display.color = ft.colors.WHITE54
                elif change >= 0:
                    change_display.value = f"✅  Cambio: {currency}{float(change):.2f}"
                    change_display.color = SUCCESS
                else:
                    change_display.value = f"Faltan: {currency}{float(-change):.2f}"
                    change_display.color = ERROR

            elif method in ("card", "transfer"):
                amount_display.value = f"{currency}{float(total_d):.2f}"
                label = "tarjeta" if method == "card" else "transferencia"
                ref   = f_reference.value.strip()
                if ref:
                    change_display.value = f"Ref: {ref}"
                    change_display.color = PRIMARY_LT
                else:
                    change_display.value = f"Pago exacto con {label}"
                    change_display.color = PRIMARY_LT

            elif method == "mixed":
                # El monto con tarjeta se ingresa; el efectivo = total - tarjeta
                try:
                    card_a = _dec(f_card_amount.value or "0")
                except Exception:
                    card_a = Decimal("0")

                if card_a > total_d:
                    # Tarjeta supera el total
                    pay_state["card_amount"] = total_d
                    pay_state["cash_amount"] = Decimal("0")
                    amount_display.value = f"{currency}{float(total_d):.2f}"
                    change_display.value = "⚠  Tarjeta supera el total"
                    change_display.color = WARNING
                else:
                    # Efectivo requerido = resto después de tarjeta
                    cash_needed = total_d - card_a
                    pay_state["card_amount"] = card_a
                    pay_state["cash_amount"] = cash_needed
                    # Auto-llenar numpad con el efectivo requerido
                    pay_state["amount_str"] = f"{float(cash_needed):.2f}"
                    amount_display.value = f"{currency}{float(total_d):.2f}"
                    if cash_needed == 0:
                        change_display.value = "✅  Pago completo con tarjeta"
                        change_display.color = SUCCESS
                    else:
                        change_display.value = (
                            f"💵 Cobrar en efectivo: {currency}{float(cash_needed):.2f}"
                        )
                        change_display.color = PRIMARY_LT
            page.update()

        f_discount.on_change    = lambda _: _update_change()
        f_reference.on_change   = lambda _: _update_change()
        f_card_amount.on_change = lambda _: _update_change()

        # ── Numpad ────────────────────────────────────────────────────────────
        def digit(d):
            s = pay_state["amount_str"]
            if d == "." and "." in s:
                return
            # Máximo 2 decimales
            if "." in s and len(s.split(".")[1]) >= 2:
                return
            pay_state["amount_str"] = s + d
            _update_change()

        def backspace():
            pay_state["amount_str"] = pay_state["amount_str"][:-1]
            _update_change()

        def clear_amount():
            pay_state["amount_str"] = ""
            _update_change()

        def exact_amount():
            total_d = _get_total_with_discount()
            pay_state["amount_str"] = f"{float(total_d):.2f}"
            _update_change()

        def _numpad_btn(label, on_click, bgcolor=BG_SURFACE, text_color=ft.colors.WHITE, width=None):
            return ft.ElevatedButton(
                content=ft.Text(label, size=20, weight=ft.FontWeight.W_600, color=text_color),
                height=58, width=width, expand=width is None,
                on_click=lambda _: on_click(),
                style=ft.ButtonStyle(
                    bgcolor=bgcolor,
                    color=text_color,
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
            )

        numpad = ft.Column(spacing=4, controls=[
            ft.Row(spacing=4, controls=[
                _numpad_btn("7", lambda: digit("7")),
                _numpad_btn("8", lambda: digit("8")),
                _numpad_btn("9", lambda: digit("9")),
            ]),
            ft.Row(spacing=4, controls=[
                _numpad_btn("4", lambda: digit("4")),
                _numpad_btn("5", lambda: digit("5")),
                _numpad_btn("6", lambda: digit("6")),
            ]),
            ft.Row(spacing=4, controls=[
                _numpad_btn("1", lambda: digit("1")),
                _numpad_btn("2", lambda: digit("2")),
                _numpad_btn("3", lambda: digit("3")),
            ]),
            ft.Row(spacing=4, controls=[
                _numpad_btn(".", lambda: digit("."), bgcolor=BG_CARD),
                _numpad_btn("0", lambda: digit("0")),
                _numpad_btn("⌫", backspace, bgcolor=WARNING + "88", text_color=ft.colors.WHITE),
            ]),
            ft.Row(spacing=4, controls=[
                _numpad_btn("EXACTO", exact_amount,
                            bgcolor=PRIMARY + "88", text_color=ft.colors.WHITE),
                _numpad_btn("🗑 BORRAR", clear_amount,
                            bgcolor=ERROR + "66", text_color=ft.colors.WHITE),
            ]),
        ])

        # ── Selector de método de pago ────────────────────────────────────────
        method_buttons: dict = {}
        numpad_container   = ft.Container()
        mixed_card_row     = ft.Container()
        reference_row      = ft.Container()   # campo de referencia tarjeta/transferencia

        def _set_method(m: str):
            pay_state["method"] = m
            pay_state["amount_str"] = ""
            for k, btn in method_buttons.items():
                btn.style = ft.ButtonStyle(
                    bgcolor=PRIMARY if k == m else BG_SURFACE,
                    color=ft.colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=8),
                )
            # Mostrar numpad solo para efectivo (en mixto el efectivo se calcula automáticamente)
            numpad_container.content = numpad if m == "cash" else ft.Container(height=4)
            # Campo tarjeta (solo mixto)
            mixed_card_row.content  = f_card_amount if m == "mixed" else ft.Container()
            f_card_amount.visible   = m == "mixed"
            if m == "mixed":
                f_card_amount.value = "0.00"
            # Campo referencia (tarjeta o transferencia)
            reference_row.content   = f_reference if m in ("card", "transfer") else ft.Container()
            f_reference.visible     = m in ("card", "transfer")
            f_reference.value       = ""
            f_reference.label       = ("N° de aprobación / referencia de tarjeta"
                                       if m == "card" else
                                       "Referencia de transferencia (CLABE, folio...)")
            _update_change()

        for mid, mlabel, micon in [
            ("cash",     "Efectivo",       ft.icons.PAYMENTS),
            ("card",     "Tarjeta",        ft.icons.CREDIT_CARD),
            ("transfer", "Transferencia",  ft.icons.ACCOUNT_BALANCE),
            ("mixed",    "Mixto",          ft.icons.COMPARE_ARROWS),
        ]:
            btn = ft.ElevatedButton(
                mlabel, icon=micon, expand=True, height=46,
                style=ft.ButtonStyle(
                    bgcolor=PRIMARY if mid == "cash" else BG_SURFACE,
                    color=ft.colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=8),
                ),
            )
            def make_set(m): return lambda _: _set_method(m)
            btn.on_click = make_set(mid)
            method_buttons[mid] = btn

        # Init
        numpad_container.content = numpad
        _update_change()

        # ── Resumen del pedido (columna izquierda) ────────────────────────────
        order_items = ft.ListView(spacing=4, height=220)
        for ci in cart:
            p    = ci["product"]
            qty  = ci["qty"]
            disc = ci["discount_pct"]
            line = ci["unit_price"] * qty * (1 - disc / 100)
            order_items.controls.append(ft.Container(
                bgcolor=BG_SURFACE, border_radius=6,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                content=ft.Row([
                    ft.Column(expand=True, spacing=2, controls=[
                        ft.Text(p.get("name","")[:32], size=13, color=ft.colors.WHITE),
                        ft.Text(
                            f"{currency}{ci['unit_price']:.2f} × {qty:.0f}" +
                            (f"  –{disc:.0f}%" if disc else ""),
                            size=11, color=ft.colors.WHITE54,
                        ),
                    ]),
                    ft.Text(f"{currency}{line:.2f}", size=13,
                            color=PRIMARY_LT, weight=ft.FontWeight.BOLD),
                ]),
            ))

        disc_raw = Decimal("0")
        try: disc_raw = _dec(f_discount.value or "0")
        except Exception: pass

        summary_col = ft.Container(
            expand=True, bgcolor=BG_CARD, border_radius=12,
            padding=ft.padding.all(16),
            content=ft.Column(expand=True, spacing=10, scroll=ft.ScrollMode.AUTO, controls=[
                ft.Text("📋 Resumen del pedido", size=15, weight=ft.FontWeight.BOLD,
                        color=ft.colors.WHITE),
                ft.Divider(color=ft.colors.WHITE12),
                order_items,
                ft.Divider(color=ft.colors.WHITE12),
                ft.Row([ft.Text("Subtotal:", color=ft.colors.WHITE70),
                        ft.Text(f"{currency}{float(sub):.2f}", color=ft.colors.WHITE)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text(f"{tax_name}:", color=ft.colors.WHITE70),
                        ft.Text(f"{currency}{float(tax):.2f}", color=ft.colors.WHITE)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("TOTAL:", color=ft.colors.WHITE, weight=ft.FontWeight.BOLD, size=16),
                        ft.Text(f"{currency}{float(total_val):.2f}", color=PRIMARY_LT,
                                weight=ft.FontWeight.BOLD, size=16)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(color=ft.colors.WHITE12),
                ft.Text("👤 Datos del cliente", size=13, weight=ft.FontWeight.W_600,
                        color=ft.colors.WHITE70),
                f_customer, f_tax_id,
                ft.Row([f_discount, ft.Container(expand=True)]),
                f_notes,
            ]),
        )

        # ── Columna de cobro (derecha) ────────────────────────────────────────
        payment_col = ft.Container(
            width=340, bgcolor=BG_CARD, border_radius=12,
            padding=ft.padding.all(16),
            content=ft.Column(spacing=10, controls=[
                ft.Text("💳 Método de pago", size=15, weight=ft.FontWeight.BOLD,
                        color=ft.colors.WHITE),
                ft.Row([method_buttons["cash"], method_buttons["card"]], spacing=6),
                ft.Row([method_buttons["transfer"], method_buttons["mixed"]], spacing=6),
                ft.Divider(color=ft.colors.WHITE12),
                total_display,
                ft.Container(height=4),
                ft.Container(
                    bgcolor=BG_DARK, border_radius=10,
                    padding=ft.padding.symmetric(horizontal=16, vertical=12),
                    alignment=ft.alignment.center,
                    content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                      spacing=6, controls=[
                        ft.Text("MONTO RECIBIDO", size=11, color=ft.colors.WHITE54),
                        amount_display,
                        mixed_card_row,
                        reference_row,
                        ft.Divider(color=ft.colors.WHITE12, height=1),
                        change_display,
                    ]),
                ),
                numpad_container,
                ft.Row([loading_ring], alignment=ft.MainAxisAlignment.CENTER),
                confirm_btn,
            ]),
        )

        # ── Acción: confirmar venta ───────────────────────────────────────────
        def confirm_sale(e):
            total_d = _get_total_with_discount()
            method  = pay_state["method"]
            discount_amount = max(total_val - total_d, Decimal("0"))

            # Validar monto
            if method == "cash":
                paid = _dec(pay_state["amount_str"] or "0")
                if paid < total_d:
                    _snack("El monto recibido es menor al total", ERROR)
                    return
                cash_a = paid; card_a = Decimal("0")
                change = paid - total_d
                pay_total = paid
            elif method == "card":
                cash_a = Decimal("0"); card_a = total_d
                change = Decimal("0"); pay_total = total_d
            elif method == "transfer":
                cash_a = Decimal("0"); card_a = Decimal("0")
                change = Decimal("0"); pay_total = total_d
            elif method == "mixed":
                try:
                    card_a = _dec(f_card_amount.value or "0")
                except Exception:
                    card_a = Decimal("0")
                if card_a > total_d:
                    _snack("El monto con tarjeta supera el total", ERROR)
                    return
                # Efectivo = lo que resta después de la tarjeta (auto-calculado)
                cash_a    = total_d - card_a
                change    = Decimal("0")
                pay_total = total_d
            else:
                cash_a = total_d; card_a = Decimal("0")
                change = Decimal("0"); pay_total = total_d

            # Construir notas incluyendo referencia si aplica
            ref_val   = f_reference.value.strip() if method in ("card", "transfer") else ""
            notes_val = f_notes.value.strip()
            notes_parts = []
            if ref_val:
                label = "Ref. tarjeta" if method == "card" else "Ref. transferencia"
                notes_parts.append(f"{label}: {ref_val}")
            if notes_val:
                notes_parts.append(notes_val)
            final_notes = "  |  ".join(notes_parts) or None

            confirm_btn.disabled = True
            loading_ring.visible = True
            page.update()

            try:
                items_payload = [
                    {
                        "product_id":   ci["product"]["id"],
                        "quantity":     ci["qty"],
                        "unit_price":   ci["unit_price"],
                        "discount_pct": ci["discount_pct"],
                    }
                    for ci in cart
                ]
                sale_data = {
                    "session_id":      app_state.get("session_id"),
                    "customer_name":   f_customer.value.strip() or None,
                    "customer_tax_id": f_tax_id.value.strip() or None,
                    "items":           items_payload,
                    "payment_method":  method if method != "mixed" else "mixed",
                    "payment_amount":  float(pay_total),
                    "discount_amount": float(discount_amount),
                    # cash_tendered = dinero físico que entra a la caja
                    # efectivo: el monto recibido (incluye el cambio a devolver)
                    # tarjeta/transferencia: 0
                    # mixto: solo la parte en efectivo (total - tarjeta)
                    "cash_tendered":   float(cash_a),
                    "notes":           final_notes,
                }
                sale = api.create_sale(sale_data)
                last_sale.clear()
                last_sale.update(sale)
                last_sale["_change"] = float(change)
                last_sale["_currency"] = currency

                # Imprimir ticket
                try:
                    from services.printer import TicketPrinter
                    tp = TicketPrinter(api.get_config_map())
                    if tp.enabled and not tp.print_ticket(sale):
                        _snack(f"⚠ No se pudo imprimir el ticket: {tp.last_error}", WARNING)
                except Exception as ex:
                    _snack(f"⚠ No se pudo imprimir el ticket: {ex}", WARNING)

                # Abrir cajón si la venta involucra efectivo
                if method in ("cash", "mixed"):
                    try:
                        from services.printer import TicketPrinter
                        tp = TicketPrinter(api.get_config_map())
                        tp.open_drawer()
                    except Exception:
                        pass

                cart.clear()
                _switch("success")

            except APIError as ex:
                _snack(str(ex), ERROR)
            except Exception as ex:
                _snack(f"Error inesperado: {ex}", ERROR)
            finally:
                confirm_btn.disabled = False
                loading_ring.visible = False
                page.update()

        confirm_btn.on_click = confirm_sale

        # ── Tracking de foco en campos de texto ───────────────────────────────
        # Permite al handler de teclado saber si un TextField está activo,
        # para no interceptar las teclas numéricas en ese caso.
        tf_focused = {"val": False}
        def _tf_focus(_): tf_focused["val"] = True
        def _tf_blur(_):  tf_focused["val"] = False
        for tf in (f_customer, f_tax_id, f_discount, f_notes,
                   f_reference, f_card_amount):
            tf.on_focus = _tf_focus
            tf.on_blur  = _tf_blur

        # ── Hotkeys pantalla de cobro (leídos desde configuración) ───────────
        def _payment_keyboard(e: ft.KeyboardEvent):
            if not app_state.get("pos_active") or state["mode"] != "payment":
                return                      # ignorar si no es la vista/modo activo
            c  = app_state.get("config", {})
            k  = e.key

            # Navegación / confirmación (siempre activos)
            if k == c.get("hotkey.payment.back", "Escape"):
                _switch("pos"); return
            if k in (c.get("hotkey.payment.confirm", "F12"), "Numpad Enter") \
                    and not tf_focused["val"]:
                confirm_sale(None); return

            # Selección de método de pago
            if k == c.get("hotkey.payment.method_cash",     "F1"): _set_method("cash");     return
            if k == c.get("hotkey.payment.method_card",     "F2"): _set_method("card");     return
            if k == c.get("hotkey.payment.method_transfer", "F3"): _set_method("transfer"); return
            if k == c.get("hotkey.payment.method_mixed",    "F4"): _set_method("mixed");    return
            if k == c.get("hotkey.payment.exact",           "F9"): exact_amount();           return

            # Entrada numérica (solo efectivo y sin TextField activo)
            if pay_state["method"] == "cash" and not tf_focused["val"]:
                numpad_map = {
                    "Numpad 0":"0","Numpad 1":"1","Numpad 2":"2",
                    "Numpad 3":"3","Numpad 4":"4","Numpad 5":"5",
                    "Numpad 6":"6","Numpad 7":"7","Numpad 8":"8",
                    "Numpad 9":"9","Numpad Decimal":".",
                }
                if k in numpad_map:        digit(numpad_map[k]); return
                if len(k) == 1 and k.isdigit(): digit(k); return
                if k == ".":               digit("."); return
                if k == c.get("hotkey.payment.backspace", "Backspace"): backspace(); return
                if k == c.get("hotkey.payment.clear",     "Delete"):    clear_amount(); return

        kb_callbacks["payment"] = _payment_keyboard

        # ── Header de la pantalla de cobro ────────────────────────────────────
        header = ft.Container(
            bgcolor=BG_CARD,
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            content=ft.Row([
                ft.IconButton(
                    ft.icons.ARROW_BACK, icon_color=ft.colors.WHITE,
                    tooltip="Volver al POS  [Esc]",
                    on_click=lambda _: _switch("pos"),
                ),
                ft.Icon(ft.icons.POINT_OF_SALE, color=PRIMARY),
                ft.Text("Procesar Cobro", size=18, color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD, expand=True),
                ft.Text(f"{len(cart)} artículo(s)  •  Total: {currency}{float(total_val):.2f}",
                        size=13, color=ft.colors.WHITE70),
                ft.Container(
                    bgcolor=BG_SURFACE, border_radius=6,
                    padding=ft.padding.symmetric(3, 8),
                    content=ft.Text(
                        "F1 Efec  F2 Tarj  F3 Trans  F4 Mixto  F9 Exacto  F12 Cobrar  Esc Volver",
                        size=10, color=ft.colors.WHITE38,
                    ),
                ),
            ], spacing=10),
        )

        return ft.Column(expand=True, spacing=0, controls=[
            header,
            ft.Container(
                expand=True,
                padding=ft.padding.all(12),
                content=ft.Row(
                    expand=True, spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[summary_col, payment_col],
                ),
            ),
        ])

    # ─────────────────────────────────────────────────────────────────────────
    # ── PANTALLA DE ÉXITO / TICKET ────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _build_success():
        kb_callbacks["success"] = None  # invalidar handler anterior durante rebuild
        folio    = last_sale.get("folio", "—")
        total    = float(last_sale.get("total", 0))
        change   = last_sale.get("_change", 0)
        cur      = last_sale.get("_currency", currency)
        method   = last_sale.get("payment_method", "")
        items    = last_sale.get("items", [])
        cashier  = (last_sale.get("cashier") or {}).get("full_name","")
        customer = last_sale.get("customer_name","") or ""

        # Ticket visual
        ticket_lines = ft.ListView(spacing=0)

        def ticket_row(left_text: str, right_text: str = "", bold: bool = False,
                       color=ft.colors.BLACK87, divider: bool = False):
            if divider:
                ticket_lines.controls.append(ft.Divider(height=1, color=ft.colors.BLACK26))
                return
            ticket_lines.controls.append(ft.Container(
                padding=ft.padding.symmetric(horizontal=10, vertical=2),
                content=ft.Row([
                    ft.Text(left_text, size=12, color=color, expand=True,
                            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL),
                    ft.Text(right_text, size=12, color=color,
                            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
                            text_align=ft.TextAlign.RIGHT),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ))

        store_name    = cfg.get("store.name","Mi Tienda")
        store_address = cfg.get("store.address","")
        store_phone   = cfg.get("store.phone","")
        footer_text   = cfg.get("store.footer_text","¡Gracias por su compra!")
        tax_id        = cfg.get("store.tax_id","")

        # Encabezado del ticket
        ticket_header = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            controls=[
                ft.Text(store_name, size=16, weight=ft.FontWeight.BOLD,
                        color=ft.colors.BLACK, text_align=ft.TextAlign.CENTER),
                ft.Text(store_address, size=11, color=ft.colors.BLACK54,
                        text_align=ft.TextAlign.CENTER) if store_address else ft.Container(),
                ft.Text(f"Tel: {store_phone}", size=11, color=ft.colors.BLACK54,
                        text_align=ft.TextAlign.CENTER) if store_phone else ft.Container(),
                ft.Text(f"RFC: {tax_id}", size=11, color=ft.colors.BLACK54,
                        text_align=ft.TextAlign.CENTER) if tax_id else ft.Container(),
                ft.Divider(color=ft.colors.BLACK26),
                ft.Text(f"Folio: {folio}", size=12, color=ft.colors.BLACK87),
                ft.Text(f"Fecha: {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}",
                        size=11, color=ft.colors.BLACK54),
                ft.Text(f"Cajero: {cashier}", size=11, color=ft.colors.BLACK54),
                ft.Text(f"Cliente: {customer}", size=11,
                        color=ft.colors.BLACK54) if customer else ft.Container(),
                ft.Divider(color=ft.colors.BLACK26),
            ],
        )

        for item in items:
            name  = item.get("product_name","")[:32]
            qty   = item.get("quantity",0)
            price = float(item.get("unit_price",0))
            disc  = item.get("discount_pct",0)
            line  = float(item.get("subtotal",0))
            ticket_row(f"{name}", f"{cur}{line:.2f}")
            ticket_row(f"  {qty:.0f} × {cur}{price:.2f}" + (f"  -{disc:.0f}%" if disc else ""),
                       color=ft.colors.BLACK54)

        ticket_row("", divider=True)
        ticket_row("Subtotal:", f"{cur}{float(last_sale.get('subtotal',0)):.2f}")
        if float(last_sale.get("tax_amount",0)) > 0:
            ticket_row(f"{tax_name}:", f"{cur}{float(last_sale.get('tax_amount',0)):.2f}")
        if float(last_sale.get("discount_amount",0)) > 0:
            ticket_row("Descuento:", f"-{cur}{float(last_sale.get('discount_amount',0)):.2f}")
        ticket_row("TOTAL:", f"{cur}{total:.2f}", bold=True)
        ticket_row("", divider=True)
        method_labels = {"cash":"Efectivo","card":"Tarjeta","transfer":"Transferencia","mixed":"Mixto"}
        ticket_row(f"Pago ({method_labels.get(method, method)}):",
                   f"{cur}{float(last_sale.get('payment_amount',0)):.2f}")
        if change > 0:
            ticket_row("Cambio:", f"{cur}{change:.2f}", bold=True, color=ft.colors.GREEN)
        ticket_row("", divider=True)

        ticket_footer = ft.Container(
            padding=ft.padding.all(10),
            content=ft.Text(footer_text, size=12, color=ft.colors.BLACK54,
                            text_align=ft.TextAlign.CENTER),
        )

        ticket_card = ft.Container(
            width=320, bgcolor=ft.colors.WHITE,
            border_radius=8,
            border=ft.border.all(1, ft.colors.BLACK12),
            shadow=ft.BoxShadow(blur_radius=12, color=ft.colors.BLACK26,
                                offset=ft.Offset(0, 4)),
            padding=ft.padding.symmetric(vertical=10),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[ticket_header, ticket_lines, ticket_footer],
            ),
        )

        # Acciones
        def print_again(_):
            try:
                from services.printer import TicketPrinter
                tp = TicketPrinter(api.get_config_map())
                if not tp.enabled:
                    _snack("⚠ La impresión automática está deshabilitada (Configuración → Impresora y Cajón)", WARNING)
                elif tp.print_ticket(last_sale):
                    _snack("✅ Ticket enviado a impresora")
                else:
                    _snack(f"Error de impresora: {tp.last_error}", ERROR)
            except Exception as ex:
                _snack(f"Error de impresora: {ex}", ERROR)

        def download_pdf(_):
            try:
                from services.printer import TicketPrinter
                tp = TicketPrinter(api.get_config_map())
                path = tp.print_ticket_pdf(last_sale)
                if path:
                    _snack(f"✅ PDF guardado: {path}")
                else:
                    _snack("⚠ Instala fpdf2:  pip install fpdf2", WARNING)
            except Exception as ex:
                _snack(f"Error PDF: {ex}", ERROR)

        def new_sale(_):
            _switch("pos")

        change_badge = ft.Container()
        if change > 0:
            change_badge = ft.Container(
                bgcolor=SUCCESS + "22", border_radius=12,
                border=ft.border.all(2, SUCCESS),
                padding=ft.padding.symmetric(horizontal=24, vertical=16),
                content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, controls=[
                    ft.Text("CAMBIO A ENTREGAR", size=13, color=SUCCESS, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{cur}{change:.2f}", size=40, color=SUCCESS, weight=ft.FontWeight.BOLD),
                ]),
            )

        left_col = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
            controls=[
                ft.Container(
                    width=90, height=90, border_radius=45,
                    bgcolor=SUCCESS + "22",
                    border=ft.border.all(4, SUCCESS),
                    alignment=ft.alignment.center,
                    content=ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE, color=SUCCESS, size=52),
                ),
                ft.Text("¡Venta completada!", size=26, weight=ft.FontWeight.BOLD,
                        color=ft.colors.WHITE, text_align=ft.TextAlign.CENTER),
                ft.Text(f"Folio: {folio}", size=16, color=PRIMARY_LT),
                change_badge,
                ft.Container(height=8),
                ft.Row(
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.ElevatedButton(
                            "🖨  Reimprimir", width=124, height=48,
                            on_click=print_again,
                            style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=ft.colors.WHITE,
                                                 shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ft.ElevatedButton(
                            "📄  PDF", width=124, height=48,
                            on_click=download_pdf,
                            style=ft.ButtonStyle(bgcolor=BG_SURFACE, color=PRIMARY_LT,
                                                 side=ft.BorderSide(1, PRIMARY),
                                                 shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                    ],
                ),
                ft.ElevatedButton(
                    "➕  Nueva venta", expand=False, width=260, height=56,
                    on_click=new_sale,
                    style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE,
                                         shape=ft.RoundedRectangleBorder(radius=10)),
                ),
            ],
        )

        right_col = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Text("Vista previa del ticket", size=13, color=ft.colors.WHITE54),
                ticket_card,
            ],
        )

        # ── Hotkeys pantalla de éxito (leídos desde configuración) ──────────
        def _success_keyboard(e: ft.KeyboardEvent):
            if not app_state.get("pos_active") or state["mode"] != "success":
                return                      # ignorar si no es la vista/modo activo
            c = app_state.get("config", {})
            k = e.key
            new_sale_key = c.get("hotkey.success.new_sale", "Enter")
            print_key     = c.get("hotkey.success.print",    "P")
            if k in (new_sale_key, "Numpad Enter", "F12", "Escape"):
                new_sale(None)
            elif k == print_key or k.lower() == print_key.lower():
                print_again(None)

        kb_callbacks["success"] = _success_keyboard

        return ft.Container(
            expand=True, bgcolor=BG_DARK,
            content=ft.Column(expand=True, spacing=0, controls=[
                ft.Container(
                    bgcolor=BG_CARD,
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                    content=ft.Row([
                        ft.Icon(ft.icons.RECEIPT_LONG, color=SUCCESS),
                        ft.Text("Venta Registrada", size=18, color=ft.colors.WHITE,
                                weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(datetime.now().strftime("%d/%m/%Y  %H:%M"),
                                size=13, color=ft.colors.WHITE54),
                    ], spacing=10),
                ),
                ft.Container(
                    expand=True,
                    padding=ft.padding.all(24),
                    content=ft.Row(
                        expand=True, spacing=40,
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[left_col, right_col],
                    ),
                ),
            ]),
        )

    # ── Arrancar en modo POS ──────────────────────────────────────────────────
    _switch("pos")
    return root
