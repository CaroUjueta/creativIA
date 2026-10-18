"""App web: python -m radar.web [--port 8000] [--host 0.0.0.0]

Sirve el tablero del último reporte, el historial de reportes en out/ y un botón para
actualizar el radar sin usar la consola. Por defecto solo escucha en este computador (127.0.0.1).
Para publicarla (p. ej. en Hugging Face Spaces) se usa --host 0.0.0.0 y RADAR_PASSWORD: sin
la contraseña nadie ve el tablero ni puede actualizar el radar o escribir datos.
"""

from __future__ import annotations

import argparse
import hmac
import html as htmllib
import os
import json
import logging
import platform
import subprocess
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import account, pipeline, report, sources, storage
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
            storage.push("Radar actualizado")
        except Exception as e:
            log.exception("Falló la actualización del radar")
            self.status.update(state="error", error=str(e) or e.__class__.__name__)


def seed_reports(out: Path, seed: Path = Path("demo")) -> None:
    """En un servidor recién creado, arranca con el último reporte del equipo (demo/)."""
    if list_reports(out) or not seed.is_dir():
        return
    out.mkdir(parents=True, exist_ok=True)
    for f in seed.glob("*.json"):
        (out / f.name).write_bytes(f.read_bytes())


def list_reports(out: Path) -> list[str]:
    return sorted((p.stem for p in out.glob("radar-*.json")), reverse=True)


