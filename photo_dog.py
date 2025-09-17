#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
import urllib.parse
import unicodedata
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

def extract_image_url_from_html(html: str, page_url: str, verbose: bool = False) -> str | None:
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
        url = urllib.parse.urljoin(page_url, og["content"])
        if verbose:
            print(f"[DBG] og:image -> {url}")
        return url

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
        url = urllib.parse.urljoin(page_url, src)
        if verbose:
            print(f"[DBG] img candidate -> {url}")
        return url

    # 4) como último recurso, busca <a> que apunten a imagen
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|tiff)(\?.*)?$", href, re.I):
            url = urllib.parse.urljoin(page_url, href)
            if verbose:
                print(f"[DBG] anchor image -> {url}")
            return url

    return None


def normalize_for_match(text: str) -> str:
    """Normaliza texto para coincidencia flexible.

    - Decodifica %XX de URLs
    - Pasa a minúsculas
    - Quita acentos/diacríticos
    - Sustituye no alfanuméricos por espacios y colapsa espacios
    """
    if not text:
        return ""
    # Decodifica path/url encoded
    text = urllib.parse.unquote(text)
    # Minúsculas
    text = text.lower()
    # Quita diacríticos
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Sustituye no alfanuméricos por espacio
    text = re.sub(r"[^0-9a-z]+", " ", text)
    # Colapsa espacios
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_keywords(values: list[str]) -> list[str]:
    """Despliega listas separadas por comas y normaliza cada término."""
    out: list[str] = []
    for v in values or []:
        if not v:
            continue
        parts = [p.strip() for p in v.split(",")]
        for p in parts:
            n = normalize_for_match(p)
            if n:
                out.append(n)
    return out


def eval_keywords(img_url: str, includes: list[str], excludes: list[str], any_mode: bool, target: str):
    """Evalúa filtros y devuelve (ok, reason, normalized, hits, required, excluded_token)."""
    parsed = urllib.parse.urlparse(img_url)
    if target == "filename":
        base = os.path.basename(parsed.path)
    else:  # "url" o "auto"
        base = parsed.path

    norm = normalize_for_match(base)

    # Excludes
    for ex in excludes:
        if ex and ex in norm:
            return False, f"excluded: {ex}", norm, 0, len(includes), ex

    # Includes
    if includes:
        hits = sum(1 for inc in includes if inc in norm)
        if any_mode:
            ok = hits >= 1
            return ok, ("ok" if ok else f"no-include-any (hits={hits}/1)"), norm, hits, 1, None
        else:
            ok = hits == len(includes)
            return ok, ("ok" if ok else f"missing-includes (hits={hits}/{len(includes)})"), norm, hits, len(includes), None
    return True, "ok", norm, 0, 0, None


def matches_keywords(img_url: str, includes: list[str], excludes: list[str], any_mode: bool, target: str) -> bool:
    """Comprueba si `img_url` cumple filtros include/exclude sobre `url` o `filename`.

    - includes vacío: no requiere nada (pasa salvo que excluya)
    - excludes: si alguno aparece, falla
    - any_mode: si True, basta con que aparezca alguno de `includes`; si False, deben aparecer todos
    """
    ok, _, _, _, _, _ = eval_keywords(img_url, includes, excludes, any_mode, target)
    return ok

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
    include: list[str],
    exclude: list[str],
    include_any: bool,
    filter_on: str,
    dry_run: bool,
    verbose: bool,
):
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    misses = 0
    pid = start_pid
    total_ok = 0
    total_seen = 0

    # Preprocesa filtros una vez
    include_norm = parse_keywords(include)
    exclude_norm = parse_keywords(exclude)

    while True:
        if end_pid is not None and pid > end_pid:
            break

        page_url = build_page_url(base_url, pid, category)
        total_seen += 1

        resp = fetch(page_url, session=session, stream=False)
        if resp and verbose:
            print(f"[DBG] GET {page_url} -> {resp.status_code} ctype={resp.headers.get('Content-Type','')}")
        skipped = False
        if resp and is_image_response(resp):
            # La URL devuelve directamente una imagen
            candidate_url = page_url
            ok2, reason, norm, hits, need, _ = eval_keywords(
                candidate_url, include_norm, exclude_norm, include_any, "filename" if filter_on == "filename" else "url"
            )
            if not ok2:
                print(f"[SKIP] pid={pid} (filtro) {reason}")
                if verbose:
                    print(f"[DBG] target='{candidate_url}' norm='{norm}' hits={hits}/{need}")
                ok = False
                skipped = True
            else:
                if dry_run:
                    print(f"[MATCH] pid={pid} -> {candidate_url}")
                    if verbose:
                        print(f"[DBG] norm='{norm}'")
                    ok = True
                else:
                    ok = download_image(candidate_url, out_dir, f"pid_{pid}", session)
        elif resp:
            # Es HTML: extrae la URL real de la imagen
            html = resp.text
            img_url = extract_image_url_from_html(html, page_url, verbose=verbose)
            if img_url:
                ok2, reason, norm, hits, need, _ = eval_keywords(
                    img_url, include_norm, exclude_norm, include_any, "filename" if filter_on == "filename" else "url"
                )
                if not ok2:
                    print(f"[SKIP] pid={pid} (filtro) {reason}")
                    if verbose:
                        print(f"[DBG] target='{img_url}' norm='{norm}' hits={hits}/{need}")
                    ok = False
                    skipped = True
                else:
                    if dry_run:
                        print(f"[MATCH] pid={pid} -> {img_url}")
                        if verbose:
                            print(f"[DBG] norm='{norm}'")
                        ok = True
                    else:
                        ok = download_image(img_url, out_dir, f"pid_{pid}", session)
            else:
                if verbose:
                    print(f"[DBG] No se pudo extraer imagen de {page_url}")
                ok = False
        else:
            ok = False

        if ok:
            if dry_run:
                print(f"[OK-DRY] pid={pid}")
            else:
                print(f"[OK] pid={pid}")
            total_ok += 1
            misses = 0
        elif skipped:
            # No cuenta como miss al ser un descarte intencional
            pass
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


