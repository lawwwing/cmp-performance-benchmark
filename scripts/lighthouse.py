#!/usr/bin/env python3
"""Run Lighthouse against every variant and write a comparison table.

The benchmark server must already be running, unless --serve is passed.
Lighthouse is not a project dependency: install the CLI separately, or
pass --npx to let npx fetch it for this run.

    python3 scripts/serve.py
    python3 scripts/lighthouse.py --runs 5

Positive deltas are variant minus baseline. For LCP, FCP, TBT, CLS, and
Speed Index, a positive delta is additional cost. For the performance
score, a positive delta is a higher Lighthouse score.

Set lighthouseHost in benchmark.config.json when a CMP only loads on a
hostname its dashboard already allows. Set host on one variant when only
that CMP needs a different name. Lighthouse opens that name, and Chrome
connects it to host for this run.
"""

import argparse
import csv
import json
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchlib

AUDITS = (
    ("lcp_ms", "largest-contentful-paint"),
    ("fcp_ms", "first-contentful-paint"),
    ("tbt_ms", "total-blocking-time"),
    ("cls", "cumulative-layout-shift"),
    ("speed_index_ms", "speed-index"),
)


def main(argv: List[str] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run Lighthouse against every variant and write a comparison table.",
        epilog=(
            "Example: python3 scripts/serve.py  then  "
            "python3 scripts/lighthouse.py --runs 5. "
            "Pass --serve to start and stop the server for the run. "
            "Delta columns are variant median minus baseline median."
        ),
    )
    parser.add_argument("--runs", type=int, default=1, help="Lighthouse runs per variant (default 1)")
    parser.add_argument("--desktop", action="store_true", help="use the Lighthouse desktop preset")
    parser.add_argument("--serve", action="store_true", help="start scripts/serve.py for this run and stop it after")
    parser.add_argument("--npx", action="store_true", help="launch Lighthouse with npx --yes")
    parser.add_argument("--lighthouse", help="path to the lighthouse binary")
    parser.add_argument("--no-sandbox", action="store_true", help="pass --no-sandbox to Chrome")
    parser.add_argument("--timeout", type=int, default=180, help="seconds allowed per Lighthouse run")
    parser.add_argument("--baseline", default="baseline", help="variant id used as the delta reference")
    args = parser.parse_args(argv)

    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    if args.timeout < 30:
        raise SystemExit("--timeout must be at least 30 seconds")

    config = benchlib.load_config()
    binary = find_lighthouse(args)
    server = None
    if args.serve:
        server = subprocess.Popen(
            [sys.executable, str(benchlib.ROOT / "scripts" / "serve.py")]
        )
    try:
        wait_for_server(config, server)
        confirm_skeletons(config)
        describe_lighthouse_host(config)
        if args.runs < 3:
            print("One or two runs are noisy. Use --runs 5 before comparing CMPs.")
        summary = run_all(config, binary, args)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()

    write_summary(summary)
    print_table(summary, args.baseline)
    if summary["failures"]:
        raise SystemExit(1)


def find_lighthouse(args: argparse.Namespace) -> List[str]:
    if args.npx:
        npx = shutil.which("npx")
        if npx is None:
            raise SystemExit("npx was not found on PATH")
        return [npx, "--yes", "lighthouse"]
    if args.lighthouse:
        return [args.lighthouse]
    found = shutil.which("lighthouse")
    if found is None:
        raise SystemExit(
            "lighthouse was not found on PATH. Install it, pass --lighthouse, "
            "or pass --npx."
        )
    return [found]


def wait_for_server(config: dict, server: Optional[subprocess.Popen]) -> None:
    variant_id = config["variants"][0]["id"]
    url = variant_url(config, variant_id)
    for _ in range(50):
        if server is not None and server.poll() is not None:
            raise SystemExit("benchmark server exited before it accepted a request")
        if fetch_status(url) == 200:
            return
        time.sleep(0.1)
    raise SystemExit(
        f"No benchmark server at {url}. Start it with python3 scripts/serve.py "
        "or pass --serve."
    )