def page(out: Path, name: str | None, top: int) -> str:
    reports = list_reports(out)
    if name not in reports:
        name = reports[0] if reports else None
    if name:
        data = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        html = report.render_html(data, data.get("adaptations", {}), data["meta"], data["meta"].get("top") or len(data.get("adaptations", {})) or top,
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


COOKIE = "creativia"

LOGIN_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CreativIA</title>
<link rel="icon" href="__LOGO__"><style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#16161a;--muted:#6b6b76;--line:#e4e2dc;--accent:#5b4bff}
@media (prefers-color-scheme:dark){:root{--bg:#121216;--card:#1c1c22;--ink:#f2f2f5;--muted:#a0a0ac;--line:#2e2e36}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:16px}
form{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px;width:100%;max-width:360px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:20px;margin-bottom:4px}
.brand i{width:32px;height:32px;background:url(__LOGO__) center/contain no-repeat}
p{color:var(--muted);margin:0 0 18px;font-size:14px}
input{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;font:inherit;background:var(--bg);color:var(--ink)}
button{margin-top:12px;width:100%;padding:11px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}
.err{color:#d33;font-size:14px;margin-top:10px}</style></head><body>
<form method="post" action="/login"><div class="brand"><i></i>CreativIA</div>
<p>Radar de contenido · Reto 30X. Escribe la contraseña del equipo.</p>
<input type="password" name="password" placeholder="Contraseña" autofocus required autocomplete="current-password">
<button>Entrar</button>__ERROR__</form></body></html>"""


def session_token(password: str) -> str:
    return hmac.new(password.encode(), b"creativia-sesion", "sha256").hexdigest()


def make_handler(runner: Runner, password: str = ""):
    out = runner.opts.out
    community = runner.opts.community
    token = session_token(password) if password else ""

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

        def _authed(self) -> bool:
            if not password:
                return True
            for part in (self.headers.get("Cookie") or "").split(";"):
                key, _, value = part.strip().partition("=")
                if key == COOKIE and hmac.compare_digest(value, token):
                    return True
            return False

        def _login_page(self, status: int = HTTPStatus.OK, error: str = "") -> None:
            body = LOGIN_PAGE.replace("__LOGO__", report.LOGO).replace(
                "__ERROR__", f'<div class="err">{htmllib.escape(error)}</div>' if error else "")
            self._send(status, body, "text/html")

        def _login(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if 0 < length <= 2_000 else ""
            given = parse_qs(raw).get("password", [""])[0]
            if not hmac.compare_digest(given.encode(), password.encode()):
                time.sleep(1)  # frena a quien intente adivinar
                self._login_page(HTTPStatus.UNAUTHORIZED, "Contraseña incorrecta.")
                return
            https = self.headers.get("X-Forwarded-Proto") == "https"
            # SameSite=None deja entrar también desde la vista incrustada de huggingface.co
            flags = "Secure; SameSite=None" if https else "SameSite=Lax"
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Set-Cookie", f"{COOKIE}={token}; Path=/; HttpOnly; Max-Age=2592000; {flags}")
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/login":
                self._login_page()
                return
            if not self._authed():
                if url.path.startswith("/api/"):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "Inicia sesión"})
                else:
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header("Location", "/login")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                return
            if url.path == "/":
                name = parse_qs(url.query).get("r", [None])[0]
                self._send(HTTPStatus.OK, page(out, name, runner.opts.top), "text/html")
            elif url.path == "/api/status":
                self._json(HTTPStatus.OK, runner.status)
            elif url.path == "/api/reports":
                self._json(HTTPStatus.OK, {"reports": list_reports(out)})
            elif url.path == "/api/community":
                self._json(HTTPStatus.OK, {"count": sources.count_community(community)})
            elif url.path == "/api/account":
                self._json(HTTPStatus.OK, {"profile": account.load_profile() or account.DEFAULT,
                                           "saved": account.PROFILE.exists(), "metrics": account.metrics_status()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/login" and password:
                self._login()
                return
            if not self._authed():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Inicia sesión"})
                return
            if path not in ("/api/run", "/api/community", "/api/account", "/api/account/metrics"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "No existe"})
                return
            # Evita que otra página abierta en el navegador dispare el radar o escriba aportes.
            origin = self.headers.get("Origin")
            own = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1", own):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origen no permitido"})
                return
            if path == "/api/community":
                self._contribute()
            elif path == "/api/account":
                self._account()
            elif path == "/api/account/metrics":
                self._account_metrics()
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
            storage.push("Nuevo aporte de la comunidad")
            self._json(HTTPStatus.CREATED, {"count": total})

        def _body(self, limit: int) -> bytes | None:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= limit:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Envío vacío o demasiado grande"})
                return None
            return self.rfile.read(length)

        def _account(self) -> None:
            raw = self._body(20_000)
            if raw is None:
                return
            try:
                profile = account.save_profile(json.loads(raw))
            except (ValueError, AttributeError) as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e) if isinstance(e, ValueError) else "Formato inválido"})
                return
            storage.push("Ficha de la cuenta actualizada")
            self._json(HTTPStatus.OK, {"profile": profile})

        def _account_metrics(self) -> None:
            raw = self._body(5_000_000)
            if raw is None:
                return
            try:
                status = account.save_metrics(raw.decode("utf-8-sig", errors="replace"))
            except ValueError as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                return
            storage.push("Métricas de la cuenta actualizadas")
            self._json(HTTPStatus.OK, {"metrics": status})

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
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="0.0.0.0 para publicarla (exige RADAR_PASSWORD)")
    ap.add_argument("--public", action="store_true",
                    help="pedir RADAR_PASSWORD aunque escuche en 127.0.0.1 (p. ej. detrás de un túnel)")
    ap.add_argument("--sin-clave", action="store_true",
                    help="publicarla sin contraseña: cualquiera con el enlace puede usarla (p. ej. jurados)")
    ap.add_argument("--out", type=Path, default=Path("out"), help="carpeta de reportes")
    ap.add_argument("--no-open", action="store_true", help="no abrir el navegador")
    ap.add_argument("--no-jev", action="store_true", help="no usar Jev aunque haya clave")
    ap.add_argument("--no-llm", action="store_true", help="redactar la adaptación con plantillas")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpx2", "typesafe_sdk", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    public = (args.public or args.host not in ("127.0.0.1", "localhost")) and not args.sin_clave
    password = os.environ.get("RADAR_PASSWORD", "") if public else ""  # en este computador no se pide
    if public and not password:
        ap.error("para escuchar fuera de este computador define RADAR_PASSWORD")
    storage.pull()
    seed_reports(args.out)
    runner = Runner(pipeline.Options(out=args.out, no_jev=args.no_jev, no_llm=args.no_llm))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(runner, password))
    url = f"http://localhost:{args.port}"
    print(f"CreativIA · Radar de contenido en {url}  (Ctrl+C para salir)")
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
