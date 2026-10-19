#!/usr/bin/env python3
"""Локальный сервер мастер-класса (PLAN.md 8).

Раздаёт статику проекта с заголовками:
  - COOP/COEP (нужны для потоков WASM в onnxruntime);
  - долгий кэш для моделей и node_modules (модель Laya качается один раз).

Опционально:
  --https          самоподписанный сертификат (микрофон требует защищённый контекст);
  --nlu-url URL    прокси POST /api/nlu → внешний сервис модели (system-one-npu
                   /v1/systemone или облачный). Ключ живёт только здесь —
                   браузер обращается исключительно к этому бэкенду.

Примеры:
  python3 tools/serve.py --port 8080
  python3 tools/serve.py --https --nlu-url http://192.168.1.40:8000/v1/systemone
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Канонический источник obj-мешей (как в docker-prepare: ros_packages/scripts/
# build_for_desktop.sh кладёт их в deps/mujoco_playground). В репозитории
# эксперимента копий нет — /assets/scenes/meshes/*.obj отдаём отсюда.
CANONICAL_MESH_DIR = Path(__file__).resolve().parents[3] / "urdf_src" / "export" / "rds-2p" / "meshes" / "obj"

# Нейросетевая политика ходьбы (rospkg rds_2p_inference) — тоже без копий.
POLICY_DIR = Path(__file__).resolve().parents[3] / "ros_packages" / "src" / "rds_2p_inference" / "models"

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/xml", ".mjcf")
mimetypes.add_type("text/xml", ".xml")
mimetypes.add_type("text/plain", ".obj")

LONG_CACHE_PREFIXES = ("/node_modules/", "/models/", "/assets/scenes/meshes/")


class Handler(SimpleHTTPRequestHandler):
    nlu_upstream: str | None = None
    nlu_headers: dict = {}
    # HTTP/1.1 — keep-alive: без него каждый файл (а их в node_modules сотни)
    # открывает новое TCP-соединение, что заметно замедляет первую загрузку.
    protocol_version = "HTTP/1.1"

    def guess_cache(self, path: str) -> str:
        if any(path.startswith(p) for p in LONG_CACHE_PREFIXES):
            return "public, max-age=31536000, immutable"
        if path.endswith(".html") or path in ("/", "") or path.startswith("/src/") or path.startswith("/assets/scenes/"):
            return "no-cache"
        return "public, max-age=3600"

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/nlu"):
            self._nlu_probe()
            return
        if self.path.startswith("/api/laya/status"):
            self._laya_status()
            return
        self.send_head_patched()

    def do_HEAD(self):  # noqa: N802
        self.send_head_patched()

    def send_head_patched(self):
        path = self.path.split("?", 1)[0]
        fs_path = self.translate_path(path)
        if path.startswith("/assets/scenes/meshes/") and path.endswith(".obj"):
            canonical = CANONICAL_MESH_DIR / os.path.basename(path)
            if canonical.is_file():
                fs_path = str(canonical)
        if path.startswith("/models/policy/"):
            canonical = POLICY_DIR / os.path.basename(path)
            if canonical.is_file():
                fs_path = str(canonical)
        if os.path.isdir(fs_path):
            index = os.path.join(fs_path, "index.html")
            if os.path.isfile(index):
                fs_path = index
                path = path.rstrip("/") + "/index.html"
        if not os.path.isfile(fs_path):
            self.send_error(404, f"Not found: {path}")
            return
        try:
            ctype = self.guess_type(fs_path)
            # Предсжатый сиблинг file.gz (готовится на сборке образа,
            # tools/precompress_assets.py) — отдаём его, когда клиент умеет gzip.
            # Range всегда обслуживаем по identity-файлу: так докачка (важно для
            # Laya 646 МБ) простая и предсказуемая, без диапазонов поверх gzip.
            accept = (self.headers.get("Accept-Encoding") or "").lower()
            range_hdr = self.headers.get("Range")
            gz_path = fs_path + ".gz"
            send_gz = "gzip" in accept and not range_hdr and os.path.isfile(gz_path)
            body_path = gz_path if send_gz else fs_path
            body_size = os.path.getsize(body_path)

            status = 200
            start, end = 0, body_size - 1
            if range_hdr:
                parsed = self._parse_range(range_hdr, body_size)
                if parsed is None:  # неудовлетворимый диапазон
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{body_size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if parsed != (-1, -1):
                    start, end = parsed
                    status = 206

            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(end - start + 1))
            if send_gz:
                self.send_header("Content-Encoding", "gzip")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{body_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", self.guess_cache(path))
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(body_path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _parse_range(header: str, size: int):
        """Один диапазон bytes=start-end.

        Возвращает (start, end) включительно, (-1, -1) — «игнорировать Range»
        (несколько диапазонов/мусор), None — 416 (диапазон неудовлетворим).
        """
        if not header.startswith("bytes=") or size <= 0:
            return (-1, -1)
        spec = header[len("bytes="):].strip()
        if "," in spec:
            return (-1, -1)
        first, _, last = spec.partition("-")
        try:
            if first == "":
                suffix = int(last)
                if suffix <= 0:
                    return None
                return (max(0, size - suffix), size - 1)
            start = int(first)
            explicit_end = last != ""
            end = int(last) if explicit_end else size - 1
        except ValueError:
            return (-1, -1)
        # last < first — синтаксически невалидный диапазон → игнорируем весь Range
        # (RFC 9110); «start за концом файла» — валидный, но неудовлетворимый → 416.
        if start < 0 or (explicit_end and end < start):
            return (-1, -1)
        if start >= size:
            return None
        return (start, min(end, size - 1))

    # ── прокси NLU ──────────────────────────────────

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _nlu_probe(self):
        self._json(200, {"enabled": bool(self.nlu_upstream), "proxy": "/api/nlu"})

    def _laya_status(self):
        """Есть ли артефакты Laya в models/laya — без 404-шума в консоли браузера."""
        base = Path(self.translate_path("/models/laya"))
        files = {n: (base / n).is_file() for n in ("manifest.json", "tokenizer.json")}
        available = files["manifest.json"] or (base / "laya_multilingual_seq512.onnx").is_file()
        if files["manifest.json"]:
            try:
                manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                manifest = None
        else:
            manifest = None
        self._json(200, {"available": bool(available), "files": files, "manifest": manifest})

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/api/nlu"):
            self.send_error(404)
            return
        if not self.nlu_upstream:
            self._json(404, {"detail": "nlu proxy не настроен (запустите serve.py с --nlu-url)"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        request = urllib.request.Request(self.nlu_upstream, data=raw, method="POST")
        request.add_header("Content-Type", "application/json")
        for name, value in self.nlu_headers.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                payload = resp.read()
                self._json(200, json.loads(payload.decode("utf-8")))
        except urllib.error.HTTPError as err:
            detail = err.read()[:2000].decode("utf-8", "replace")
            self._json(err.code, {"detail": detail})
        except Exception as err:  # noqa: BLE001
            self._json(502, {"detail": f"upstream недоступен: {err}"})

    def end_headers(self):  # COOP/COEP ко всем ответам, включая 404: иначе COEP их «блокирует»
        for name, value in (
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Cross-Origin-Embedder-Policy", "require-corp"),
            ("Cross-Origin-Resource-Policy", "same-origin"),
        ):
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, fmt, *args):  # компактнее
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def ensure_cert(cert_dir: Path) -> tuple[Path, Path]:
    cert = cert_dir / "cert.pem"
    key = cert_dir / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    cert_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "825",
        "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"сгенерированы {cert} и {key}")
    return cert, key


def parse_auth(pairs: list[str]) -> dict:
    headers = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if name and value:
            headers[name.strip()] = value.strip()
    return headers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--https", action="store_true", help="самоподписанный TLS (нужен для микрофона вне localhost)")
    parser.add_argument("--cert-dir", type=Path, default=ROOT / ".certs")
    parser.add_argument("--nlu-url", default=os.environ.get("NLU_UPSTREAM_URL") or None,
                        help="внешний сервис модели (system-one-npu /v1/systemone или облачный)")
    parser.add_argument("--nlu-header", action="append", default=[], metavar="NAME=VALUE",
                        help="заголовок для upstream, повторяемый (например Authorization=Bearer <ключ на сервере>)")
    parser.add_argument("--directory", type=Path, default=ROOT)
    args = parser.parse_args()

    Handler.nlu_upstream = args.nlu_url
    Handler.nlu_headers = parse_auth(args.nlu_header)

    handler = partial(Handler, directory=str(args.directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)

    if args.https:
        cert, key = ensure_cert(args.cert_dir)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    scheme = "https" if args.https else "http"
    print(f"мастер-класс Панды: {scheme}://{args.host}:{args.port}/")
    if args.nlu_url:
        print(f"nlu-прокси: POST /api/nlu → {args.nlu_url}")
    else:
        print("nlu-прокси выключен (браузер использует Laya локально или keywords)")
    print("COOP/COEP включены (потоки WASM), Ctrl+C — остановка")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")


if __name__ == "__main__":
    main()
