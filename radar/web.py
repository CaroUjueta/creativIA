"""App web local: python -m radar.web [--port 8000]

Sirve el tablero del último reporte, el historial de reportes en out/ y un botón para
actualizar el radar sin usar la consola. Solo escucha en este computador (127.0.0.1).
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import subprocess
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import pipeline, report, sources
from .models import scrub

log = logging.getLogger("radar")


class Runner:
    """Corre el radar en segundo plano, de a una ejecución a la vez."""

    def __init__(self, opts: pipeline.Options):
        self.opts = opts
        self.lock = threading.Lock()
        self.status = {"state": "idle", "step": 0, "message": "", "error": ""}

    def start(self) -> bool:
        with self.lock:
            if self.status["state"] == "running":
                return False
            self.status = {"state": "running", "step": 1, "message": "", "error": ""}
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def _progress(self, step: int, message: str) -> None:
        self.status.update(step=step, message=message)

    def _work(self) -> None:
        try:
            pipeline.run(self.opts, self._progress)
            self.status.update(state="done", step=pipeline.STEPS + 1, message="")
        except Exception as e:
            log.exception("Falló la actualización del radar")
            self.status.update(state="error", error=str(e) or e.__class__.__name__)


def list_reports(out: Path) -> list[str]:
    return sorted((p.stem for p in out.glob("radar-*.json")), reverse=True)


def page(out: Path, name: str | None, top: int) -> str:
    reports = list_reports(out)
    if name not in reports:
        name = reports[0] if reports else None
    if name:
        data = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        html = report.render_html(data, data.get("adaptations", {}), data["meta"], len(data.get("adaptations", {})) or top,
                                  report.latest_backtest(out))
    else:
        html = report.render_empty(top)
    app = json.dumps({"reports": reports, "current": name}).replace("<", "\\u003c")
    return html.replace("</head>", f"<script>window.RADAR_APP = {app};</script></head>", 1)


PLATFORMS = {"linkedin", "instagram", "tiktok", "youtube", "x", "facebook", "threads", "otra"}


def validate_contribution(body: dict, today: date | None = None) -> dict:
    """Revisa un aporte de la comunidad. Lanza ValueError con un mensaje para mostrar en el formulario."""
    today = today or date.today()
    if body.get("public") is not True:
        raise ValueError("Confirma que la publicación es pública y no incluye datos personales.")
    url = str(body.get("url", "")).strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
        raise ValueError("El enlace debe ser una dirección web pública (https://…).")
    text = scrub(str(body.get("text", "")))
    if len(text) < 15:
        raise ValueError("Pega el texto de la publicación (al menos una frase).")
    try:
        published = date.fromisoformat(str(body.get("published_at", ""))[:10])
    except ValueError:
        raise ValueError("Revisa la fecha de publicación.") from None
    if not today - timedelta(days=60) <= published <= today:
        raise ValueError("La fecha debe estar entre hoy y los últimos 60 días.")
    platform_ = str(body.get("platform", "otra")).strip().lower()
    counts = {}
    for k in ("likes", "comments", "shares", "views"):
        try:
            counts[k] = max(0, int(float(body.get(k) or 0)))
        except (TypeError, ValueError):
            raise ValueError("Las métricas deben ser números.") from None
    return {"platform": platform_ if platform_ in PLATFORMS else "otra", "url": url[:500], "text": text[:3000],
            # Mediodía de Bogotá: la publicación cae en el día que eligió la persona.
            "published_at": datetime(published.year, published.month, published.day, 12).isoformat() + "-05:00",
            "publisher": str(body.get("publisher", "")).strip()[:80], **counts}


def make_handler(runner: Runner):
    out = runner.opts.out
    community = runner.opts.community

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, obj: dict) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False), "application/json")

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                name = parse_qs(url.query).get("r", [None])[0]
                self._send(HTTPStatus.OK, page(out, name, runner.opts.top), "text/html")
            elif url.path == "/api/status":
                self._json(HTTPStatus.OK, runner.status)
            elif url.path == "/api/reports":
                self._json(HTTPStatus.OK, {"reports": list_reports(out)})
            elif url.path == "/api/community":
                self._json(HTTPStatus.OK, {"count": sources.count_community(community)})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in ("/api/run", "/api/community"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})
                return
            # Evita que otra página abierta en el navegador dispare el radar o escriba aportes.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origen no permitido"})
                return
            if path == "/api/community":
                self._contribute()
            elif runner.start():
                self._json(HTTPStatus.ACCEPTED, runner.status)
            else:
                self._json(HTTPStatus.CONFLICT, {"error": "El radar ya se está actualizando"})

        def _contribute(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 20_000:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Aporte vacío o demasiado grande"})
                return
            try:
                row = validate_contribution(json.loads(self.rfile.read(length)))
            except (ValueError, AttributeError) as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e) if isinstance(e, ValueError) else "Formato inválido"})
                return
            with runner.lock:
                total = sources.append_community(community, row)
            self._json(HTTPStatus.CREATED, {"count": total})

        def log_message(self, fmt: str, *args) -> None:  # sin una línea por cada consulta de estado
            pass

    return Handler


def open_browser(url: str) -> None:
    if "microsoft" in platform.release().lower():  # WSL: el navegador vive en Windows
        try:
            subprocess.Popen(["explorer.exe", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


def main() -> None:
    pipeline.load_dotenv()
    ap = argparse.ArgumentParser(prog="radar.web", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out", type=Path, default=Path("out"), help="carpeta de reportes")
    ap.add_argument("--no-open", action="store_true", help="no abrir el navegador")
    ap.add_argument("--no-jev", action="store_true", help="no usar Jev aunque haya clave")
    ap.add_argument("--no-llm", action="store_true", help="redactar la adaptación con plantillas")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpx2", "typesafe_sdk", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    runner = Runner(pipeline.Options(out=args.out, no_jev=args.no_jev, no_llm=args.no_llm))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(runner))
    url = f"http://localhost:{args.port}"
    print(f"Radar de contenido IA en {url}  (Ctrl+C para salir)")
    if not args.no_open:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
