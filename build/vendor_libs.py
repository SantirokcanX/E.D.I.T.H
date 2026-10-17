"""Copia local de las librerías de la interfaz (Fase 14): versiones fijas, sin CDN y con huella verificada.

Uso:  python build/vendor_libs.py        (descarga a ide/static/vendor/ y escribe MANIFEST.json)
      python build/vendor_libs.py --check (solo comprueba que lo que hay en disco coincide con el manifiesto)

Cada archivo se baja de cdn.jsdelivr.net y su SHA-256 se compara con el que publica la API de jsdelivr
para ese paquete y versión: si no coincide, no se guarda. Con todo en local, EDITH funciona sin internet
y la interfaz puede usar una Content-Security-Policy estricta (script-src 'self').
"""

import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "ide" / "static" / "vendor"

# (paquete npm, versión, [(ruta en el paquete, destino dentro de vendor/)])
# marked: la URL sin versión de antes servía la 15.0.12 (última con marked.min.js en la raíz).
LIBS = [
    ("marked", "15.0.12", [("marked.min.js", "marked/marked.min.js")]),
    ("dompurify", "3.4.16", [("dist/purify.min.js", "dompurify/purify.min.js")]),
    ("katex", "0.16.11", [("dist/katex.min.js", "katex/katex.min.js"), ("dist/katex.min.css", "katex/katex.min.css"),
                          ("dist/fonts/*.woff2", "katex/fonts/")]),
    ("@highlightjs/cdn-assets", "11.9.0", [("highlight.min.js", "highlight/highlight.min.js"),
                                           ("styles/github-dark.min.css", "highlight/github-dark.min.css")]),
    ("mermaid", "10.9.8", [("dist/mermaid.min.js", "mermaid/mermaid.min.js")]),
    ("chart.js", "4.5.1", [("dist/chart.umd.min.js", "chart/chart.umd.min.js")]),
    ("@fontsource/plus-jakarta-sans", "5.3.0",
     [(f"files/plus-jakarta-sans-latin-{w}-normal.woff2", "fonts/") for w in (300, 400, 500, 600, 700)]),
    ("@fontsource/fira-code", "5.3.0", [(f"files/fira-code-latin-{w}-normal.woff2", "fonts/") for w in (400, 500, 600)]),
]

FONTS_CSS = """/* Fuentes de la interfaz, copia local (@fontsource, OFL). Solo el subconjunto latino: cubre el español. */
""" + "".join(
    f"@font-face {{ font-family: '{fam}'; font-style: normal; font-weight: {w}; font-display: swap;\n"
    f"  src: url('{slug}-latin-{w}-normal.woff2') format('woff2'); }}\n"
    for fam, slug, weights in (("Plus Jakarta Sans", "plus-jakarta-sans", (300, 400, 500, 600, 700)),
                               ("Fira Code", "fira-code", (400, 500, 600)))
    for w in weights)


def listing(pkg: str, version: str) -> dict:
    r = httpx.get(f"https://data.jsdelivr.com/v1/packages/npm/{pkg}@{version}?structure=flat", timeout=30)
    r.raise_for_status()
    return {f["name"].lstrip("/"): f["hash"] for f in r.json()["files"]}


def expand(files: dict, pattern: str) -> list:
    if "*" not in pattern:
        return [pattern]
    prefix, suffix = pattern.split("*", 1)
    return sorted(n for n in files if n.startswith(prefix) and n.endswith(suffix) and "/" not in n[len(prefix):])


def main(check_only: bool = False) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # acentos también en la consola de Windows o en un subproceso
    manifest_path = VENDOR / "MANIFEST.json"
    if check_only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bad = [rel for rel, info in manifest["files"].items()
               if hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() != info["sha256"]]
        print("OK: las librerías locales coinciden con el manifiesto" if not bad else f"Distintas: {bad}")
        return 1 if bad else 0

    manifest = {"source": "cdn.jsdelivr.net (hash verificado con data.jsdelivr.com)", "packages": {}, "files": {}}
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for pkg, version, items in LIBS:
            files = listing(pkg, version)
            manifest["packages"][pkg] = version
            for pattern, dest in items:
                for path in expand(files, pattern):
                    data = client.get(f"https://cdn.jsdelivr.net/npm/{pkg}@{version}/{path}").content
                    if base64.b64encode(hashlib.sha256(data).digest()).decode() != files[path]:
                        raise SystemExit(f"La huella de {pkg}@{version}/{path} no coincide con la de jsdelivr: no se guarda.")
                    rel = dest + Path(path).name if dest.endswith("/") else dest
                    out = VENDOR / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
                    manifest["files"][rel] = {
                        "package": f"{pkg}@{version}", "path": path, "sha256": hashlib.sha256(data).hexdigest(),
                        "sri": "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()}
                    print(f"ok  {rel}  ({len(data) // 1024} KB)")
    (VENDOR / "fonts" / "fonts.css").write_text(FONTS_CSS, encoding="utf-8", newline="\n")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"\n{len(manifest['files'])} archivos en {VENDOR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv[1:]))
