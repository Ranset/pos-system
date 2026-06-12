# Assets de empaquetado (`flet build`)

Coloca aquí las imágenes que `flet build` usa automáticamente para generar el
ícono de la app y el splash screen. No es necesario declararlas en ningún
archivo de configuración: `flet build` busca estos nombres por convención
dentro de esta carpeta.

## Ícono de la aplicación

| Archivo                  | Uso                                  |
|---------------------------|---------------------------------------|
| `icon.png`                 | Ícono por defecto (todas las plataformas) |
| `icon_windows.png`         | Override solo para Windows (opcional) |
| `icon_macos.png`           | Override solo para macOS (opcional) |
| `icon_android.png`         | Override solo para Android (opcional) |
| `icon_ios.png`              | Override solo para iOS (opcional) |
| `icon_web.png`              | Override solo para Web (opcional) |

Recomendado: PNG cuadrado de **1024x1024**, fondo no transparente (algunas
plataformas no soportan transparencia en el ícono).

## Splash screen

| Archivo                  | Uso                                  |
|---------------------------|---------------------------------------|
| `splash.png`               | Imagen del splash (modo claro), todas las plataformas |
| `splash_dark.png`          | Imagen del splash (modo oscuro), todas las plataformas |
| `splash_windows.png` / `splash_dark_windows.png` | Override solo Windows (opcional) |
| `splash_web.png` / `splash_dark_web.png`         | Override solo Web (opcional) |
| `splash_android.png` / `splash_dark_android.png` | Override solo Android (opcional) |
| `splash_ios.png` / `splash_dark_ios.png`         | Override solo iOS (opcional) |

Recomendado: PNG con fondo **transparente**, logo centrado, ~512x512.
El color de fondo detrás de la imagen se configura con los flags
`--splash-color` / `--splash-dark-color` de `flet build` (ver
[README principal](../../README.md)).

Si no se coloca ninguna imagen, `flet build` usa `icon.png` como fallback
para el splash.