def confirm_skeletons(config: dict) -> None:
    local = None
    for variant in config["variants"]:
        url = variant_url(config, variant["id"])
        try:
            body, status = fetch(url)
            expected = benchlib.render_variant(variant)
        except urllib.error.URLError as err:
            raise SystemExit(f"Could not fetch {url}: {err}")
        except ValueError as err:
            raise SystemExit(f"{variant['id']}: {err}")
        if status != 200:
            raise SystemExit(f"{url} returned HTTP {status}")
        try:
            current = benchlib.skeleton_of(body)
        except ValueError as err:
            raise SystemExit(f"{url} is not a benchmark page: {err}")
        if local is None:
            local = benchlib.skeleton_of(expected)
        if current != local or benchlib.snippet_of(body) != benchlib.read_snippet(variant):
            raise SystemExit(
                f"{url} does not match the shared template plus {variant['snippet'] or 'an empty snippet'}."
            )
    print("Fetched variants match the snippet files and share one page skeleton.")


def run_all(config: dict, binary: List[str], args: argparse.Namespace) -> Dict[str, Any]:
    version = require_lighthouse(binary)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_root = benchlib.REPORTS / stamp
    out_root.mkdir(parents=True, exist_ok=True)
    failures = []
    variants = []
    for variant in config["variants"]:
        runs = []
        variant_dir = out_root / variant["id"]
        variant_dir.mkdir()
        for number in range(1, args.runs + 1):
            print(f"Lighthouse {variant['id']} run {number}/{args.runs}")
            result = run_once(
                binary=binary,
                url=variant_url(config, variant["id"], measurement_host(config, variant)),
                out_dir=variant_dir,
                number=number,
                desktop=args.desktop,
                no_sandbox=args.no_sandbox,
                timeout=args.timeout,
                config=config,
            )
            runs.append(result)
            if result.get("error"):
                failures.append(f"{variant['id']} run {number}: {result['error']}")
        variants.append(
            {
                "id": variant["id"],
                "label": variant["label"],
                "url": variant_url(config, variant["id"], measurement_host(config, variant)),
                "median": median_of(runs),
                "runs": runs,
            }
        )
    return {
        "createdAt": stamp,
        "outputDir": str(out_root),
        "formFactor": "desktop" if args.desktop else "mobile",
        "origin": f"http://{lighthouse_host(config)}:{config['port']}",
        "runsPerVariant": args.runs,
        "lighthouseVersion": version,
        "baseline": args.baseline,
        "variants": variants,
        "failures": failures,
    }


def run_once(
    binary: List[str],
    url: str,
    out_dir: Path,
    number: int,
    desktop: bool,
    no_sandbox: bool,
    timeout: int,
    config: dict,
) -> Dict[str, Any]:
    output_path = out_dir / f"run-{number}"
    cmd = binary + [
        url,
        "--only-categories=performance",
        "--output=json",
        "--output=html",
        "--output-path=" + str(output_path),
        "--chrome-flags=" + chrome_flags_value(no_sandbox, config),
    ]
    if desktop:
        cmd.append("--preset=desktop")
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(benchlib.ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"run": number, "error": f"timed out after {timeout}s"}

    if completed.returncode != 0:
        (out_dir / f"run-{number}.stderr.txt").write_bytes(completed.stderr)
        detail = failure_detail(completed.stderr.decode("utf-8", errors="replace"), completed.returncode)
        return {"run": number, "error": detail}

    report_path = output_path.parent / f"{output_path.name}.report.json"
    if not report_path.is_file():
        report_path = output_path.parent / f"{output_path.name}.json"
    if not report_path.is_file():
        return {"run": number, "error": "Lighthouse finished without a JSON report"}
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return {"run": number, "error": f"could not parse {report_path.name}: {err}"}
    return parse_report(number, data, report_path)


def parse_report(number: int, data: dict, report_path: Path) -> Dict[str, Any]:
    categories = data.get("categories") or {}
    performance = categories.get("performance") or {}
    score = performance.get("score")
    parsed: Dict[str, Any] = {
        "run": number,
        "report": str(report_path),
        "requestedUrl": data.get("requestedUrl"),
        "finalUrl": data.get("finalUrl"),
        "fetchTime": data.get("fetchTime"),
        "performanceScore": float(score) if isinstance(score, (int, float)) else None,
    }
    audits = data.get("audits") or {}
    for field, audit_id in AUDITS:
        audit = audits.get(audit_id) or {}
        value = audit.get("numericValue")
        parsed[field] = float(value) if isinstance(value, (int, float)) else None
    if parsed["requestedUrl"] and parsed["finalUrl"] and parsed["requestedUrl"] != parsed["finalUrl"]:
        parsed["error"] = f"redirected to {parsed['finalUrl']}"
    return parsed


