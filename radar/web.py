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
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import pipeline, report

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
        except BaseException as e:  # classify() usa SystemExit para una clave de Jev inválida
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
        html = report.render_html(data, data.get("adaptations", {}), data["meta"], len(data.get("adaptations", {})) or top)
    else:
        html = report.render_empty(top)
    app = json.dumps({"reports": reports, "current": name}).replace("<", "\\u003c")
    return html.replace("</head>", f"<script>window.RADAR_APP = {app};</script></head>", 1)


def make_handler(runner: Runner):
    out = runner.opts.out

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
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/run":
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})
                return
            # Evita que otra página abierta en el navegador dispare el radar.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origen no permitido"})
                return
            if runner.start():
                self._json(HTTPStatus.ACCEPTED, runner.status)
            else:
                self._json(HTTPStatus.CONFLICT, {"error": "El radar ya se está actualizando"})

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
