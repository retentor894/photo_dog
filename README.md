# Photo Dog

Crawl sencillo para descargar imágenes desde galerías tipo Coppermine/Piwigo.

- Soporta páginas `displayimage.php?pid=...&fullsize=1` (Coppermine y similares).
- Soporta páginas `picture.php?/PID[/category/CAT]` (Piwigo) con o sin categoría.
- Extrae la URL de la imagen a partir de `og:image`, `<img>` o enlaces directos a ficheros.
- Descarga con nombre estable por `pid` y adivina la extensión desde la URL o `Content-Type`.

> Sé amable con los servidores: utiliza `--delay` y limita el crawl con `--end` o `--max-misses`.

---

## Instalación rápida

Requisitos: Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U requests beautifulsoup4
```

No hay dependencias adicionales.

---

## Uso

Ejecuta el script principal `photo_dog.py` desde la raíz del repositorio.

```bash
python photo_dog.py --start 100 --end 120
```

Por defecto descarga a `downloads_myphotos/`. Puedes cambiarlo con `--out`.

### Filtros por palabras clave (flexibles)

Puedes filtrar imágenes por términos presentes en la URL o en el nombre del archivo. La coincidencia es flexible: sin mayúsculas ni acentos, separando guiones, subrayados y símbolos.

- `--include`: palabras clave a requerir (se puede repetir o pasar separadas por comas).
- `--exclude`: palabras clave a excluir.
- `--include-any`: si se usa, basta con que coincida cualquiera de `--include` (por defecto, deben coincidir todas).
- `--filter-on`: `url` (ruta completa), `filename` (solo nombre de archivo) o `auto` (por defecto, ruta completa).

Ejemplos basados en URLs tipo wallpaper:

```bash
# Coincidir "John Smith"
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith"

# Coincidir "The Tour" y tamaño "4k" (ambos deben aparecer)
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "The Tour" --include 4k

# Coincidir cualquiera de los términos
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith,The Tour,4k" --include-any

# Filtrar solo por nombre de archivo
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "john smith" --filter-on filename

# Excluir "uhdpaper" pero incluir "4k"
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include 4k --exclude uhdpaper
```

### Dry-run (listar sin descargar)

Si quieres ver qué coincidiría con tus filtros sin descargar nada, usa `--dry-run`.

```bash
# Lista coincidencias (muestra [MATCH] y no descarga)
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith,The Tour,4k" --include-any --dry-run
```

Activa `--verbose` para ver trazas de extracción y filtros (útil para depurar).

#### Caso práctico: URL de wallpaper con strings

Si la imagen final tiene un nombre descriptivo, por ejemplo:

```
https://myphotos.net/wallpaper/john-smith-the-tour-4k-wallpaper-uhdpaper.com-21@3@a.jpg
```

puedes localizarla por sus componentes de texto con filtros sobre el nombre de archivo:

```bash
# Buscar por artista (normaliza guiones/acentos y mayúsculas)
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith" --filter-on filename

# Buscar por título y tamaño (ambos deben aparecer)
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "The Tour" --include 4k --filter-on filename

# Cualquiera de los términos (artista, título o 4k)
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith,The Tour,4k" --include-any --filter-on filename

# Incluir 4k y excluir "uhdpaper"
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include 4k --exclude uhdpaper --filter-on filename

# Previsualizar sin descargar
python photo_dog.py --base https://myphotos.net/picture.php --start 1 --end 500 \
  --include "John Smith,The Tour,4k" --include-any --filter-on filename --dry-run
```

Consejos:
- `--filter-on filename` centra la búsqueda en `.../john-smith-the-tour-4k-...jpg`.
- La normalización elimina acentos, convierte a minúsculas y trata `-`, `_`, `@` y otros como separadores.

### Modo listado (páginas sin pid)

Para páginas que no usan `displayimage.php`/`picture.php` ni `pid`, como `https://myphotos.net/wallpaper/`, usa el modo `list`.
Este modo abre una única página de listado, extrae enlaces a imágenes (`<img src>` y `<a href>` que terminen en `.jpg|png|...`), aplica filtros y descarga.

```bash
# Buscar imágenes en una página de listado, filtrando por nombre de archivo, con trazas
python photo_dog.py --mode list --base https://myphotos.net/wallpaper/ --verbose \
  --include "john smith" --include 4k --filter-on filename --dry-run

# Descargar las coincidencias (quitando --dry-run)
python photo_dog.py --mode list --base https://myphotos.net/wallpaper/ \
  --include "john smith,the tour,4k" --include-any --filter-on filename
```

### Rutas soportadas

