#!/usr/bin/env python3
"""Serve the benchmark. Snippet files are read on each request and inserted as stored.

There is no generated copy of the pages. /<variant>/ is the shared template
plus the snippet path from benchmark.config.json. /assets/hero.jpg is the
file in assets/. Responses are Cache-Control: no-store and never 304.
"""

import html
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchlib


class Handler(BaseHTTPRequestHandler):
    server_version = "cmp-bench"
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self._respond(write_body=False)

    def do_GET(self):
        self._respond(write_body=True)

    def _respond(self, write_body: bool) -> None:
        path = urlsplit(self.path).path
        try:
            body, content_type = resolve(path)
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        except ValueError as err:
            body = (str(err) + "\n").encode("utf-8")
            self.send_response(500)
            self._cache_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if write_body:
                self.wfile.write(body)
            return
        self.send_response(200)
        self._cache_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _cache_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def resolve(path: str):
    route, extra = route_path(path)
    if route == "index":
        return index_page(benchlib.load_config()), "text/html; charset=utf-8"
    if route == "asset":
        return extra.read_bytes(), "image/jpeg"
    if route == "variant":
        config = benchlib.load_config()
        variant = next((item for item in config["variants"] if item["id"] == extra), None)
        if variant is None:
            raise FileNotFoundError(path)
        return benchlib.render_variant(variant).encode("utf-8"), "text/html; charset=utf-8"
    raise FileNotFoundError(path)


def route_path(path: str):
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    if path in ("", "/"):
        return "index", None
    if path == "/index.html":
        return "index", None
    if path == "/assets/hero.jpg":
        hero = benchlib.ASSETS / "hero.jpg"
        if not hero.is_file():
            raise FileNotFoundError(path)
        return "asset", hero
    parts = [part for part in path.split("/") if part]
    if len(parts) == 1 or (len(parts) == 2 and parts[1] == "index.html"):
        return "variant", parts[0]
    return "missing", None


def index_page(config: dict) -> bytes:
    items = []
    for variant in config["variants"]:
        items.append(
            "<li><a href=\"/{id}/\">{id}</a> — {label}</li>".format(
                id=html.escape(variant["id"]),
                label=html.escape(variant["label"]),
            )
        )
    body = "\n    ".join(items)
    page = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CMP benchmark variants</title>
</head>
<body>
  <h1>CMP benchmark</h1>
  <p>Each link serves the same page. The file named in benchmark.config.json is inserted between the CMP markers exactly as it is saved in snippets/. Measure those URLs. This index is only a directory.</p>
  <p>Open the browser console and wait for the line that contains <code>phase=settled</code>.</p>
  <ul>
    {items}
  </ul>
</body>
</html>
""".format(items=body)
    return page.encode("utf-8")


def bind_address(default: str) -> str:
    """Address the socket binds. CMP_BENCH_BIND overrides the public host.

    Docker must listen on 0.0.0.0 while browsers and Lighthouse still open
    the host from benchmark.config.json, usually 127.0.0.1 via a published port.
    """
    value = os.environ.get("CMP_BENCH_BIND", "").strip()
    if not value:
        return default
    if not benchlib.HOST_RE.fullmatch(value) or ".." in value:
        raise SystemExit("CMP_BENCH_BIND must be a hostname or IPv4 address")
    return value


def warn_snippets(config: dict) -> None:
    for variant in config["variants"]:
        if variant["snippet_path"] is None:
            continue
        text = benchlib.read_snippet(variant)
        if "<script" not in text.lower():
            print(f"warning: {variant['snippet']} has no <script> tag")


def main() -> None:
    config = benchlib.load_config()
    warn_snippets(config)
    # Fail at startup if the shared page cannot be rendered.
    benchlib.render_variant(config["variants"][0])
    host = config["host"]
    port = config["port"]
    bind = bind_address(host)
    try:
        server = Server((bind, port), Handler)
    except OSError as err:
        raise SystemExit(f"Could not bind {bind}:{port}: {err}")

    print(f"Listening on {bind}:{port}", flush=True)
    print(f"Open http://{host}:{port}/", flush=True)
    print("Snippet files are read from snippets/ on each request.", flush=True)
    print("Cache-Control: no-store (no 304s)", flush=True)
    for variant in config["variants"]:
        origin = variant["snippet"] or "no snippet"
        print(f"  http://{host}:{port}/{variant['id']}/  {origin}", flush=True)
        alias = variant.get("host") or config["lighthouseHost"]
        if alias and alias != host:
            print(
                f"    Lighthouse opens http://{alias}:{port}/{variant['id']}/ "
                f"and connects {alias} to {host}.",
                flush=True,
            )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
