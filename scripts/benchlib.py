"""Paths, config, and the shared-page check for the CMP benchmark."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "benchmark.config.json"
DIST = ROOT / "dist"
SRC = ROOT / "src"
ASSETS = ROOT / "assets"
SNIPPETS = ROOT / "snippets"
REPORTS = ROOT / "reports"

START = "<!-- CMP:START -->"
END = "<!-- CMP:END -->"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
RESERVED_IDS = {"assets", "src", "scripts", "snippets", "reports"}


def load_config() -> Dict[str, Any]:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing {CONFIG_PATH.name}")
    except json.JSONDecodeError as err:
        raise SystemExit(f"{CONFIG_PATH.name} is not valid JSON: {err}")
    if not isinstance(raw, dict):
        raise SystemExit(f"{CONFIG_PATH.name} must be a JSON object")
    return parse_config(raw)


def parse_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    host = raw.get("host", "127.0.0.1")
    port = raw.get("port", 4173)
    host = require_host(host, "config host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SystemExit("config port must be an integer from 1 to 65535")

    # Absent or null keeps Lighthouse on `host`. A string is the hostname
    # Chrome should present to CMP domain checks.
    if "lighthouseHost" not in raw or raw.get("lighthouseHost") is None:
        lighthouse_host = None
    else:
        lighthouse_host = require_host(raw.get("lighthouseHost"), "config lighthouseHost").lower()

    entries = raw.get("variants")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("config variants must be a non-empty list")

    variants: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("each variant must be an object")
        variant_id = entry.get("id")
        label = entry.get("label")
        snippet = entry.get("snippet", None)
        if not isinstance(variant_id, str) or not ID_RE.fullmatch(variant_id):
            raise SystemExit(
                "variant id must be lowercase letters, digits, and hyphens: "
                f"{variant_id!r}"
            )
        if variant_id in RESERVED_IDS:
            raise SystemExit(f"variant id {variant_id!r} is reserved")
        if variant_id in seen:
            raise SystemExit(f"duplicate variant id {variant_id!r}")
        seen.add(variant_id)
        if not isinstance(label, str) or not label.strip():
            raise SystemExit(f"variant {variant_id} needs a label")
        snippet_path: Optional[Path] = None
        if snippet is not None:
            if not isinstance(snippet, str) or not snippet:
                raise SystemExit(f"variant {variant_id} snippet must be a path or null")
            snippet_path = resolve_snippet(snippet)
        # Absent or null keeps this variant on the run's lighthouseHost.
        # A string is the hostname Chrome should open for this variant only.
        if "host" not in entry or entry.get("host") is None:
            variant_host = None
        else:
            variant_host = require_host(entry.get("host"), f"variant {variant_id} host").lower()
        variants.append(
            {
                "id": variant_id,
                "label": label.strip(),
                "snippet": snippet,
                "snippet_path": snippet_path,
                "host": variant_host,
            }
        )

    return {
        "host": host,
        "port": port,
        "lighthouseHost": lighthouse_host,
        "variants": variants,
    }


def require_host(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not HOST_RE.fullmatch(value)
        or ".." in value
        or value.startswith(".")
        or value.endswith(".")
    ):
        raise SystemExit(f"{label} must be a hostname or IPv4 address")
    return value


def resolve_snippet(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(SNIPPETS.resolve())
    except ValueError:
        raise SystemExit(f"Snippet must live in {SNIPPETS.relative_to(ROOT)}: {value}")
    if not path.is_file():
        raise SystemExit(f"Snippet file not found: {value}")
    return path


def skeleton_of(html: str) -> str:
    """Page HTML with the CMP region replaced by empty markers."""
    if html.count(START) != 1 or html.count(END) != 1:
        raise ValueError("CMP markers missing or duplicated")
    start = html.index(START)
    end = html.index(END) + len(END)
    if start > end:
        raise ValueError("CMP markers are out of order")
    return html[:start] + START + "\n" + END + html[end:]


def snippet_of(html: str) -> str:
    """Snippet file contents between the CMP markers."""
    if html.count(START) != 1 or html.count(END) != 1:
        raise ValueError("CMP markers missing or duplicated")
    start = html.index(START) + len(START)
    end = html.index(END)
    if start > end:
        raise ValueError("CMP markers are out of order")
    body = html[start:end]
    if body.startswith("\n"):
        body = body[1:]
    return body


CSS_TOKEN = "/*__CSS__*/"
JS_TOKEN = "/*__JS__*/"


def read_snippet(variant: Dict[str, Any]) -> str:
    """Return the snippet file exactly as it is stored. Baseline is empty."""
    path = variant["snippet_path"]
    if path is None:
        return ""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{variant['snippet']} starts with a BOM; remove it")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as err:
        raise ValueError(f"{variant['snippet']} is not UTF-8: {err}")
    if START in text or END in text:
        raise ValueError(f"{variant['snippet']} contains CMP marker comments")
    return text


def render_variant(variant: Dict[str, Any]) -> str:
    """Shared page with this variant's snippet file inserted unchanged."""
    template = (SRC / "page.template.html").read_text(encoding="utf-8")
    css = (SRC / "site.css").read_text(encoding="utf-8")
    js = (SRC / "metrics.js").read_text(encoding="utf-8")
    if "</style>" in css.lower():
        raise ValueError("src/site.css contains </style>")
    if "</script>" in js.lower():
        raise ValueError("src/metrics.js contains </script>")
    if template.count(CSS_TOKEN) != 1 or template.count(JS_TOKEN) != 1:
        raise ValueError("page template is missing its CSS or JS placeholder")
    page = template.replace(CSS_TOKEN, css, 1).replace(JS_TOKEN, js, 1)
    needle = START + "\n" + END
    if page.count(needle) != 1:
        raise ValueError("page template CMP markers are missing or not adjacent")
    snippet = read_snippet(variant)
    return page.replace(needle, START + "\n" + snippet + END, 1)