- Coppermine (por defecto):
  - Base: `https://myphotos.net/displayimage.php`
  - URL efectiva por PID: `displayimage.php?pid=PID&fullsize=1`

- Piwigo:
  - Base: `https://myphotos.net/picture.php`
  - URL efectiva por PID: `picture.php?/PID`
  - Con categoría/álbum: `picture.php?/PID/category/CATEGORY`

El script autodetecta el formato en función de la ruta base (`displayimage.php` o `picture.php`).

### Ejemplos

- Coppermine básico:
  ```bash
  python photo_dog.py --start 1 --end 50
  ```

- Coppermine con base personalizada:
  ```bash
  python photo_dog.py \
    --base https://example.com/displayimage.php \
    --start 1 --max-misses 25 --delay 1.5
  ```

- Piwigo sin categoría:
  ```bash
  python photo_dog.py \
    --base https://myphotos.net/picture.php \
    --start 189375 --end 189380
  ```

- Piwigo con categoría (como tu ejemplo `.../category/447`):
  ```bash
  python photo_dog.py \
    --base https://myphotos.net/picture.php \
    --start 189375 --end 189380 \
    --category 447
  ```

### Opciones

- `--base`: URL base del visor (por ejemplo, `displayimage.php` o `picture.php`).
- `--start`: PID inicial (incluido).
- `--end`: PID final (incluido). Si se omite, terminará tras demasiados fallos seguidos.
- `--out`: carpeta de salida. Por defecto `downloads_myphotos/`.
- `--delay`: pausa entre peticiones en segundos (sé amable con el servidor). Por defecto `1.0`.
- `--max-misses`: parar tras N fallos consecutivos cuando `--end` no está definido. Por defecto `50`.
- `--category`: solo para `picture.php`, id de categoría/álbum para construir `picture.php?/PID/category/CATEGORY`.

---

## Cómo funciona

- Para cada PID, construye la URL de página según la base:
  - `displayimage.php`: `?pid=PID&fullsize=1`
  - `picture.php`: `?/PID` o `?/PID/category/CATEGORY`
- Si la respuesta es una imagen (cabecera `Content-Type: image/*`), la descarga directamente.
- Si la respuesta es HTML, intenta extraer la URL de la imagen con varias estrategias:
  1) `meta[property="og:image"]`
  2) `<img id="the_image">`, `.display_media`, `.image`, `.img-responsive`, `img`
  3) Cualquier `<a>` que apunte a `*.jpg|png|gif|webp|bmp|tiff`
- Descarga en streaming y adivina la extensión por la URL o `Content-Type`.

Fichero principal: `photo_dog.py`.

---

## Consejos de uso responsable

- Ajusta `--delay` y `--max-misses` para evitar saturar el servidor.
- Revisa y respeta los términos del sitio y `robots.txt`.
- Si el sitio requiere autenticación o cabeceras adicionales, evalúa añadirlas en el código antes de usarlas y no compartas credenciales.

---

## Desarrollo y pruebas

Estructura actual:

- `photo_dog.py`: CLI principal y lógica de crawler.
- `fotos/`: carpeta local de pruebas manuales (opcional, no usada por el código).

Sugerencia futura: separar en paquete `photo_dog/` (p. ej. `crawler.py`, `parsers.py`) y `tests/`.

Instalar dependencias de desarrollo y ejecutar tests (si existen):

```bash
pip install -U pytest
pytest -q
```

Enfoque recomendado de pruebas (cuando se añadan):

- `extract_image_url_from_html`: cubrir páginas con imagen directa, `og:image` y anclas a ficheros.
- `guess_ext`: casos con/ sin extensión en URL y con/ sin `Content-Type`.
- Flujo de `crawl`: simular respuestas con `requests` mockeado.

---

## Solución de problemas

- 403/404 constantes: confirma la URL base y si el servidor bloquea el bot. Prueba aumentando `--delay`.
- Imagen no encontrada en HTML: copia el HTML y verifica si la imagen está en una etiqueta/atributo no contemplado. Puedes abrir un issue con un snippet anonimizando la página.
- Archivos vacíos o incompletos: revisa conectividad y reintenta; el downloader usa streaming con chunks.

---

## Ejemplos de invocación usados en pruebas manuales

- `python photo_dog.py --start 100 --end 120`
- `python photo_dog.py --base https://example.com/displayimage.php --start 1 --max-misses 25 --delay 1.5`
- `python photo_dog.py --base https://myphotos.net/picture.php --start 189375 --end 189380 --category 447`

---

## Aviso

Este proyecto es para fines educativos. Asegúrate de tener permiso para descargar contenido. Respeta las leyes de copyright y las normas del sitio.