def crawl_list_page(
    base_url: str,
    out: str,
    delay: float,
    include: list[str],
    exclude: list[str],
    include_any: bool,
    filter_on: str,
    dry_run: bool,
    verbose: bool,
):
    """Crawl de una sola página de listado (sin pid), extrayendo y filtrando imágenes.

    Útil para rutas como `https://myphotos.net/wallpaper/` que listan imágenes o enlazan a ellas.
    """
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    include_norm = parse_keywords(include)
    exclude_norm = parse_keywords(exclude)

    resp = fetch(base_url, session=session, stream=False)
    if not resp:
        print(f"[ERR] No se pudo abrir la página: {base_url}")
        return
    else:
        if verbose:
            print(f"[DBG] GET {base_url} -> {resp.status_code} ctype={resp.headers.get('Content-Type','')}")

    if is_image_response(resp):
        # La URL base ya es una imagen; trátala como único candidato
        candidates = [base_url]
        if verbose:
            print("[DBG] Página base devuelve imagen directa")
    else:
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        hrefs = set()
        n_imgs = 0
        n_as = 0
        # <img src>
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                hrefs.add(urllib.parse.urljoin(base_url, src))
                n_imgs += 1
        # <a href>
        for a in soup.find_all("a", href=True):
            hrefs.add(urllib.parse.urljoin(base_url, a["href"]))
            n_as += 1

        # Filtra a extensiones de imagen conocidas
        candidates = [
            h for h in hrefs if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|tiff)(\?.*)?$", h, re.I)
        ]
        if verbose:
            print(
                f"[DBG] img-tags={n_imgs} a-tags={n_as} hrefs-unicos={len(hrefs)} candidatos={len(candidates)}"
            )
            for u in sorted(candidates)[:5]:
                print(f"       - {u}")

    total = len(candidates)
    matched = 0
    downloaded = 0

    for idx, url in enumerate(sorted(candidates)):
        ok2, reason, norm, hits, need, _ = eval_keywords(
            url, include_norm, exclude_norm, include_any, "filename" if filter_on == "filename" else "url"
        )
        if not ok2:
            print(f"[SKIP] {url} ({reason})")
            if verbose:
                print(
                    f"[DBG] target='{os.path.basename(urllib.parse.urlparse(url).path) if filter_on=='filename' else urllib.parse.urlparse(url).path}' norm='{norm}' hits={hits}/{need}"
                )
            continue
        matched += 1
        if dry_run:
            print(f"[MATCH] {url}")
        else:
            if verbose:
                print(f"[DBG] Descargando {url}")
            if download_image(url, Path(out), f"list_{idx:05d}", session):
                print(f"[OK] {url}")
                downloaded += 1
            else:
                print(f"[MISS] {url}")
        if delay > 0:
            time.sleep(delay)

    print(f"\nHecho (list-mode). Encontrados: {total} | Coinciden: {matched} | Descargados: {downloaded}")

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
    ap.add_argument("--start", type=int, required=False, default=None, help="PID inicial (incluido)")
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
    ap.add_argument(
        "--include",
        action="append",
        default=[],
        help=(
            "Palabras clave a incluir (repetible o separadas por comas). "
            "Coincidencia flexible sobre URL/filename, sin mayúsculas/acentos."
        ),
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "Palabras clave a excluir (repetible o separadas por comas)."
        ),
    )
    ap.add_argument(
        "--include-any",
        action="store_true",
        help="Si se indica, basta con que coincida cualquiera de las keywords de --include.",
    )
    ap.add_argument(
        "--filter-on",
        choices=["auto", "url", "filename"],
        default="auto",
        help=(
            "Dónde aplicar los filtros: 'url' usa la ruta completa; 'filename' solo el nombre de archivo; "
            "'auto' usa la ruta (por defecto)."
        ),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista coincidencias sin descargar archivos",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Muestra trazas detalladas (peticiones, extracción, filtros)",
    )
    ap.add_argument(
        "--mode",
        choices=["auto", "list"],
        default="auto",
        help=(
            "Modo de funcionamiento: 'auto' usa pid y detecta displayimage/picture; "
            "'list' explora una sola página de listado (sin pid), extrayendo enlaces a imágenes."
        ),
    )
    args = ap.parse_args()

    if args.mode == "list":
        crawl_list_page(
            base_url=args.base,
            out=args.out,
            delay=args.delay,
            include=args.include,
            exclude=args.exclude,
            include_any=args.include_any,
            filter_on=args.filter_on,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        return

    if args.start is None:
        print("Error: --start es obligatorio en modo 'auto' (usa --mode list para páginas sin pid).", file=sys.stderr)
        sys.exit(2)

    crawl(
        base_url=args.base,
        start_pid=args.start,
        end_pid=args.end,
        out=args.out,
        delay=args.delay,
        max_misses=args.max_misses,
        category=args.category,
        include=args.include,
        exclude=args.exclude,
        include_any=args.include_any,
        filter_on=args.filter_on,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

if __name__ == "__main__":
    main()
