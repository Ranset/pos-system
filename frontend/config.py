"""
Configuración del cliente Flet (Frontend)
"""
import os
import json
from dotenv import load_dotenv
import appdirs

load_dotenv()

APP_VERSION: str = "1.4.1"
APP_TITLE: str = f"CM Cash v{APP_VERSION}"

# Archivo donde se guarda la dirección del servidor configurada desde la UI.
# Tiene prioridad sobre API_BASE_URL del .env una vez que el usuario la cambia.
_CONFIG_DIR = appdirs.user_data_dir(APP_TITLE, False)
_SERVER_CONFIG_FILE = os.path.join(_CONFIG_DIR, "server_config.json")

# Archivo donde se guarda la configuración de Impresora y Cajón de ESTE equipo.
# Cada caja registradora (computadora) tiene su propia impresora/cajón conectados
# físicamente, por lo que esta configuración es local y no se comparte vía backend.
_PRINTER_CONFIG_FILE = os.path.join(_CONFIG_DIR, "printer_config.json")


def get_default_api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000/api")


def load_api_base_url() -> str:
    try:
        with open(_SERVER_CONFIG_FILE, "r", encoding="utf-8") as f:
            url = json.load(f).get("api_base_url")
            if url:
                return url
    except (OSError, ValueError):
        pass
    return get_default_api_base_url()


def save_api_base_url(url: str) -> None:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_SERVER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"api_base_url": url}, f)


def load_printer_config() -> dict:
    """Lee la configuración de Impresora y Cajón guardada localmente para esta caja."""
    try:
        with open(_PRINTER_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_printer_config(values: dict) -> None:
    """Guarda la configuración de Impresora y Cajón de esta caja en disco."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_PRINTER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f)


API_BASE_URL: str = load_api_base_url()

# Colores del tema
PRIMARY     = "#1565C0"
PRIMARY_LT  = "#1E88E5"
SECONDARY   = "#00897B"
BG_DARK     = "#121212"
BG_CARD     = "#1E1E1E"
BG_SURFACE  = "#2C2C2C"
TEXT_MAIN   = "#FFFFFF"
TEXT_SUB    = "#B0B0B0"
SUCCESS     = "#4CAF50"
ERROR       = "#F44336"
WARNING     = "#FFC107"
