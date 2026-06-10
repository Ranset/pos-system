from escpos.printer import Network
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
