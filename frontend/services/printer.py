"""
Servicio de impresión ESC/POS para ticketeras térmicas y cajón de dinero.
Soporta: USB, Serial, Red (TCP)
"""
from __future__ import annotations   # permite str | None y list[str] en Python 3.9
import os
import unicodedata
from typing import Optional
from datetime import datetime


def _format_currency(amount, symbol="$", decimals=2) -> str:
    try:
        return f"{symbol}{float(amount):,.{decimals}f}"
    except Exception:
        return str(amount)


def _sanitize_escpos(texto: str) -> str:
    """Convierte texto con tildes, eñes, signos ¡¿, etc. a ASCII plano,
    seguro para impresoras térmicas sin perfil/codepage configurado."""
    normalizado = unicodedata.normalize("NFKD", texto)
    return normalizado.encode("ascii", "ignore").decode("ascii")


class TicketPrinter:
    def __init__(self, config: dict):
        self.config = config
        self._printer = None
        self.last_error: Optional[str] = None
        self.enabled = config.get("printer.enabled", "false").lower() == "true"
        self.paper_width = int(config.get("printer.paper_width", "80"))
        self.open_drawer_enabled = config.get("printer.open_drawer", "true").lower() == "true"
        self.copies = int(config.get("printer.copies", "1"))
        self.currency_symbol = config.get("fiscal.currency_symbol", "$")
        self.tax_name = config.get("fiscal.tax_name", "IVA")
        self.print_tax = config.get("fiscal.print_tax_breakdown", "true").lower() == "true"
        self.store_name = config.get("store.name", "Mi Tienda")
        self.store_address = config.get("store.address", "")
        self.store_phone = config.get("store.phone", "")
        self.store_tax_id = config.get("store.tax_id", "")
        self.footer_text = config.get("store.footer_text", "¡Gracias por su compra!")
        self.qr_content = (config.get("store.qr_content") or "").strip()
        self.qr_cta_text = (config.get("store.qr_cta_text") or "").strip()
        self.char_width = 48 if self.paper_width >= 80 else 32

    def _get_printer(self):
        """Instancia la impresora según tipo de conexión."""
        self.last_error = None
        try:
            from escpos.printer import Usb, Serial, Network
            ptype = self.config.get("printer.type", "usb").lower()

            if ptype == "usb":
                vid = int(self.config.get("printer.usb_vendor_id", "0x0416"), 0)
                pid = int(self.config.get("printer.usb_product_id", "0x5011"), 0)
                return Usb(vid, pid)
            elif ptype == "serial":
                port = self.config.get("printer.serial_port", "/dev/ttyUSB0")
                return Serial(port)
            elif ptype == "network":
                host = self.config.get("printer.network_host", "")
                if not host:
                    self.last_error = "Falta configurar la IP de la impresora de red (Configuración → Impresora y Cajón)"
                    print(f"[Printer] {self.last_error}")
                    return None
                port = int(self.config.get("printer.network_port", "9100"))
                return Network(host, port)
            else:
                self.last_error = f"Tipo de impresora desconocido: '{ptype}'"
                print(f"[Printer] {self.last_error}")
                return None
        except Exception as e:
            self.last_error = str(e)
            print(f"[Printer] Error al conectar impresora: {e}")
            return None

    def _center(self, text: str) -> str:
        w = self.char_width
        return text.center(w)

    def _divider(self, char="-") -> str:
        return char * self.char_width

    _CARD_TYPE_LABELS = {"credit": "Crédito", "debit": "Débito"}
    _CLIP_STATUS_LABELS = {"approved": "Aprobado", "declined": "Declinado",
                           "cancelled": "Cancelado", "error": "Error", "pending": "Pendiente"}

    def _clip_payment_summary(self, sale: dict) -> Optional[dict]:
        """Datos ya formateados del cobro con terminal Clip (tipo de tarjeta,
        últimos 4 dígitos, banco emisor, estado), o None si la venta no se
        pagó con terminal (efectivo, tarjeta manual, transferencia, mixto).
        Acepta tanto "_clip_payment" (dato en memoria del flujo en vivo del
        POS, ver pos.py) como "clip_payment" (campo de SaleOut al recargar
        una venta ya existente desde el backend, ej. reimpresión en Ventas)."""
        cp = sale.get("_clip_payment") or sale.get("clip_payment")
        if not cp:
            return None
        card_type_raw = (cp.get("card_type") or "").lower()
        last4 = cp.get("last4")
        status_raw = (cp.get("status") or "").lower()
        return {
            "card_type": self._CARD_TYPE_LABELS.get(card_type_raw, cp.get("card_type") or "No disponible"),
            "card_str": f"**** {last4}" if last4 else "No disponible",
            "issuer": cp.get("issuer") or "No disponible",
            "status": self._CLIP_STATUS_LABELS.get(status_raw, (cp.get("status") or "-").capitalize()),
        }

    def print_ticket(self, sale: dict) -> bool:
        """Imprime el ticket de venta en impresora ESC/POS."""
        self._print_to_console(sale)   # siempre a consola

        if not self.enabled:
            return True
        try:
            p = self._get_printer()
            if not p:
                return False

            def ptext(s: str):
                p.text(_sanitize_escpos(s))

            cw  = self.char_width
            sym = self.currency_symbol

            def div(c="-"): return c * cw

            # ── Encabezado ────────────────────────────────────────────────
            p.set(align="center", bold=True, double_height=True, double_width=True)
            ptext(self.store_name + "\n")
            p.set(align="center", bold=False, double_height=False, double_width=False)
            if self.store_address:
                for part in self.store_address.split("|"):
                    ptext(part.strip() + "\n")
            if self.store_phone:
                ptext(f"Tel: {self.store_phone}\n")
            if self.store_tax_id:
                ptext(f"RFC: {self.store_tax_id}\n")

            ptext(div("=") + "\n")

            # ── Folio / Fecha / Cajero ─────────────────────────────────────
            p.set(align="center")
            ptext(f"Folio: {sale.get('folio', '')}\n")
            ptext(f"Fecha: {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}\n")
            cashier = (sale.get("cashier") or {}).get("full_name", "")
            if cashier:
                ptext(f"Cajero: {cashier}\n")
            if sale.get("customer_name"):
                ptext(f"Cliente: {sale['customer_name']}\n")

            p.set(align="left")
            ptext(div() + "\n")

            # ── Artículos ──────────────────────────────────────────────────
            for item in sale.get("items", []):
                name  = item.get("product_name", "")[:cw - 10]
                qty   = float(item.get("quantity", 1))
                price = float(item.get("unit_price", 0))
                disc  = float(item.get("discount_pct", 0))
                sub   = float(item.get("subtotal", 0))
                price_str = f"{sym}{sub:.2f}"
                p.set(bold=False)
                ptext(f"{name:<{cw-len(price_str)}}{price_str}\n")
                qty_str = f"  {qty:.0f} x {sym}{price:.2f}"
                if disc:
                    qty_str += f"  -{disc:.0f}%"
                ptext(qty_str + "\n")

            ptext(div() + "\n")

            # ── Totales ────────────────────────────────────────────────────
            subtotal    = float(sale.get("subtotal", 0))
            tax_amt     = float(sale.get("tax_amount", 0))
            disc_amt    = float(sale.get("discount_amount", 0))
            comm_amt    = float(sale.get("commission_amount", 0) or 0)
            comm_pct    = float(sale.get("commission_pct", 0) or 0)
            total       = float(sale.get("total", 0))
            paid        = float(sale.get("payment_amount", 0))
            change      = float(sale.get("change_amount", 0))
            method      = sale.get("payment_method", "cash")
            method_map = {"cash": "Efectivo", "card": "Tarjeta",
                          "transfer": "Transferencia", "mixed": "Mixto"}

            def total_row(label, value, bold=False, prefix=""):
                val_str = f"{prefix}{sym}{value:.2f}"
                p.set(bold=bold)
                ptext(f"{label:<{cw-len(val_str)}}{val_str}\n")
                p.set(bold=False)

            total_row("Subtotal:", subtotal)
            if self.print_tax and tax_amt > 0:
                total_row(f"{self.tax_name}:", tax_amt)
            if disc_amt > 0:
                total_row("Descuento:", disc_amt, prefix="-")
            if comm_amt:
                total_row(f"Comision {method_map.get(method, method)} ({comm_pct:g}%):",
                          abs(comm_amt), prefix="-" if comm_amt < 0 else "+")
            total_row("TOTAL:", total, bold=True)
            total_row(f"Pago ({method_map.get(method, method)}):", paid)
            if change > 0:
                total_row("Cambio:", change, bold=True)

            clip_summary = self._clip_payment_summary(sale)
            if clip_summary:
                ptext(div() + "\n")
                p.set(bold=True)
                ptext("Terminal Clip\n")
                p.set(bold=False)
                ptext(f"Tipo de tarjeta: {clip_summary['card_type']}\n")
                ptext(f"Tarjeta: {clip_summary['card_str']}\n")
                ptext(f"Banco emisor: {clip_summary['issuer']}\n")
                ptext(f"Estado: {clip_summary['status']}\n")

            # ── Pie ────────────────────────────────────────────────────────
            ptext(div("=") + "\n")
            p.set(align="center")
            ptext(self.footer_text + "\n")

            # ── Código QR (llamado a la acción) ─────────────────────────────
            if self.qr_content:
                p.qr(self.qr_content, size=6, center=True)
                # ptext("\n")
                if self.qr_cta_text:
                    p.set(align="center", bold=True)
                    ptext(self.qr_cta_text + "\n")
                    p.set(align="center", bold=False)

            ptext("\n")
            p.cut()
            p.close()
            return True

        except Exception as e:
            self.last_error = str(e)
            print(f"[Printer] Error al imprimir: {e}")
            return False

    def _build_ticket_lines(self, sale: dict) -> list[str]:
        """Genera las líneas del ticket de venta como lista de strings."""
        cw  = self.char_width
        sym = self.currency_symbol

        def div(c="-"): return c * cw
        def rrow(label, value, prefix=""):
            val = f"{prefix}{sym}{float(value):,.2f}"
            return f"{label:<{cw-len(val)}}{val}"

        lines = [div("="), self._center(self.store_name)]
        if self.store_address:
            for part in self.store_address.split("|"):
                lines.append(self._center(part.strip()))
        if self.store_phone:  lines.append(self._center(f"Tel: {self.store_phone}"))
        if self.store_tax_id: lines.append(self._center(f"RFC: {self.store_tax_id}"))

        lines += [div("="),
                  f"Folio : {sale.get('folio', '')}",
                  f"Fecha : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"]
        if sale.get("customer_name"):
            lines.append(f"Cliente: {sale['customer_name']}")
        lines.append(div())

        # Items
        hdr = f"{'PRODUCTO':<{cw-16}}{'CANT':>4}{'P.UNIT':>6}{'TOTAL':>6}"
        lines += [hdr, div()]
        for item in sale.get("items", []):
            name  = item.get("product_name", "")[:cw - 16]
            qty   = item.get("quantity", 0)
            price = float(item.get("unit_price", 0))
            sub   = float(item.get("subtotal", 0))
            lines.append(f"{name:<{cw-16}}{qty:>4.0f}{price:>6.2f}{sub:>6.2f}")

        subtotal = float(sale.get("subtotal", 0))
        tax      = float(sale.get("tax_amount", 0))
        disc     = float(sale.get("discount_amount", 0))
        total    = float(sale.get("total", 0))
        paid     = float(sale.get("payment_amount", 0))
        change   = float(sale.get("change_amount", 0))
        method   = sale.get("payment_method", "cash")

        lines.append(div())
        lines.append(rrow("Subtotal", subtotal))
        if self.print_tax and tax > 0:
            lines.append(rrow(self.tax_name, tax))
        if disc > 0:
            lines.append(rrow("Descuento", disc, prefix="-"))
        lines.append(rrow("TOTAL", total))
        lines.append(rrow(f"Pago ({method})", paid))
        if change > 0:
            lines.append(rrow("Cambio", change))
        lines += [div("="), self._center(self.footer_text), div("=")]
        return lines

    def _qr_image(self, content: str):
        """Genera la imagen del código QR (PIL.Image) para incrustar en el PDF."""
        try:
            import qrcode
        except ImportError:
            print("[PDF] qrcode no instalado. Ejecuta: pip install qrcode")
            return None
        try:
            qr = qrcode.QRCode(border=1, box_size=8)
            qr.add_data(content)
            qr.make(fit=True)
            return qr.make_image(fill_color="black", back_color="white").convert("RGB")
        except Exception as e:
            print(f"[PDF] Error al generar código QR: {e}")
            return None

    def _sanitize_line(self, line: str) -> str:
        """Convierte una línea a Latin-1 seguro para las fuentes core de fpdf2.
        Reemplaza emojis con equivalentes ASCII y descarta caracteres no codificables."""
        replacements = {
            "💵": "$", "💳": "[T]", "🏦": "[B]", "🔀": "[M]",
            "✅": "OK", "⚠": "!", "↩": "<-", "↑": "^",
            "→": "->", "☐": "[ ]", "✓": "v", "❌": "X",
            "📄": "PDF", "↩": "<-",
        }
        for emoji, repl in replacements.items():
            line = line.replace(emoji, repl)
        # Codificar a Latin-1 (fuentes core de fpdf2); sustituir lo que no entre
        return line.encode("latin-1", errors="replace").decode("latin-1")

    def _lines_to_pdf(self, lines: list[str], filename: str) -> str | None:
        """Convierte líneas de texto a un PDF de recibo y lo abre. Requiere fpdf2."""
        try:
            from fpdf import FPDF
        except ImportError:
            print("[PDF] fpdf2 no instalado. Ejecuta: pip install fpdf2")
            return None

        import tempfile

        safe_lines = [self._sanitize_line(l) for l in lines]

        # Ancho: 88mm para que 48 chars Courier 7pt quepan sin wrapping
        # Courier 7pt: ~1.48mm/char → 48 chars × 1.48 = 71mm < 80mm usable ✓
        line_h = 4        # mm por línea
        mm_w   = 88       # ancho de la página
        margin = 4        # margen izquierdo y derecho
        total_h = max(len(safe_lines) * line_h + margin * 2 + 10, 80)

        pdf = FPDF(unit="mm", format=(mm_w, total_h))
        pdf.set_margins(margin, margin, margin)
        pdf.add_page()
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Courier", size=7)

        for line in safe_lines:
            try:
                # Usar 'text' (parámetro nuevo desde fpdf2 2.7.6)
                pdf.cell(0, line_h, text=line, new_x="LMARGIN", new_y="NEXT")
            except Exception:
                # Si una línea falla, avanzar igual para no perder el resto
                try:
                    pdf.cell(0, line_h, text="", new_x="LMARGIN", new_y="NEXT")
                except Exception:
                    pdf.ln(line_h)

        tmp_path = os.path.join(tempfile.gettempdir(), filename)
        pdf.output(tmp_path)
        self._open_file(tmp_path)
        return tmp_path

    def _open_file(self, path: str):
        """Abre un archivo con el programa predeterminado del SO."""
        import subprocess, sys
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            print(f"[PDF] No se pudo abrir el archivo: {e}")

    def print_ticket_pdf(self, sale: dict) -> str | None:
        """Genera un PDF del ticket de venta con el mismo formato que la vista previa en UI."""
        try:
            from fpdf import FPDF
        except ImportError:
            print("[PDF] fpdf2 no instalado. Ejecuta: pip install fpdf2")
            return None

        import tempfile

        S   = self._sanitize_line
        cur = self.currency_symbol

        # ── Dimensiones ─────────────────────────────────────────────────
        pw, mg = 80, 5          # page width mm, margin
        uw = pw - mg * 2        # usable width = 70mm
        lh, slh = 5, 4          # line-height normal y small

        items       = sale.get("items", [])
        clip_summary = self._clip_payment_summary(sale)
        # Estimar altura de página
        n_rows = (9                          # header
                  + len(items) * 2           # products
                  + 7                        # totals (incl. comisión)
                  + (6 if clip_summary else 0)  # detalles de terminal Clip
                  + 4)                       # footer
        qr_extra_h = 40 if self.qr_content else 0   # título + código QR
        ph = max(n_rows * lh + mg * 2 + 10 + qr_extra_h, 90)

        pdf = FPDF(unit="mm", format=(pw, ph))
        pdf.set_margins(mg, mg, mg)
        pdf.add_page()
        pdf.set_auto_page_break(auto=False)

        # ── Helpers ──────────────────────────────────────────────────────
        def fnt(size=9, bold=False):
            pdf.set_font("Helvetica", style="B" if bold else "", size=size)

        def center(text, size=9, bold=False, h=lh):
            fnt(size, bold)
            pdf.cell(uw, h, text=S(text), align="C", new_x="LMARGIN", new_y="NEXT")

        def lr(left, right, size=9, bold=False, h=lh):
            """Fila con texto a la izquierda y monto a la derecha."""
            fnt(size, bold)
            rw = 28           # columna de montos
            pdf.cell(uw - rw, h, text=S(left), new_x="RIGHT", new_y="TOP")
            pdf.cell(rw, h, text=S(right), align="R", new_x="LMARGIN", new_y="NEXT")

        def hrule(gap_before=1, gap_after=1):
            pdf.ln(gap_before)
            y = pdf.get_y()
            pdf.set_draw_color(180, 180, 180)
            pdf.line(mg, y, pw - mg, y)
            pdf.set_draw_color(0, 0, 0)
            pdf.ln(gap_after)

        def gap(h=2): pdf.ln(h)

        # ── Encabezado ────────────────────────────────────────────────────
        center(self.store_name, size=13, bold=True, h=7)
        if self.store_address:
            for part in self.store_address.split("|"):
                center(part.strip(), size=7, h=4)
        if self.store_phone:
            center(f"Tel: {self.store_phone}", size=7, h=4)
        if self.store_tax_id:
            center(f"RFC: {self.store_tax_id}", size=7, h=4)

        hrule(gap_before=2, gap_after=2)

        # ── Folio / Fecha / Cajero ────────────────────────────────────────
        center(f"Folio: {sale.get('folio', '')}", size=8, h=5)
        center(f"Fecha: {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}", size=8, h=5)
        cashier = (sale.get("cashier") or {}).get("full_name", "")
        if cashier:
            center(f"Cajero: {cashier}", size=8, h=5)
        if sale.get("customer_name"):
            center(f"Cliente: {sale['customer_name']}", size=8, h=5)

        hrule(gap_before=2, gap_after=2)

        # ── Artículos ─────────────────────────────────────────────────────
        for item in items:
            name  = item.get("product_name", "")[:38]
            qty   = float(item.get("quantity", 1))
            price = float(item.get("unit_price", 0))
            disc  = float(item.get("discount_pct", 0))
            sub   = float(item.get("subtotal", 0))
            lr(name, f"{cur}{sub:.2f}", size=9, h=lh)
            qty_txt = f"  {qty:.0f} \xd7 {cur}{price:.2f}"   # × in Latin-1
            if disc:
                qty_txt += f"  -{disc:.0f}%"
            fnt(size=7)
            # pdf.set_text_color(110, 110, 110)
            pdf.cell(uw, slh, text=S(qty_txt), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        hrule(gap_before=2, gap_after=1)

        # ── Totales ───────────────────────────────────────────────────────
        subtotal = float(sale.get("subtotal", 0))
        tax_amt  = float(sale.get("tax_amount", 0))
        disc_amt = float(sale.get("discount_amount", 0))
        comm_amt = float(sale.get("commission_amount", 0) or 0)
        comm_pct = float(sale.get("commission_pct", 0) or 0)
        total    = float(sale.get("total", 0))
        paid     = float(sale.get("payment_amount", 0))
        change   = float(sale.get("change_amount", 0))
        method   = sale.get("payment_method", "cash")
        method_map = {"cash": "Efectivo", "card": "Tarjeta",
                      "transfer": "Transferencia", "mixed": "Mixto"}

        lr("Subtotal:", f"{cur}{subtotal:.2f}", size=8, h=slh)
        if self.print_tax and tax_amt > 0:
            lr(f"{self.tax_name}:", f"{cur}{tax_amt:.2f}", size=8, h=slh)
        if disc_amt > 0:
            lr("Descuento:", f"-{cur}{disc_amt:.2f}", size=8, h=slh)
        if comm_amt:
            sign = "-" if comm_amt < 0 else "+"
            lr(f"Comisión {method_map.get(method, method)} ({comm_pct:g}%):",
               f"{sign}{cur}{abs(comm_amt):.2f}", size=8, h=slh)
        gap(1)
        lr("TOTAL:", f"{cur}{total:.2f}", size=11, bold=True, h=6)
        gap(1)
        lr(f"Pago ({method_map.get(method, method)}):",
           f"{cur}{paid:.2f}", size=8, h=slh)
        if change > 0:
            pdf.set_text_color(0, 130, 0)
            lr("Cambio:", f"{cur}{change:.2f}", size=9, bold=True, h=slh)
            pdf.set_text_color(0, 0, 0)

        if clip_summary:
            hrule(gap_before=2, gap_after=1)
            center("Terminal Clip", size=8, bold=True, h=slh)
            lr("Tipo de tarjeta:", clip_summary["card_type"], size=8, h=slh)
            lr("Tarjeta:", clip_summary["card_str"], size=8, h=slh)
            lr("Banco emisor:", clip_summary["issuer"], size=8, h=slh)
            lr("Estado:", clip_summary["status"], size=8, h=slh)

        hrule(gap_before=2, gap_after=2)

        # ── Pie ───────────────────────────────────────────────────────────
        center(self.footer_text, size=8, h=5)
        gap()

        # ── Código QR (llamado a la acción) ────────────────────────────────
        if self.qr_content:
            qr_img = self._qr_image(self.qr_content)
            if qr_img:
                if self.qr_cta_text:
                    center(self.qr_cta_text, size=9, bold=True, h=5)
                    gap(1)
                qr_size = 28
                pdf.image(qr_img, x=mg + (uw - qr_size) / 2, y=pdf.get_y(), w=qr_size, h=qr_size)
                pdf.set_y(pdf.get_y() + qr_size)
                gap(2)

        folio    = sale.get("folio", "ticket").replace("/", "-")
        tmp_path = os.path.join(tempfile.gettempdir(), f"ticket_{folio}.pdf")
        pdf.output(tmp_path)
        self._open_file(tmp_path)
        return tmp_path

    def print_session_close_pdf(self, session: dict, summary: dict) -> str | None:
        """Genera un PDF del ticket de cierre de caja y lo abre."""
        lines    = self._build_close_lines(session, summary)
        fecha    = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"cierre_caja_{fecha}.pdf"
        return self._lines_to_pdf(lines, filename)

    def open_drawer(self, printer=None) -> bool:
        """Envía el pulso ESC/POS para abrir el cajón de dinero."""
        if not self.open_drawer_enabled:
            self.last_error = "Apertura automática de cajón deshabilitada"
            return False
        if not self.enabled:
            print("[Drawer] Cajón abierto (simulado)")
            return True
        try:
            if printer is None:
                printer = self._get_printer()
            if printer:
                printer.cashdraw(2)   # Pin 2 o Pin 5
                return True
        except Exception as e:
            print(f"[Drawer] Error al abrir cajón: {e}")
        return False

    def _print_to_console(self, sale: dict):
        """Imprime el ticket en consola con el mismo formato que la vista previa."""
        cw  = self.char_width
        sym = self.currency_symbol
        div = lambda c="-": c * cw

        print("\n" + div("="))
        print(self._center(self.store_name))
        if self.store_address:
            for part in self.store_address.split("|"):
                print(self._center(part.strip()))
        if self.store_phone:
            print(self._center(f"Tel: {self.store_phone}"))
        if self.store_tax_id:
            print(self._center(f"RFC: {self.store_tax_id}"))
        print(div("="))
        print(self._center(f"Folio: {sale.get('folio', '')}"))
        print(self._center(f"Fecha: {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}"))
        cashier = (sale.get("cashier") or {}).get("full_name", "")
        if cashier:
            print(self._center(f"Cajero: {cashier}"))
        if sale.get("customer_name"):
            print(self._center(f"Cliente: {sale['customer_name']}"))
        print(div())

        for item in sale.get("items", []):
            name  = item.get("product_name", "")[:cw - 10]
            qty   = float(item.get("quantity", 1))
            price = float(item.get("unit_price", 0))
            disc  = float(item.get("discount_pct", 0))
            sub   = float(item.get("subtotal", 0))
            price_str = f"{sym}{sub:.2f}"
            print(f"{name:<{cw-len(price_str)}}{price_str}")
            qty_str = f"  {qty:.0f} x {sym}{price:.2f}"
            if disc:
                qty_str += f"  -{disc:.0f}%"
            print(qty_str)

        print(div())
        subtotal = float(sale.get("subtotal", 0))
        tax_amt  = float(sale.get("tax_amount", 0))
        disc_amt = float(sale.get("discount_amount", 0))
        comm_amt = float(sale.get("commission_amount", 0) or 0)
        comm_pct = float(sale.get("commission_pct", 0) or 0)
        total    = float(sale.get("total", 0))
        paid     = float(sale.get("payment_amount", 0))
        change   = float(sale.get("change_amount", 0))
        method   = sale.get("payment_method", "cash")
        method_map = {"cash": "Efectivo", "card": "Tarjeta",
                      "transfer": "Transferencia", "mixed": "Mixto"}

        def row(label, val, prefix=""):
            v = f"{prefix}{sym}{val:.2f}"
            print(f"{label:<{cw-len(v)}}{v}")

        row("Subtotal:", subtotal)
        if self.print_tax and tax_amt > 0:
            row(f"{self.tax_name}:", tax_amt)
        if disc_amt > 0:
            row("Descuento:", disc_amt, prefix="-")
        if comm_amt:
            row(f"Comisión {method_map.get(method, method)} ({comm_pct:g}%):",
                abs(comm_amt), prefix="-" if comm_amt < 0 else "+")
        row("TOTAL:", total)
        row(f"Pago ({method_map.get(method, method)}):", paid)
        if change > 0:
            row("Cambio:", change)

        clip_summary = self._clip_payment_summary(sale)
        if clip_summary:
            print(div())
            print("Terminal Clip")
            print(f"Tipo de tarjeta: {clip_summary['card_type']}")
            print(f"Tarjeta: {clip_summary['card_str']}")
            print(f"Banco emisor: {clip_summary['issuer']}")
            print(f"Estado: {clip_summary['status']}")

        print(div("="))
        print(self._center(self.footer_text))
        if self.qr_content:
            if self.qr_cta_text:
                print(self._center(self.qr_cta_text))
            print(self._center(f"[QR] {self.qr_content}"))
        print(div("=") + "\n")

    def _build_close_lines(self, session: dict, summary: dict) -> list[str]:
        """Genera las líneas del ticket de cierre. Usadas tanto para impresora como consola."""
        cw  = self.char_width
        sym = self.currency_symbol
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        reg    = (session.get("register") or {}).get("name", "")
        cajero = (session.get("cashier")  or {}).get("full_name", "")

        def div(c="="):  return c * cw
        def center(t):   return t.center(cw)
        def row(label, value, neg=False):
            val = f"-{sym}{abs(float(value)):,.2f}" if neg else f"{sym}{float(value):,.2f}"
            return f"{label:<{cw-len(val)}}{val}"

        lines = []
        # ── Encabezado ──────────────────────────────────────────────────
        lines += [div(), center(self.store_name)]
        if self.store_address:
            for part in self.store_address.split("|"):
                lines.append(center(part.strip()))
        if self.store_phone:  lines.append(center(f"Tel: {self.store_phone}"))
        if self.store_tax_id: lines.append(center(f"RFC: {self.store_tax_id}"))

        # ── Identificación de sesión ─────────────────────────────────────
        lines += [div(), center("CORTE DEL DÍA"),
                  f"Fecha : {now}", f"Cajero: {cajero}", f"Caja  : {reg}"]

        # ── Resumen global ────────────────────────────────────────────────
        n_ventas = int(summary.get("total_sales", 0))
        lines += [div(),
                  f"{'TOTAL DE VENTAS':<{cw-len(str(n_ventas))}}{n_ventas}",   # entero, sin moneda
                  row("TOTAL DE INGRESOS", summary.get("total_revenue", 0)),
        ]
        if summary.get("total_returned", 0):
            lines.append(row("DEVOLUCIONES", summary["total_returned"], neg=True))

        # ── Métodos de pago ───────────────────────────────────────────────
        lines += [div("-"), center("MÉTODOS DE PAGO")]
        for label, key in [("EFECTIVO",      "cash_revenue"),
                            ("TARJETA",       "card_revenue"),
                            ("TRANSFERENCIA", "transfer_revenue"),
                            ("MIXTO (TOTAL)", "mixed_revenue")]:
            v = summary.get(key, 0)
            if v:
                lines.append(row(label, v))

        # ── Efectivo en caja ──────────────────────────────────────────────
        lines += [div(), center("EFECTIVO EN CAJA"),
                  row("FONDO DE APERTURA",       summary.get("opening_amount", 0)),
                  row("EFECTIVO NETO DE VENTAS", summary.get("cash_net", 0)),
        ]
        if summary.get("cash_in", 0):
            lines.append(row("ENTRADAS MANUALES", summary["cash_in"]))
        if summary.get("cash_out", 0):
            lines.append(row("SALIDAS MANUALES", summary["cash_out"], neg=True))
        lines += [div("-"),
                  row("Efectivo en caja", summary.get("expected_in_register", 0)).rjust(cw)]

        # ── Salidas manuales ──────────────────────────────────────────────
        expenses = summary.get("expense_detail", [])
        if expenses:
            lines += [div(), center("SALIDAS MANUALES")]
            for i, e in enumerate(expenses):
                if i: lines.append(div("-"))
                val = f"-{sym}{e['amount']:,.2f}"
                lines.append(f"{e['time']:<{cw-len(val)}}{val}")
                if e["reason"]:
                    lines.append(e["reason"][:cw])

        # ── Entradas manuales ─────────────────────────────────────────────
        incomes = summary.get("income_detail", [])
        if incomes:
            lines += [div(), center("ENTRADAS MANUALES")]
            for i, e in enumerate(incomes):
                if i: lines.append(div("-"))
                val = f"{sym}{e['amount']:,.2f}"
                lines.append(f"{e['time']:<{cw-len(val)}}{val}")
                if e["reason"]:
                    lines.append(e["reason"][:cw])

        # ── Devoluciones ──────────────────────────────────────────────────
        returns = summary.get("returns_detail", [])
        if returns:
            lines += [div(), center("DEVOLUCIONES")]
            for i, r in enumerate(returns):
                if i: lines.append(div("-"))
                folio_str = f"Venta {r['folio']}"
                lines.append(f"{r['time']:<{cw-len(folio_str)}}{folio_str}")
                for it in r.get("items", []):
                    val = f"-{sym}{it['subtotal']:,.2f}"
                    name = it["name"][:cw-len(val)-1]
                    lines.append(f"{name:<{cw-len(val)}}{val}")
                lines.append(f"Aprobó: {r['supervisor']}")
                lines.append(f"Motivo: {r['reason']}")

        # ── Cancelaciones ─────────────────────────────────────────────────
        cancels = summary.get("cancellations_detail", [])
        if cancels:
            total_cancel = sum(c["total"] for c in cancels)
            lines += [div(), center("CANCELACIONES")]
            for i, c in enumerate(cancels):
                if i: lines.append(div("-"))
                folio_str = f"Venta {c['folio']}"
                lines.append(f"{c['time']:<{cw-len(folio_str)}}{folio_str}")
                for it in c.get("items", []):
                    val = f"-{sym}{it['subtotal']:,.2f}"
                    name = it["name"][:cw-len(val)-1]
                    lines.append(f"{name:<{cw-len(val)}}{val}")
                lines.append(f"Aprobó: {c['supervisor']}")
                lines.append(f"Motivo: {c['reason']}")
            lines.append(div("-"))
            tc = f"Total cancelaciones -{sym}{total_cancel:,.2f}"
            lines.append(tc.rjust(cw))

        lines.append(div())
        return lines

    def print_session_close(self, session: dict, summary: dict) -> bool:
        """Imprime el ticket de cierre en impresora Y en consola."""
        lines = self._build_close_lines(session, summary)

        # ── Siempre imprimir en consola ───────────────────────────────────
        print("\n")
        for line in lines:
            print(line)
        print("\n")

        # ── Imprimir en impresora térmica si está habilitada ─────────────
        if not self.enabled:
            return True
        try:
            p = self._get_printer()
            if not p:
                return False
            for line in lines:
                p.text(_sanitize_escpos(line) + "\n")
            p.text("\n\n\n")
            p.cut()
            p.close()
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"[Printer] Error al imprimir cierre: {e}")
            return False


# Instancia global (se reconfigura con los datos del backend)
printer = TicketPrinter({})
