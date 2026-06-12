# 🏪 POS System – Sistema de Punto de Venta

Sistema completo de punto de venta para tiendas físicas, desarrollado con
**Flet + FastAPI + SQLAlchemy + MySQL**.

---

## 📐 Arquitectura

```
Red Local (LAN)
┌─────────────────────────────────────────────────────────────────┐
│                        SERVIDOR                                 │
│  ┌──────────────┐     ┌──────────────────┐    ┌─────────────┐  │
│  │    MySQL 8   │────▶│  FastAPI Backend  │    │  Docker     │  │
│  │   :3306      │     │     :8000         │    │  Compose    │  │
│  └──────────────┘     └──────────────────┘    └─────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ▲                      ▲  HTTP/REST
         │                      │
┌────────┴────────┐    ┌────────┴────────┐    ┌─────────────────┐
│  Caja 1         │    │  Caja 2         │    │  Caja N         │
│  Flet Desktop   │    │  Flet Desktop   │    │  Flet Desktop   │
│  + Ticketera    │    │  + Ticketera    │    │  + Ticketera    │
│  + Cajón $      │    │  + Cajón $      │    │  + Cajón $      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 🚀 Instalación Rápida (Servidor)

### Opción A – Docker Compose (recomendado)

```bash
# 1. Clonar / copiar el proyecto
cd pos-system/

# 2. Levantar MySQL + Backend
docker-compose up -d

# 3. Inicializar configuración por defecto (una sola vez)
curl -X GET http://localhost:8000/api/config/initialize \
     -H "Authorization: Bearer <token_admin>"
```

### Opción B – Instalación manual

```bash
# ── Base de datos ────────────────────────────────────────────────
mysql -u root -p -e "
  CREATE DATABASE pos_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'pos_user'@'%' IDENTIFIED BY 'pos_password';
  GRANT ALL PRIVILEGES ON pos_db.* TO 'pos_user'@'%';
  FLUSH PRIVILEGES;
"
mysql -u pos_user -p pos_db < setup.sql

# ── Backend ──────────────────────────────────────────────────────
cd backend/
cp .env.example .env          # Editar .env con tus datos
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 💻 Instalación del Cliente (cada caja)

```bash
cd frontend/
cp .env.example .env
# Editar .env: cambiar la IP del servidor
# API_BASE_URL=http://192.168.1.100:8000/api

pip install -r requirements.txt

# Modo escritorio (recomendado para POS)
flet run main.py

# Modo web (acceso desde navegador)
flet run --web --port 8080 main.py
```

---

## 📦 Empaquetado del cliente (flet build)

Para generar un ejecutable de escritorio (`.exe` en Windows) con ícono y splash screen propios:

1. Coloca las imágenes en `frontend/assets/` (ver [`frontend/assets/README.md`](frontend/assets/README.md) para los nombres de archivo y tamaños recomendados).
2. Ejecuta el build desde `frontend/`:

```bash
cd frontend/
flet build windows ^
  --product "POS System" ^
  --org "com.miempresa" ^
  --company "Mi Empresa" ^
  --copyright "Copyright (c) 2026 Mi Empresa" ^
  --splash-color "#121212" ^
  --splash-dark-color "#121212"
```

El ejecutable queda en `frontend/build/windows/`.

---

## 🔑 Acceso inicial

| Campo    | Valor    |
|----------|----------|
| Usuario  | `admin`  |
| Contraseña | `admin123` |

> ⚠️ **Cambia la contraseña inmediatamente** tras el primer inicio de sesión.

---

## 👥 Roles y Permisos

| Función                     | Cajero | Gerente | Admin |
|-----------------------------|:------:|:-------:|:-----:|
| Registrar ventas            | ✅     | ✅      | ✅    |
| Abrir/cerrar caja           | ✅     | ✅      | ✅    |
| Ver productos               | ✅     | ✅      | ✅    |
| Gestionar productos         | ❌     | ✅      | ✅    |
| Ajustar inventario          | ❌     | ✅      | ✅    |
| Cancelar ventas             | ❌     | ✅      | ✅    |
| Movimientos de caja         | ❌     | ✅      | ✅    |
| Ver reportes                | ❌     | ✅      | ✅    |
| Ver resumen de ventas       | ❌     | ✅      | ✅    |
| Gestionar usuarios          | ❌     | ❌      | ✅    |
| Configuración del sistema   | ❌     | ❌      | ✅    |

---

## 🎹 Atajos de teclado (Flet Desktop)

