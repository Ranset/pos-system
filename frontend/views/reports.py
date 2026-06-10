"""
Vista de Reportes Financieros – Resumen mensual, Diario y por rango
"""
import flet as ft
from datetime import date, timedelta
from config import PRIMARY, PRIMARY_LT, BG_DARK, BG_CARD, BG_SURFACE, SUCCESS, ERROR, WARNING
from services import api, APIError


MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MONTH_ABBR = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


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

    # Controles de fecha directos (sin ft.Ref) – usados por Reporte Diario / Rango
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

    def _bar_row(label: str, value: float, max_val: float, color: str, is_qty: bool = False):
        pct = (value / max_val) if max_val > 0 else 0
        value_text = f"{value:,.0f}" if is_qty else f"{currency}{value:,.2f}"
        return ft.Container(
            padding=ft.padding.symmetric(vertical=3),
            content=ft.Column(spacing=4, controls=[
                ft.Row([
                    ft.Text(label[:28], size=12, color=ft.colors.WHITE70, expand=True),
                    ft.Text(value_text, size=12, color=color,
                            weight=ft.FontWeight.BOLD, width=90, text_align=ft.TextAlign.RIGHT),
                ]),
                ft.ProgressBar(value=pct, color=color, bgcolor=ft.colors.WHITE12,
                               height=8),
            ]),
        )

    def _empty_placeholder(text: str = "No hay datos para mostrar"):
        return ft.Container(
            alignment=ft.alignment.center, padding=30,
            content=ft.Text(text, color=ft.colors.WHITE38, size=12),
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

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 0 — Resumen / Dashboard
    # ─────────────────────────────────────────────────────────────────────────

    dash_state = {"year": date.today().year, "monthly": []}
    period_state = {"start": date.today(), "end": date.today()}

    dash_year_text  = ft.Text(str(dash_state["year"]), size=16,
                               color=ft.colors.WHITE, weight=ft.FontWeight.BOLD)
    dash_count_switch = ft.Switch(value=False, active_color=SUCCESS,
                                   tooltip="Mostrar cantidad de ventas en lugar de ingresos")
    dash_chart_container = ft.Container(height=230)
    dash_total_label = ft.Text("Ventas Totales", size=11, color=ft.colors.WHITE54)
    dash_total_text  = ft.Text("0", size=40, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
    dash_best_month_text  = ft.Text("---", size=15, color=PRIMARY_LT, weight=ft.FontWeight.BOLD)
    dash_best_month_value = ft.Text(f"{currency}0.00", size=18, color=ft.colors.WHITE,
                                     weight=ft.FontWeight.BOLD)

    period_label_text = ft.Text("", size=13, color=ft.colors.WHITE, weight=ft.FontWeight.BOLD)
    period_top_products   = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=190)
    period_hours_container = ft.Container(height=140, alignment=ft.alignment.bottom_center)
    period_total_qty_text = ft.Text("0", size=46, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
    period_top_categories = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=160)

    period_from_field = ft.TextField(
        label="Desde", value=today_str, width=150, hint_text="AAAA-MM-DD",
        border_color=PRIMARY, color=ft.colors.WHITE, bgcolor=BG_SURFACE, text_size=12,
    )
    period_to_field = ft.TextField(
        label="Hasta", value=today_str, width=150, hint_text="AAAA-MM-DD",
        border_color=PRIMARY, color=ft.colors.WHITE, bgcolor=BG_SURFACE, text_size=12,
    )

    def _render_dashboard_chart():
        data = dash_state.get("monthly") or [
            {"month": m, "total_sales": 0, "total_revenue": 0.0} for m in range(1, 13)
        ]
        by_count = dash_count_switch.value
        values = [(d["total_sales"] if by_count else d["total_revenue"]) for d in data]
        max_v = max(values) if values and max(values) > 0 else 1

        bar_groups = []
        for i, v in enumerate(values):
            tooltip = (
                f"{MONTH_NAMES[i]}: {v:,.0f}" if by_count
                else f"{MONTH_NAMES[i]}: {currency}{v:,.2f}"
            )
            bar_groups.append(
                ft.BarChartGroup(
                    x=i,
                    bar_rods=[
                        ft.BarChartRod(
                            to_y=v,
                            width=18,
                            color=PRIMARY if v > 0 else ft.colors.WHITE12,
                            border_radius=ft.border_radius.only(top_left=4, top_right=4),
                            tooltip=tooltip,
                        )
                    ],
                )
            )

        dash_chart_container.content = ft.BarChart(
            bar_groups=bar_groups,
            groups_space=10,
            max_y=max_v * 1.2,
            interactive=True,
            expand=True,
            tooltip_bgcolor=ft.colors.with_opacity(0.85, BG_SURFACE),
            border=ft.border.all(0, ft.colors.TRANSPARENT),
            horizontal_grid_lines=ft.ChartGridLines(
                color=ft.colors.WHITE12, width=1, interval=max(max_v / 4, 1)
            ),
            left_axis=ft.ChartAxis(labels_size=44, show_labels=True),
            bottom_axis=ft.ChartAxis(
                labels_size=24,
                labels=[
                    ft.ChartAxisLabel(
                        value=i,
                        label=ft.Text(MONTH_ABBR[i], size=10, color=ft.colors.WHITE54),
                    )
                    for i in range(12)
                ],
            ),
        )

        # Tarjeta "Ventas Totales" + mes de mayor rendimiento
        total_rev   = sum(d["total_revenue"] for d in data)
        total_count = sum(d["total_sales"] for d in data)
        if by_count:
            dash_total_label.value = "Ventas Totales (Cantidad)"
            dash_total_text.value  = f"{total_count:,.0f}"
        else:
            dash_total_label.value = "Ventas Totales"
            dash_total_text.value  = f"{currency}{total_rev:,.2f}"

        best = max(data, key=lambda d: d["total_revenue"], default=None)
        if best and best["total_revenue"] > 0:
            dash_best_month_text.value  = MONTH_NAMES[best["month"] - 1]
            dash_best_month_value.value = f"{currency}{best['total_revenue']:,.2f}"
        else:
            dash_best_month_text.value  = "---"
            dash_best_month_value.value = f"{currency}0.00"

        page.update()

    def load_monthly(e=None):
        try:
            dash_state["monthly"] = api.get_monthly_report(dash_state["year"])
        except APIError as ex:
            dash_state["monthly"] = []
            _show_snack(str(ex))
        _render_dashboard_chart()

    def _year_prev(e=None):
        dash_state["year"] -= 1
        dash_year_text.value = str(dash_state["year"])
        load_monthly()

    def _year_next(e=None):
        dash_state["year"] += 1
        dash_year_text.value = str(dash_state["year"])
        load_monthly()

    def _toggle_dash_mode(e=None):
        _render_dashboard_chart()

    def _period_label():
        d_from = period_state["start"].strftime("%d/%m/%Y")
        d_to   = period_state["end"].strftime("%d/%m/%Y")
        return f"Reportes Periódicos ( {d_from} - {d_to} )"

    def _render_period(data: dict):
        period_label_text.value = _period_label()

        # Top productos
        period_top_products.controls.clear()
        top = data.get("top_products", [])
        if top:
            max_top = max((p.get("total", 0) for p in top), default=0.01)
            for p in top[:8]:
                period_top_products.controls.append(
                    _bar_row(p.get("name", ""), float(p.get("total", 0)), max_top, PRIMARY_LT)
                )
        else:
            period_top_products.controls.append(_empty_placeholder())

        # Ventas por hora
        hours = data.get("sales_by_hour", [])
        max_h = max((h.get("count", 0) for h in hours), default=0)
        if max_h > 0:
            period_hours_container.content = ft.Row(
                controls=[_hour_bar(h["hour"], h["count"], max_h) for h in hours],
                vertical_alignment=ft.CrossAxisAlignment.END,
                spacing=3,
            )
        else:
            period_hours_container.content = _empty_placeholder()

        # Ventas totales (cantidad)
        period_total_qty_text.value = f"{data.get('total_sales', 0):,.0f}"

        # Top grupos de productos (categorías)
        period_top_categories.controls.clear()
        cats = data.get("top_categories", [])
        if cats:
            max_cat = max((c.get("total", 0) for c in cats), default=0.01)
            for c in cats[:10]:
                period_top_categories.controls.append(
                    _bar_row(c.get("name", ""), float(c.get("total", 0)), max_cat, SUCCESS)
                )
        else:
            period_top_categories.controls.append(_empty_placeholder())

        page.update()

    def load_period(e=None):
        try:
            data = api.get_period_report(
                period_state["start"].isoformat(), period_state["end"].isoformat()
            )
            _render_period(data)
        except APIError as ex:
            _show_snack(str(ex))

    def _open_period_picker(e=None):
        period_from_field.value = period_state["start"].isoformat()
        period_to_field.value   = period_state["end"].isoformat()
        err_t = ft.Text("", color=ERROR, size=12)

        def apply_range(_):
            try:
                f = date.fromisoformat((period_from_field.value or "").strip())
                t = date.fromisoformat((period_to_field.value or "").strip())
            except ValueError:
                err_t.value = "Formato de fecha inválido (use AAAA-MM-DD)"
                page.update()
                return
            if f > t:
                err_t.value = "La fecha 'Desde' no puede ser posterior a 'Hasta'"
                page.update()
                return
            period_state["start"] = f
            period_state["end"]   = t
            dlg.open = False
            page.update()
            load_period()

        def quick(days: int):
            period_to_field.value   = date.today().isoformat()
            period_from_field.value = (date.today() - timedelta(days=days - 1)).isoformat()
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.icons.CALENDAR_MONTH, color=PRIMARY),
                ft.Text("Rango de Reportes Periódicos", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=380,
                content=ft.Column(spacing=10, controls=[
                    ft.Row([period_from_field, period_to_field], spacing=10),
                    ft.Row(spacing=4, controls=[
                        ft.TextButton("Hoy", on_click=lambda _: quick(1),
                                      style=ft.ButtonStyle(color=PRIMARY_LT)),
                        ft.TextButton("7 días", on_click=lambda _: quick(7),
                                      style=ft.ButtonStyle(color=PRIMARY_LT)),
                        ft.TextButton("30 días", on_click=lambda _: quick(30),
                                      style=ft.ButtonStyle(color=PRIMARY_LT)),
                        ft.TextButton("Este mes", on_click=lambda _: (
                            setattr(period_from_field, "value", date.today().replace(day=1).isoformat()),
                            setattr(period_to_field, "value", date.today().isoformat()),
                            page.update(),
                        )[-1], style=ft.ButtonStyle(color=PRIMARY_LT)),
                    ]),
                    err_t,
                ]),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: setattr(dlg, "open", False) or page.update()),
                ft.ElevatedButton("Aplicar", icon=ft.icons.CHECK,
                                  on_click=apply_range,
                                  style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE)),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    dash_count_switch.on_change = _toggle_dash_mode

    dashboard_content = ft.Column(
        spacing=12,
        controls=[
            ft.Row(spacing=12, controls=[
                # ── Ventas mensuales (gráfica) ──────────────────────────────
                ft.Container(
                    expand=2, height=320, bgcolor=BG_CARD, border_radius=12, padding=16,
                    content=ft.Column(spacing=8, controls=[
                        ft.Row(
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Column(expand=True, spacing=2, controls=[
                                    ft.Row(spacing=4, controls=[
                                        ft.Text("Ventas Mensuales -", size=16,
                                                weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                                        dash_year_text,
                                    ]),
                                    ft.Text("Datos de ventas agrupados por mes",
                                            size=11, color=ft.colors.WHITE54),
                                ]),
                                ft.IconButton(ft.icons.REFRESH, icon_color=PRIMARY,
                                              on_click=load_monthly, tooltip="Actualizar"),
                                dash_count_switch,
                                ft.IconButton(ft.icons.CHEVRON_LEFT, icon_color=ft.colors.WHITE54,
                                              on_click=_year_prev, tooltip="Año anterior"),
                                ft.IconButton(ft.icons.CHEVRON_RIGHT, icon_color=ft.colors.WHITE54,
                                              on_click=_year_next, tooltip="Año siguiente"),
                            ],
                        ),
                        dash_chart_container,
                    ]),
                ),
                # ── Ventas totales / mejor mes ──────────────────────────────
                ft.Container(
                    expand=1, height=320, bgcolor=BG_CARD, border_radius=12, padding=16,
                    content=ft.Column(
                        spacing=10,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(spacing=10, controls=[
                                dash_total_label,
                                dash_total_text,
                            ]),
                            ft.Column(spacing=4, controls=[
                                ft.Divider(color=ft.colors.WHITE12),
                                ft.Text("Mes de mayor rendimiento:", size=11, color=ft.colors.WHITE54),
                                dash_best_month_text,
                                dash_best_month_value,
                            ]),
                        ],
                    ),
                ),
            ]),
            # ── Encabezado de reportes periódicos ───────────────────────────
            ft.Container(
                bgcolor=BG_CARD, border_radius=12,
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                content=ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        period_label_text,
                        ft.IconButton(ft.icons.CALENDAR_MONTH, icon_color=PRIMARY,
                                      on_click=_open_period_picker,
                                      tooltip="Cambiar rango de fechas"),
                    ],
                ),
            ),
            # ── Top productos / Ventas por hora / Ventas totales (cantidad) ─
            ft.Row(spacing=12, controls=[
                ft.Container(
                    expand=True, height=290, bgcolor=BG_CARD, border_radius=12, padding=16,
                    content=ft.Column(spacing=8, controls=[
                        ft.Text("Top Productos", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                        period_top_products,
                    ]),
                ),
                ft.Container(
                    expand=True, height=290, bgcolor=BG_CARD, border_radius=12, padding=16,
                    content=ft.Column(spacing=8, controls=[
                        ft.Text("Ventas por hora", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                        period_hours_container,
                    ]),
                ),
                ft.Container(
                    expand=True, height=290, bgcolor=BG_CARD, border_radius=12, padding=16,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8, controls=[
                            ft.Text("Ventas Totales (Cantidad)", size=14,
                                    weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                            period_total_qty_text,
                        ],
                    ),
                ),
            ]),
            # ── Top grupos de productos ──────────────────────────────────────
            ft.Container(
                bgcolor=BG_CARD, border_radius=12, padding=16,
                content=ft.Column(spacing=4, controls=[
                    ft.Text("Top grupos de productos", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                    ft.Text("Grupos de productos de mayor venta en el período seleccionado",
                            size=11, color=ft.colors.WHITE54),
                    ft.Container(height=8),
                    period_top_categories,
                ]),
            ),
        ],
    )

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — Reporte Diario / TAB 2 — Reporte por Rango
    # ─────────────────────────────────────────────────────────────────────────

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

    # Filas de filtros de fecha (Reporte Diario / Reporte por Rango)
    date_filter_row = ft.Row(
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text("Desde:", color=ft.colors.WHITE54, size=12),
            date_from_field,
            ft.Text("Hasta:", color=ft.colors.WHITE54, size=12),
            date_to_field,
            ft.ElevatedButton(
                "Buscar", icon=ft.icons.SEARCH,
                on_click=lambda e: load_daily() if tab_index_ref["val"] == 1 else load_range(),
                style=ft.ButtonStyle(bgcolor=PRIMARY, color=ft.colors.WHITE),
            ),
        ],
    )
    quick_access_row = ft.Row(
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(expand=True),
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
    )
    date_filter_container  = ft.Container(
        bgcolor=BG_CARD,
        padding=ft.padding.only(left=16, right=16, top=10, bottom=6),
        content=ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Container(expand=True),
            date_filter_row,
        ]),
    )
    quick_access_container = ft.Container(
        bgcolor=BG_CARD,
        padding=ft.padding.only(left=16, right=16, bottom=8),
        content=quick_access_row,
    )

    def on_tab_change(e):
        idx = e.control.selected_index
        tab_index_ref["val"] = idx
        # Los filtros de fecha solo aplican a "Reporte Diario" y "Reporte por Rango"
        date_filter_container.visible  = idx in (1, 2)
        quick_access_container.visible = idx in (1, 2)
        if idx == 0:
            load_monthly()
            load_period()
        elif idx == 1:
            report_content.controls.clear()
            load_daily()
        elif idx == 2:
            report_content.controls.clear()
            load_range()
        page.update()

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

    # Carga inicial — pestaña "Resumen"
    date_filter_container.visible  = False
    quick_access_container.visible = False
    load_monthly()
    load_period()

    return ft.Container(
        expand=True, bgcolor=BG_DARK,
        content=ft.Column(
            expand=True, spacing=0,
            controls=[
                # ── Fila 1: Título ──────────────────────────────────────────
                ft.Container(
                    bgcolor=BG_CARD,
                    padding=ft.padding.only(left=16, right=16, top=10, bottom=6),
                    content=ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.icons.ANALYTICS, color=PRIMARY),
                            ft.Text("Reportes Financieros", size=17,
                                    color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                ),
                # ── Fila 2: Filtros de fecha (Diario / Rango) ────────────────
                date_filter_container,
                # ── Fila 3: Accesos rápidos (Diario / Rango) ─────────────────
                quick_access_container,
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
                            text="Resumen",
                            icon=ft.icons.DASHBOARD,
                            content=ft.Container(
                                expand=True,
                                padding=ft.padding.all(12),
                                content=ft.ListView(
                                    expand=True,
                                    controls=[dashboard_content],
                                    spacing=10,
                                ),
                            ),
                        ),
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
