#!/usr/bin/env python3
import argparse
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DEFAULT_BASE = "https://myphotos.net/displayimage.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GalleryCrawler/1.0; +https://example.org/bot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

IMG_EXT_FROM_CTYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE)
    return name.strip("._") or "file"

def guess_ext(url: str, content_type: str | None) -> str:
    # 1) Try extension from URL
    path = urllib.parse.urlparse(url).path
    if "." in path:
        ext = path[path.rfind(".") :].lower()
        if len(ext) <= 6 and all(c.isalnum() or c in "._" for c in ext):
            return ext
    # 2) From content-type
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in IMG_EXT_FROM_CTYPE:
            return IMG_EXT_FROM_CTYPE[ct]
    return ".jpg"

def is_image_response(resp: requests.Response) -> bool:
    ct = resp.headers.get("Content-Type", "")
    return ct.lower().startswith("image/")

def extract_image_url_from_html(html: str, page_url: str) -> str | None:
    """
    Intenta múltiples estrategias típicas de galerías Coppermine/displayimage:
    - <meta property="og:image" content="...">
    - <a id="og_fullsize" href="..."><img ...></a>
    - <img id="the_image" src="..."> (u otros <img> grandes)
    - Cualquier <img> cuya ruta parezca de 'albums/' o contenga extensiones de imagen
    Devuelve URL absoluta si encuentra algo.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) og:image
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og and og.get("content"):
        return urllib.parse.urljoin(page_url, og["content"])

    # 2) imágenes obvias
    candidates = []

    # Por id/clase conocidos
    for sel in ["#the_image", ".display_media", ".image", ".img-responsive", "img"]:
        for img in soup.select(sel):
            src = img.get("src")
            if src:
                candidates.append(src)

    # 3) filtrar por patrón típico
    img_like = []
    for src in candidates:
        if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|tiff)(\?.*)?$", src, re.I):
            img_like.append(src)
        elif "albums/" in src or "fullsize" in src:
            img_like.append(src)

    # Prioriza la que parezca más grande (heurística)
    for src in img_like:
        return urllib.parse.urljoin(page_url, src)

    # 4) como último recurso, busca <a> que apunten a imagen
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|tiff)(\?.*)?$", href, re.I):
            return urllib.parse.urljoin(page_url, href)

    return None

def fetch(url: str, session: requests.Session, stream: bool = False) -> requests.Response | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True, stream=stream)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (403, 404):
            return None
        # Otros códigos: considera como fallo recuperable
        return None
    except requests.RequestException:
        return None

def download_image(img_url: str, out_dir: Path, filename_stem: str, session: requests.Session) -> bool:
    # HEAD para conocer content-type/size (si lo permite)
    head_ok = False
    try:
        h = session.head(img_url, headers=HEADERS, timeout=20, allow_redirects=True)
        if h.status_code == 200:
            head_ok = True
            content_type = h.headers.get("Content-Type", "")
        else:
            content_type = None
    except requests.RequestException:
        content_type = None

    ext = guess_ext(img_url, content_type)
    fname = sanitize_filename(f"{filename_stem}{ext}")
    path = out_dir / fname
    if path.exists():
        return True  # ya descargado

    resp = fetch(img_url, session=session, stream=True)
    if not resp:
        return False

    # Si el servidor no devolvió content-type antes, vuelve a inferir
    if not head_ok:
        content_type = resp.headers.get("Content-Type")

    # Guarda a disco en stream
    try:
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 15):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        try:
            if path.exists():
                path.unlink(missing_ok=True)
        except Exception:
            pass
        return False

def build_page_url(base_url: str, pid: int, category: int | None) -> str:
    """Builds the per-image page URL based on the base route.

    Supports:
    - Coppermine style: displayimage.php?pid=PID&fullsize=1
    - Piwigo style: picture.php?/PID[/category/CAT]
    """
    lower = base_url.lower()
    if "displayimage.php" in lower:
        return f"{base_url}?pid={pid}&fullsize=1"
    if "picture.php" in lower:
        if category is not None:
            return f"{base_url}?/{pid}/category/{category}"
        return f"{base_url}?/{pid}"
    # Fallback: assume displayimage semantics
    return f"{base_url}?pid={pid}&fullsize=1"


def crawl(
    base_url: str,
    start_pid: int,
    end_pid: int | None,
    out: str,
    delay: float,
    max_misses: int,
    category: int | None,
):
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    misses = 0
    pid = start_pid
    total_ok = 0
    total_seen = 0

    while True:
        if end_pid is not None and pid > end_pid:
            break

        page_url = build_page_url(base_url, pid, category)
        total_seen += 1

        resp = fetch(page_url, session=session, stream=False)
        if resp and is_image_response(resp):
            # La URL devuelve directamente una imagen
            ok = download_image(page_url, out_dir, f"pid_{pid}", session)
        elif resp:
            # Es HTML: extrae la URL real de la imagen
            html = resp.text
            img_url = extract_image_url_from_html(html, page_url)
            if img_url:
                ok = download_image(img_url, out_dir, f"pid_{pid}", session)
            else:
                ok = False
        else:
            ok = False

        if ok:
            print(f"[OK] pid={pid}")
            total_ok += 1
            misses = 0
        else:
            print(f"[MISS] pid={pid}")
            misses += 1

        # Parada temprana si todo parece vacío desde aquí
        if end_pid is None and misses >= max_misses:
            print(f"Demasiados MISS seguidos ({misses}). Deteniendo crawl.")
            break

        pid += 1
        if delay > 0:
            time.sleep(delay)

    print(f"\nHecho. Vistos: {total_seen} | Descargados: {total_ok}")

def main():
    ap = argparse.ArgumentParser(
        description="Descarga imágenes de una galería tipo displayimage.php?pid=...&fullsize=1"
    )
    ap.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=(
            "URL base del visor (por ejemplo, displayimage.php o picture.php). "
            "Se auto-detecta el formato: Coppermine (displayimage) o Piwigo (picture)."
        ),
    )
    ap.add_argument("--start", type=int, required=True, help="PID inicial (incluido)")
    ap.add_argument("--end", type=int, default=None, help="PID final (incluido). Si se omite, se detiene tras demasiados miss.")
    ap.add_argument("--out", default="downloads_myphotos", help="Carpeta de salida")
    ap.add_argument("--delay", type=float, default=1.0, help="Pausa entre peticiones en segundos (sé amable con el servidor)")
    ap.add_argument("--max-misses", type=int, default=50, help="Parar tras N fallos consecutivos si --end no está definido")
    ap.add_argument(
        "--category",
        type=int,
        default=None,
        help=(
            "Solo para picture.php: id de categoría/álbum a incluir en la URL "
            "(formato: picture.php?/PID/category/CATEGORY)."
        ),
    )
    args = ap.parse_args()

    crawl(
        base_url=args.base,
        start_pid=args.start,
        end_pid=args.end,
        out=args.out,
        delay=args.delay,
        max_misses=args.max_misses,
        category=args.category,
    )

if __name__ == "__main__":
    main()