| Atajo     | Acción         |
|-----------|----------------|
| `Ctrl+1`  | Punto de Venta |
| `Ctrl+2`  | Caja           |
| `Ctrl+3`  | Productos      |
| `Ctrl+4`  | Inventario     |
| `Ctrl+5`  | Usuarios       |
| `Ctrl+6`  | Reportes       |
| `Ctrl+7`  | Configuración  |
| `Ctrl+8`  | Ventas         |

---

## 🖨️ Configuración de Impresora Térmica

### USB (más común)
1. Ve a **Configuración → Impresora y Cajón**
2. Tipo: `USB`
3. Obtén los IDs con:
   ```bash
   # Linux/macOS
   lsusb
   # Windows: Administrador de dispositivos → Dispositivos USB
   ```
4. Ingresa `Vendor ID` y `Product ID` en formato hex (ej: `0x0416`)

### Red (TCP/IP)
1. Tipo: `Red (TCP/IP)`
2. Ingresa la IP de la impresora y el puerto (generalmente `9100`)

### Cajón de dinero
- Requiere que el cajón esté conectado a la impresora (cable RJ11)
- Activa **"Abrir cajón automáticamente"** en la configuración

---

## 📊 API REST

Documentación interactiva disponible en:
- **Swagger UI:** `http://<servidor>:8000/docs`
- **ReDoc:** `http://<servidor>:8000/redoc`

### Endpoints principales

```
POST   /api/auth/login              – Iniciar sesión
GET    /api/products/               – Listar productos
GET    /api/products/barcode/{code} – Buscar por código
POST   /api/sales/                  – Registrar venta
POST   /api/cash/open               – Abrir caja
POST   /api/cash/sessions/{id}/close – Cerrar caja
GET    /api/reports/daily           – Reporte diario
GET    /api/config/map              – Configuración actual
```

---

## 🗂️ Estructura del proyecto

```
pos-system/
├── backend/                    # Servidor FastAPI
│   ├── app/
│   │   ├── main.py             # App FastAPI + startup
│   │   ├── config.py           # Settings (pydantic)
│   │   ├── database.py         # SQLAlchemy engine
│   │   ├── models/__init__.py  # Todos los modelos ORM
│   │   ├── schemas/__init__.py # Todos los schemas Pydantic
│   │   ├── routers/            # Endpoints por módulo
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── products.py
│   │   │   ├── sales.py
│   │   │   ├── cash.py
│   │   │   ├── reports.py
│   │   │   └── settings.py
│   │   └── services/           # Lógica de negocio
│   │       ├── auth.py         # JWT, bcrypt, permisos
│   │       └── reports.py      # Cálculo de reportes
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/                   # Cliente Flet
│   ├── main.py                 # Punto de entrada + navegación
│   ├── config.py               # Colores y constantes UI
│   ├── services/
│   │   ├── api.py              # Cliente HTTP (httpx)
│   │   └── printer.py          # ESC/POS + cajón de dinero
│   ├── views/                  # Una vista por módulo
│   │   ├── login.py
│   │   ├── pos.py              # Pantalla de ventas
│   │   ├── products.py
│   │   ├── inventory.py
│   │   ├── users.py
│   │   ├── cash.py
│   │   ├── reports.py
│   │   └── settings.py
│   ├── components/
│   │   └── nav_rail.py         # Barra lateral de navegación
│   ├── requirements.txt
│   └── .env.example
├── docker-compose.yml
├── setup.sql                   # Datos iniciales
└── README.md
```

---

## 🔧 Tecnologías

| Capa        | Tecnología              | Versión  |
|-------------|-------------------------|----------|
| Frontend    | Flet (Flutter/Python)   | 0.21.x   |
| Backend     | FastAPI                 | 0.104.x  |
| ORM         | SQLAlchemy              | 2.0.x    |
| Base datos  | MySQL                   | 8.0      |
| Auth        | JWT (python-jose)       | 3.3.x    |
| Passwords   | bcrypt (passlib)        | 1.7.x    |
| HTTP client | httpx                   | 0.25.x   |
| Impresora   | python-escpos           | 3.0a8    |
| Container   | Docker + Compose        | latest   |

---

## 🛡️ Seguridad en producción

```bash
# 1. Cambiar claves en backend/.env
SECRET_KEY=<clave-aleatoria-de-64-caracteres>
DB_PASSWORD=<password-seguro>

# 2. Restringir CORS en backend/app/main.py
allow_origins=["http://192.168.1.0/24"]  # Solo tu red local

# 3. Firewall: solo exponer puerto 8000 en la red local
# 4. Usar HTTPS con un proxy (nginx) si se accede desde internet
```

---

## 📞 Soporte

Para reportar bugs o sugerencias, consulta la documentación de la API
en `http://<servidor>:8000/docs`.
