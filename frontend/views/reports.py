"""
Vista de Reportes Financieros – Diario, por rango y por sesión
"""
import flet as ft
from datetime import date, timedelta
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


def reports_view(page: ft.Page, app_state: dict):
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

    report_content = ft.Column(expand=True, spacing=10, scroll=ft.ScrollMode.AUTO)
    today_str      = date.today().isoformat()

    # Controles de fecha directos (sin ft.Ref)
    date_from_field = ft.TextField(
        value=today_str, width=135,
        hint_text="AAAA-MM-DD",
        border_color=PRIMARY, color=ft.colors.WHITE,
        bgcolor=BG_SURFACE, text_size=12,
    )
    date_to_field = ft.TextField(
        value=today_str, width=135,
        hint_text="AAAA-MM-DD",
        border_color=PRIMARY, color=ft.colors.WHITE,
        bgcolor=BG_SURFACE, text_size=12,
    )

    def _show_snack(msg, color=ERROR):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=ft.colors.WHITE), bgcolor=color, open=True)
        page.update()

    # ── Tarjeta de métricas ───────────────────────────────────────────────────

    def _metric_card(label: str, value: str, icon, color: str, subtitle: str = ""):
        return ft.Container(
            expand=True, bgcolor=BG_CARD,
            border_radius=12,
            border=ft.border.all(1, color + "44"),
            padding=ft.padding.all(18),
            content=ft.Column(spacing=6, controls=[
                ft.Row([
                    ft.Container(
                        width=38, height=38, border_radius=10,
                        bgcolor=color + "22",
                        alignment=ft.alignment.center,
                        content=ft.Icon(icon, color=color, size=20),
                    ),
                    ft.Column(expand=True, spacing=1, controls=[
                        ft.Text(label, size=11, color=ft.colors.WHITE54),
                        ft.Text(value, size=22, color=color, weight=ft.FontWeight.BOLD),
                    ]),
                ], spacing=10),
                ft.Text(subtitle, size=11, color=ft.colors.WHITE38) if subtitle else ft.Container(),
            ]),
        )

    # ── Barra horizontal simple (sin dependencia de chart) ────────────────────

    def _bar_row(label: str, value: float, max_val: float, color: str):
        pct = (value / max_val) if max_val > 0 else 0
        return ft.Container(
            padding=ft.padding.symmetric(vertical=3),
            content=ft.Column(spacing=4, controls=[
                ft.Row([
                    ft.Text(label[:28], size=12, color=ft.colors.WHITE70, expand=True),
                    ft.Text(f"{currency}{value:,.2f}", size=12, color=color,
                            weight=ft.FontWeight.BOLD, width=90, text_align=ft.TextAlign.RIGHT),
                ]),
                ft.ProgressBar(value=pct, color=color, bgcolor=ft.colors.WHITE12,
                               height=8),
            ]),
        )

    def _hour_bar(hour: int, count: int, max_count: int):
        pct = (count / max_count) if max_count > 0 else 0
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            controls=[
                ft.Text(str(count), size=10, color=PRIMARY_LT if count > 0 else ft.colors.WHITE24),
                ft.Container(
                    width=18,
                    height=max(4, int(pct * 80)),
                    bgcolor=PRIMARY if count > 0 else ft.colors.WHITE12,
                    border_radius=ft.border_radius.only(top_left=3, top_right=3),
                ),
                ft.Text(f"{hour:02d}", size=9, color=ft.colors.WHITE38),
            ],
        )

    # ── Render reporte diario ─────────────────────────────────────────────────

    def render_daily(data: dict):
        report_content.controls.clear()
        total_rev  = float(data.get("total_revenue", 0))
        total_tax  = float(data.get("total_tax", 0))
        total_disc = float(data.get("total_discounts", 0))
        total_s    = int(data.get("total_sales", 0))
        cancelled  = int(data.get("cancelled_sales", 0))
        cash_s     = float(data.get("cash_sales", 0))
        card_s     = float(data.get("card_sales", 0))
        trans_s    = float(data.get("transfer_sales", 0))
        avg_ticket = total_rev / total_s if total_s > 0 else 0

        # Tarjetas de métricas
        report_content.controls.append(ft.Row(spacing=10, controls=[
            _metric_card("Ingresos totales", f"{currency}{total_rev:,.2f}",
                         ft.icons.ATTACH_MONEY, SUCCESS),
            _metric_card("Ventas completadas", str(total_s),
                         ft.icons.RECEIPT_LONG, PRIMARY_LT,
                         f"{cancelled} cancelada(s)"),
            _metric_card("Ticket promedio", f"{currency}{avg_ticket:,.2f}",
                         ft.icons.SHOW_CHART, WARNING),
            _metric_card(tax_name + " generado", f"{currency}{total_tax:,.2f}",
                         ft.icons.RECEIPT, ft.colors.PURPLE_300),
        ]))

        # Desglose por método de pago
        max_pay = max(cash_s, card_s, trans_s, 0.01)
        report_content.controls.append(ft.Container(
            bgcolor=BG_CARD, border_radius=12, padding=20,
            content=ft.Column(spacing=10, controls=[
                ft.Text("Ventas por método de pago", size=14, color=ft.colors.WHITE,
                        weight=ft.FontWeight.BOLD),
                _bar_row("💵 Efectivo",     cash_s,  max_pay, SUCCESS),
                _bar_row("💳 Tarjeta",      card_s,  max_pay, PRIMARY_LT),
                _bar_row("🏦 Transferencia", trans_s, max_pay, WARNING),
                ft.Row([
                    ft.Text(f"Descuentos aplicados: {currency}{total_disc:,.2f}",
                            size=12, color=ERROR),
                ]),
            ]),
        ))

        # Top productos
        top = data.get("top_products", [])
        if top:
            max_top = max((p.get("total",0) for p in top), default=0.01)
            prod_bars = [
                _bar_row(p.get("name","")[:30], float(p.get("total",0)), max_top, PRIMARY_LT)
                for p in top[:10]
            ]
            report_content.controls.append(ft.Container(
                bgcolor=BG_CARD, border_radius=12, padding=20,
                content=ft.Column(spacing=8, controls=[
                    ft.Text("Top 10 productos más vendidos", size=14,
                            color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                    *prod_bars,
                ]),
            ))

        # Ventas por hora
        hours_data = data.get("sales_by_hour", [])
        if hours_data:
            max_h = max((h.get("count",0) for h in hours_data), default=1)
            hour_bars = [
                _hour_bar(h.get("hour",0), h.get("count",0), max_h)
                for h in hours_data
            ]
            report_content.controls.append(ft.Container(
                bgcolor=BG_CARD, border_radius=12, padding=20,
                content=ft.Column(spacing=8, controls=[
                    ft.Text("Distribución de ventas por hora", size=14,
                            color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=ft.Row(
                            controls=hour_bars,
                            vertical_alignment=ft.CrossAxisAlignment.END,
                            spacing=3,
                        ),
                        height=120,
                        alignment=ft.alignment.bottom_center,
                    ),
                ]),
            ))

        page.update()

    # ── Render reporte por rango ──────────────────────────────────────────────

    def render_range(data: list):
        report_content.controls.clear()
        if not data:
            report_content.controls.append(ft.Text("Sin datos", color=ft.colors.WHITE54))
            page.update(); return

        total_rev    = sum(float(d.get("total_revenue",0)) for d in data)
        total_s      = sum(int(d.get("total_sales",0)) for d in data)
        total_disc   = sum(float(d.get("total_discounts",0)) for d in data)
        total_tax    = sum(float(d.get("total_tax",0)) for d in data)

        report_content.controls.append(ft.Row(spacing=10, controls=[
            _metric_card("Ingresos del período", f"{currency}{total_rev:,.2f}",
                         ft.icons.TRENDING_UP, SUCCESS),
            _metric_card("Total ventas", str(total_s), ft.icons.RECEIPT_LONG, PRIMARY_LT),
            _metric_card(tax_name, f"{currency}{total_tax:,.2f}", ft.icons.RECEIPT, ft.colors.PURPLE_300),
            _metric_card("Descuentos", f"{currency}{total_disc:,.2f}", ft.icons.DISCOUNT, WARNING),
        ]))

        # Tabla diaria
        rows = []
        for d in data:
            rev = float(d.get("total_revenue",0))
            s   = int(d.get("total_sales",0))
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(d.get("date",""), size=12, color=ft.colors.WHITE70)),
                ft.DataCell(ft.Text(str(s), size=13, color=ft.colors.WHITE)),
                ft.DataCell(ft.Text(f"{currency}{rev:,.2f}", size=13, color=SUCCESS,
                                    weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(f"{currency}{float(d.get('total_tax',0)):,.2f}",
                                    size=12, color=ft.colors.WHITE54)),
                ft.DataCell(ft.Text(f"{currency}{float(d.get('total_discounts',0)):,.2f}",
                                    size=12, color=WARNING)),
                ft.DataCell(ft.Text(f"{currency}{rev/s:.2f}" if s > 0 else "—",
                                    size=12, color=ft.colors.WHITE60)),
            ]))

        report_content.controls.append(ft.Container(
            bgcolor=BG_CARD, border_radius=12, padding=20,
            content=ft.Column(spacing=8, controls=[
                ft.Text("Detalle por día", size=14, color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    border=ft.border.all(1, ft.colors.WHITE12),
                    border_radius=8,
                    heading_row_color=BG_SURFACE,
                    columns=[
                        ft.DataColumn(ft.Text("Fecha",      color=ft.colors.WHITE70, size=12)),
                        ft.DataColumn(ft.Text("Ventas",     color=ft.colors.WHITE70, size=12), numeric=True),
                        ft.DataColumn(ft.Text("Ingresos",   color=ft.colors.WHITE70, size=12), numeric=True),
                        ft.DataColumn(ft.Text(tax_name,     color=ft.colors.WHITE70, size=12), numeric=True),
                        ft.DataColumn(ft.Text("Descuentos", color=ft.colors.WHITE70, size=12), numeric=True),
                        ft.DataColumn(ft.Text("Ticket prom",color=ft.colors.WHITE70, size=12), numeric=True),
                    ],
                    rows=rows,
                ),
            ]),
        ))
        page.update()

    # ── Controles de filtros ──────────────────────────────────────────────────

    tab_index_ref = {"val": 0}

    def load_daily(e=None):
        d = (date_from_field.value or today_str).strip()
        try:
            data = api.get_daily_report(d)
            render_daily(data)
        except APIError as ex:
            _show_snack(str(ex))

    def load_range(e=None):
        d_from = (date_from_field.value or today_str).strip()
        d_to   = (date_to_field.value or today_str).strip()
        try:
            data = api.get_range_report(d_from, d_to)
            render_range(data)
        except APIError as ex:
            _show_snack(str(ex))

    def on_tab_change(e):
        idx = e.control.selected_index
        tab_index_ref["val"] = idx
        report_content.controls.clear()
        page.update()
        if idx == 0:
            load_daily()
        elif idx == 1:
            load_range()


    def _quick_date(days_ago: int):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        date_from_field.value = d
        date_to_field.value = d
        page.update()
        load_daily()

    def _quick_range(days: int):
        d_to   = date.today().isoformat()
        d_from = (date.today() - timedelta(days=days - 1)).isoformat()
        date_from_field.value = d_from
        date_to_field.value = d_to
        page.update()
        load_range()

    # Carga inicial
    load_daily()

    return ft.Container(
        expand=True, bgcolor=BG_DARK,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                # ── Fila 1: Título + campos de fecha + Buscar ─────────────────
                ft.Container(
                    bgcolor=BG_CARD,
                    padding=ft.padding.only(left=16, right=16, top=10, bottom=6),
                    content=ft.Row(
                        # Row normal (ni scroll ni wrap) → expand=True del
                        # spacer funciona correctamente aquí
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.icons.ANALYTICS, color=PRIMARY),
                            ft.Text("Reportes Financieros", size=17,
                                    color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),       # spacer → empuja controles a la derecha
                            ft.Text("Desde:", color=ft.colors.WHITE54, size=12),
                            date_from_field,
                            ft.Text("Hasta:", color=ft.colors.WHITE54, size=12),
                            date_to_field,
                            ft.ElevatedButton(
                                "Buscar", icon=ft.icons.SEARCH,
                                on_click=lambda e: load_daily() if tab_index_ref["val"] == 0 else load_range(),
                                style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
                            ),
                        ],
                    ),
                ),
                # ── Fila 2: Accesos rápidos (siempre a la derecha) ────────────
                ft.Container(
                    bgcolor=BG_CARD,
                    padding=ft.padding.only(left=16, right=16, bottom=8),
                    content=ft.Row(
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(expand=True),       # empuja botones a la derecha
                            ft.Text("Acceso rápido:", color=ft.colors.WHITE38, size=11),
                            ft.TextButton("Hoy",     on_click=lambda _: _quick_date(0),
                                          style=ft.ButtonStyle(color=PRIMARY_LT)),
                            ft.TextButton("Ayer",    on_click=lambda _: _quick_date(1),
                                          style=ft.ButtonStyle(color=PRIMARY_LT)),
                            ft.TextButton("7 días",  on_click=lambda _: _quick_range(7),
                                          style=ft.ButtonStyle(color=PRIMARY_LT)),
                            ft.TextButton("30 días", on_click=lambda _: _quick_range(30),
                                          style=ft.ButtonStyle(color=PRIMARY_LT)),
                        ],
                    ),
                ),
                ft.Divider(height=1, color=ft.colors.WHITE12),
                # ── Pestañas de reporte ───────────────────────────────────────
                ft.Tabs(
                    expand=True,
                    selected_index=0,
                    on_change=on_tab_change,
                    indicator_color=PRIMARY,
                    label_color=PRIMARY_LT,
                    unselected_label_color=ft.colors.WHITE54,
                    tabs=[
                        ft.Tab(
                            text="Reporte Diario",
                            icon=ft.icons.TODAY,
                            content=ft.Container(
                                expand=True,
                                padding=ft.padding.all(12),
                                content=ft.ListView(
                                    expand=True,
                                    controls=[report_content],
                                    spacing=10,
                                ),
                            ),
                        ),
                        ft.Tab(
                            text="Reporte por Rango",
                            icon=ft.icons.DATE_RANGE,
                            content=ft.Container(
                                expand=True,
                                padding=ft.padding.all(12),
                                content=ft.ListView(
                                    expand=True,
                                    controls=[report_content],
                                    spacing=10,
                                ),
                            ),
                        ),
                    ],
                ),
            ],
        ),
    )