def median_of(runs: List[dict]) -> Dict[str, Optional[float]]:
    fields = ["performanceScore"] + [field for field, _audit in AUDITS]
    median: Dict[str, Optional[float]] = {}
    good = [run for run in runs if not run.get("error")]
    for field in fields:
        values = [run[field] for run in good if isinstance(run.get(field), (int, float))]
        median[field] = statistics.median(values) if values else None
    return median


def write_summary(summary: dict) -> None:
    out_root = Path(summary["outputDir"])
    (out_root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    csv_path = out_root / "summary.csv"
    fields = [
        "variant",
        "label",
        "run",
        "performance_score",
        "lcp_ms",
        "fcp_ms",
        "tbt_ms",
        "cls",
        "speed_index_ms",
        "requested_url",
        "final_url",
        "fetch_time",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for variant in summary["variants"]:
            for run in variant["runs"]:
                writer.writerow(
                    {
                        "variant": variant["id"],
                        "label": variant["label"],
                        "run": run.get("run"),
                        "performance_score": score_points(run.get("performanceScore")),
                        "lcp_ms": run.get("lcp_ms"),
                        "fcp_ms": run.get("fcp_ms"),
                        "tbt_ms": run.get("tbt_ms"),
                        "cls": run.get("cls"),
                        "speed_index_ms": run.get("speed_index_ms"),
                        "requested_url": run.get("requestedUrl"),
                        "final_url": run.get("finalUrl"),
                        "fetch_time": run.get("fetchTime"),
                        "error": run.get("error", ""),
                    }
                )
    print(f"Wrote {csv_path}")
    print(f"Wrote {out_root / 'summary.json'}")


def print_table(summary: dict, baseline_id: str) -> None:
    baseline = next((item for item in summary["variants"] if item["id"] == baseline_id), None)
    base_median = baseline["median"] if baseline else None
    if baseline is None:
        print(f"No variant with id {baseline_id!r}; deltas were not computed.")

    headers = [
        "variant",
        "score",
        "LCP",
        "FCP",
        "TBT",
        "CLS",
        "SI",
        "ΔLCP",
        "ΔFCP",
        "ΔTBT",
        "ΔCLS",
        "ΔSI",
        "Δscore",
    ]
    rows = []
    for variant in summary["variants"]:
        median = variant["median"]
        own = variant["id"] == baseline_id
        rows.append(
            [
                variant["id"],
                fmt_score(median.get("performanceScore")),
                fmt_ms(median.get("lcp_ms")),
                fmt_ms(median.get("fcp_ms")),
                fmt_ms(median.get("tbt_ms")),
                fmt_cls(median.get("cls")),
                fmt_ms(median.get("speed_index_ms")),
                "" if own else fmt_delta_ms(delta(median, base_median, "lcp_ms")),
                "" if own else fmt_delta_ms(delta(median, base_median, "fcp_ms")),
                "" if own else fmt_delta_ms(delta(median, base_median, "tbt_ms")),
                "" if own else fmt_delta_cls(delta(median, base_median, "cls")),
                "" if own else fmt_delta_ms(delta(median, base_median, "speed_index_ms")),
                "" if own else fmt_delta_score(delta(median, base_median, "performanceScore")),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render(cells: List[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))

    print("")
    print(
        f"Median of {summary['runsPerVariant']} run(s), {summary['formFactor']}, "
        f"{summary['origin']}, Lighthouse {summary['lighthouseVersion'] or 'unknown'}"
    )
    print("Δ = this variant minus baseline. Time and CLS: higher means more cost. Score: higher means a better Lighthouse score.")
    print(render(headers))
    print(render(["-" * width for width in widths]))
    for row in rows:
        print(render(row))
    if summary["failures"]:
        print("")
        print("Failed runs:")
        for failure in summary["failures"]:
            print(f"  {failure}")


def delta(median: dict, baseline: Optional[dict], field: str) -> Optional[float]:
    if baseline is None:
        return None
    current = median.get(field)
    reference = baseline.get(field)
    if not isinstance(current, (int, float)) or not isinstance(reference, (int, float)):
        return None
    return float(current) - float(reference)


def score_points(value: Optional[float]) -> Optional[int]:
    if not isinstance(value, (int, float)):
        return None
    return int(round(value * 100))


def fmt_score(value: Optional[float]) -> str:
    points = score_points(value)
    return "n/a" if points is None else str(points)


def fmt_ms(value: Optional[float]) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{value:.0f}"


def fmt_cls(value: Optional[float]) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{value:.3f}"


def fmt_delta_ms(value: Optional[float]) -> str:
    return "" if value is None else f"{value:+.0f}"


def fmt_delta_cls(value: Optional[float]) -> str:
    return "" if value is None else f"{value:+.3f}"


def fmt_delta_score(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value * 100:+.0f}"


def require_lighthouse(binary: List[str]) -> str:
    try:
        completed = subprocess.run(
            binary + ["--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
            cwd=str(benchlib.ROOT),
        )
    except OSError as err:
        raise SystemExit(f"Could not start Lighthouse: {err}")
    except subprocess.TimeoutExpired:
        raise SystemExit("lighthouse --version timed out")
    if completed.returncode != 0:
        detail = failure_detail(
            completed.stderr.decode("utf-8", errors="replace"),
            completed.returncode,
        )
        raise SystemExit(
            "Lighthouse could not start "
            f"({detail}). Node on this machine is {node_version()}. "
            "Lighthouse 13 needs Node 22.19 or newer.\n"
            "Run it from the lighthouse container instead, with the bench container already up:\n"
            "  docker compose --profile lighthouse run --rm lighthouse"
        )
    return completed.stdout.decode("utf-8", errors="replace").strip()


def node_version() -> str:
    try:
        completed = subprocess.run(
            ["node", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    return text or "unavailable"


def failure_detail(stderr: str, code: int) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("SyntaxError", "TypeError", "Error", "Error:")) or "Error:" in line:
            return line
    return lines[-1] if lines else f"exit {code}"


def lighthouse_host(config: dict) -> str:
    """Default hostname Lighthouse puts in a page URL. Defaults to the server host."""
    return config.get("lighthouseHost") or config["host"]


def measurement_host(config: dict, variant: dict) -> str:
    """Hostname Chrome opens for this variant.

    A variant host wins. Otherwise the run uses lighthouseHost, then the
    server host. The page server keeps listening on host either way.
    """
    return variant.get("host") or lighthouse_host(config)


def describe_lighthouse_host(config: dict) -> None:
    groups: Dict[str, List[str]] = {}
    for variant in config["variants"]:
        alias = measurement_host(config, variant)
        if alias == config["host"]:
            continue
        groups.setdefault(alias, []).append(variant["id"])
    for alias, ids in groups.items():
        joined = ", ".join(ids)
        print(
            f"Lighthouse opens http://{alias}:{config['port']}/ for {joined} "
            f"and connects {alias} to {config['host']}."
        )


def resolver_aliases(config: dict) -> List[str]:
    """Hostnames Chrome should send to the benchmark server, in first-seen order."""
    aliases: List[str] = []
    seen = set()
    candidates = [config.get("lighthouseHost")]
    candidates.extend(variant.get("host") for variant in config["variants"])
    for alias in candidates:
        if not alias or alias == config["host"] or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases


def host_resolver_rule(config: dict) -> Optional[str]:
    """Chrome MAP rules that send measurement hostnames to the benchmark server.

    The page URL keeps the approved hostname. Only those names are remapped,
    so each CMP's own script hosts still use public DNS.
    """
    aliases = resolver_aliases(config)
    if not aliases:
        return None
    target = config["host"]
    return ", ".join(f"MAP {alias} {target}" for alias in aliases)


def chrome_flags_value(no_sandbox: bool, config: dict) -> str:
    # Lighthouse 13 does not pass --headless itself. Chromium 154 then
    # selects the X11 backend and exits when the container has no display.
    flags = [
        "--headless=new",
        "--ozone-platform=headless",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if no_sandbox:
        flags.extend(["--no-sandbox", "--disable-dev-shm-usage"])
    rule = host_resolver_rule(config)
    if rule:
        # Lighthouse splits --chrome-flags on spaces unless the value is quoted.
        # These quotes stay in the argv string. Its parser strips them and
        # forwards one Chrome argument, --host-resolver-rules=MAP name ip.
        flags.append(f"--host-resolver-rules='{rule}'")
    return " ".join(flags)


def variant_url(config: dict, variant_id: str, host: Optional[str] = None) -> str:
    name = config["host"] if host is None else host
    return f"http://{name}:{config['port']}/{variant_id}/"


def fetch_status(url: str) -> Optional[int]:
    try:
        _body, status = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return status


def fetch(url: str):
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), response.status


if __name__ == "__main__":
    main()
