from escpos.printer import Network, Usb
import socket
import unicodedata

def sanitizar_texto(texto):
    """
    Funcion para convertir texto con caracteres latinos (tildes, enes, etc.)
    a caracteres ASCII compatibles y seguros para la impresora termica.
    Ejemplo: 'Impresion' (con tilde) se convierte en 'Impresion'.
    """
    # Normaliza el texto separando los caracteres base de sus diacriticos
    texto_normalizado = unicodedata.normalize('NFKD', texto)
    
    # Codifica a ASCII ignorando los caracteres que no tienen traduccion directa
    # (como signos de exclamacion invertidos) y lo devuelve como string
    texto_limpio = texto_normalizado.encode('ascii', 'ignore').decode('utf-8')
    
    return texto_limpio

def test_printer_red():
    try:
        # Usamos la inicialización limpia sin pasar un profile inválido
        p = Network("192.168.1.85", port=9100)

        p.set(align='center', font='a', width=2, height=2, bold=True)
        p.text(sanitizar_texto("PRUEBA DE IMPRESORA\n"))

        p.set(align='left', font='a', width=1, height=1, bold=False)
        p.text("--------------------------------\n")
        p.text(sanitizar_texto("Tamaño de texto\n"))
        p.text("--------------------------------\n")

        p.set(align='center')
        
        # 2. Enviamos el texto. Al haber configurado charcode('PC850'), 
        # la librería codificará las tildes de forma nativa para la impresora.
        p.text(sanitizar_texto("¡Impresión ok!\n"))

        p.cut()
        
    except (socket.timeout, socket.error) as e:
        print("Error de conexión con la impresora:", e)
    except Exception as e:
        print("Error al imprimir:", e)

def test_printer_usb():

    p = Usb(0x04B8, 0x118A)

    p.set(align='center', bold=True, width=2, height=2)
    p.text("SUPERMERCADO\n")

    p.set(align='center')
    p.text("Av. Principal 123\n")
    p.text("Tel: 998-123-4567\n\n")

    p.set(align='left')
    p.text("--------------------------------\n")
    p.text("Leche           2 x 30.00\n")
    p.text("Pan             1 x 25.00\n")
    p.text("Huevos          1 x 58.00\n")
    p.text("--------------------------------\n")

    p.set(align='right', bold=True)
    p.text("TOTAL: $143.00\n\n")

    p.set(align='center')
    p.qr("https://mitienda.com")
    p.text("\nGracias por su compra\n")

    p.cut()

def test_printer_usb_2():
    from escpos.printer import Win32Raw

    p = Win32Raw("EPSON L3250 Series")

    p.text("Hola mundo\n")
    p.cut()

def test_printer_usb_3():
    import win32print

    printer_name = "EPSON L3250 Series"

    hprinter = win32print.OpenPrinter(printer_name)

    try:
        job = win32print.StartDocPrinter(hprinter, 1, ("Prueba", None, "RAW"))
        win32print.StartPagePrinter(hprinter)

        data = (
            b"\x1b\x40"          # Inicializar impresora
            b"Hola Mundo\r\n"
            b"Prueba ESC/POS\r\n"
            b"\r\n\r\n"
            b"\x1d\x56\x00"      # Corte
        )

        win32print.WritePrinter(hprinter, data)

        win32print.EndPagePrinter(hprinter)
        win32print.EndDocPrinter(hprinter)

    finally:
        win32print.ClosePrinter(hprinter)

if __name__ == "__main__":
    # test_printer_red()
    # test_printer_usb()
    # test_printer_usb_2()
    test_printer_usb_3()