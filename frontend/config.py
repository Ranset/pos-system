"""
Configuración del cliente Flet (Frontend)
"""
import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000/api")
APP_VERSION: str = "1.0.0"
APP_TITLE: str = "POS System"

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
