#!/usr/bin/env python3
"""
Crawl a website and output a single indexed markdown file for RAG.

Usage:
    python tools/crawl_to_markdown.py [url]

Output:
    output/<domain>/knowledge.md  # indexed markdown
    output/<domain>/knowledge.json  # raw docs
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from math import ceil
from typing import Any
from pathlib import Path
from urllib.parse import urlparse
from html import escape

import requests
from firecrawl import FirecrawlApp
from firecrawl.v2.types import ScrapeOptions

DEFAULT_API_URL = "http://localhost:3002"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"
DEFAULT_TELEMETRY_FILE = Path("output") / "_telemetry" / "crawl_runs.jsonl"
DEFAULT_COVERAGE_THRESHOLD = 0.9


def domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def prompt_yes_no(message: str, default: bool = True) -> bool:
    yes_values = {"y", "yes"}
    no_values = {"n", "no"}
    default_str = "Y/n" if default else "y/N"

    while True:
        resp = input(f"{message} [{default_str}]: ").strip().lower()
        if not resp:
            return default
        if resp in yes_values:
            return True
        if resp in no_values:
            return False
        print("Please respond with 'y' or 'n'.")


def parse_path_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    patterns = [segment.strip() for segment in raw.split(",")]
    patterns = [segment for segment in patterns if segment]
    return patterns or None


def prompt_path_filters(kind: str) -> list[str] | None:
    prompt = (
        f"Enter comma-separated {kind} path patterns "
        "(e.g., /docs/*). Leave blank to skip: "
    )
    raw = input(prompt).strip()
    return parse_path_list(raw)


def resolve_repo_relative(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def url_path_depth(raw_url: str) -> int:
    try:
        parsed = urlparse(raw_url)
        path = parsed.path.strip("/")
        if not path:
            return 0
        return len([segment for segment in path.split("/") if segment])
    except Exception:
        return -1


def build_depth_stats(docs: list[dict[str, Any]]) -> tuple[int, dict[int, int]]:
    depths: list[int] = []
    for doc in docs:
        metadata = doc.get("metadata") or {}
        source_url = metadata.get("sourceURL") or metadata.get("url")
        if not source_url:
            continue
        depth = url_path_depth(source_url)
        if depth >= 0:
            depths.append(depth)

    if not depths:
        return -1, {}

    counts = Counter(depths)
    distribution = dict(sorted(counts.items(), key=lambda item: item[0]))
    return max(depths), distribution


def append_telemetry_record(telemetry_file: Path, record: dict[str, Any]) -> None:
    try:
        telemetry_file.parent.mkdir(parents=True, exist_ok=True)
        with telemetry_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Telemetry appended to {telemetry_file}")
    except Exception as exc:
        print(f"Warning: unable to write telemetry file {telemetry_file}: {exc}")


def export_additional_formats(markdown_content: str, out_dir: Path, short_name: str, extra_formats: list[str]) -> None:
    for fmt in extra_formats:
        if fmt == "txt":
            txt_path = out_dir / f"{short_name}.txt"
            txt_path.write_text(markdown_content, encoding="utf-8")
            print(f"Saved plain text to {txt_path}")
        elif fmt == "html":
            html_body = escape(markdown_content)
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{short_name} knowledge base</title>
</head>
<body>
<pre>
{html_body}
</pre>
</body>
</html>
"""
            html_path = out_dir / f"{short_name}.html"
            html_path.write_text(html_content, encoding="utf-8")
            print(f"Saved HTML to {html_path}")
        else:
            print(f"Warning: unsupported export format '{fmt}', skipping.")


def verify_api_available(api_url: str) -> None:
    health_url = api_url.rstrip("/") + "/"
    try:
        resp = requests.get(health_url, timeout=5)
        if resp.ok:
            return
        raise RuntimeError(f"HTTP {resp.status_code}")
    except Exception as exc:
        print(f"Unable to reach Firecrawl API at {api_url}: {exc}")
        print("Helper: ensure Docker is running via `docker compose up` in the repo root,")
        print("and verify the API is listening on the configured port before re-running.")
        sys.exit(1)


def extract_job_id(job: Any) -> str | None:
    return getattr(job, "id", None) or (job.get("id") if isinstance(job, dict) else None)


def poll_crawl_status(
    app: FirecrawlApp,
    job_id: str,
    poll_interval: int,
    timeout: int,
    label: str = "crawl",
):
    start_time = time.time()
    last_state = None

    while True:
        status = app.get_crawl_status(job_id)
        state = getattr(status, "status", None) or (
            status.get("status") if isinstance(status, dict) else ""
        )
        completed = getattr(status, "completed", None)
        total = getattr(status, "total", None)
        line = f"{label} status: {state}"
        if completed is not None or total is not None:
            line += f" ({completed or 0}/{total or '?'})"
        if state != last_state:
            print(line)
            last_state = state
        if state in {"completed", "failed", "cancelled"}:
            return status, state
        if timeout and (time.time() - start_time) > timeout:
            print(f"{label} timed out after {timeout} seconds.")
            sys.exit(1)
        time.sleep(max(1, poll_interval))


def docs_from_status(status: Any) -> list[dict[str, Any]]:
    raw_docs = getattr(status, "data", None) or (
        status.get("data") if isinstance(status, dict) else []
    )
    if not raw_docs:
        return []

    docs: list[dict[str, Any]] = []
    for doc in raw_docs:
        if hasattr(doc, "model_dump"):
            doc_dict = doc.model_dump()
        else:
            doc_dict = doc
        metadata = doc_dict.get("metadata") or {}
        doc_dict["metadata"] = metadata
        docs.append(doc_dict)
    return docs


def run_pre_scan(
    app: FirecrawlApp,
    url: str,
    pre_scan_limit: int,
    pre_scan_max_depth: int,
    poll_interval: int,
    timeout: int,
) -> dict[str, Any] | None:
    print(
        f"Running pre-scan (limit={pre_scan_limit}, max_depth={pre_scan_max_depth}) "
        "to estimate site size..."
    )
    try:
        pre_job = app.start_crawl(
            url=url,
            limit=pre_scan_limit,
            max_discovery_depth=pre_scan_max_depth,
            scrape_options=ScrapeOptions(
                formats=["links"],
                only_main_content=True,
            ),
        )
    except Exception as exc:
        print(f"Pre-scan failed to start: {exc}")
        return None

    pre_job_id = extract_job_id(pre_job)
    if not pre_job_id:
        print("Pre-scan failed: could not determine job ID.")
        return None

    status, final_state = poll_crawl_status(
        app=app,
        job_id=pre_job_id,
        poll_interval=poll_interval,
        timeout=timeout,
        label="pre-scan",
    )
    if final_state != "completed":
        print(f"Pre-scan did not complete ({final_state}). Skipping auto-tune.")
        return None

    docs = docs_from_status(status)
    total = getattr(status, "total", None)
    page_count = total if isinstance(total, int) and total >= 0 else len(docs)
    max_observed_depth, depth_distribution = build_depth_stats(docs)
    hit_limit = page_count >= pre_scan_limit or len(docs) >= pre_scan_limit

    recommended_limit = max(100, int(ceil(max(page_count, len(docs), 1) * 1.25)))
    if hit_limit:
        recommended_limit = max(recommended_limit, pre_scan_limit * 2)
    # URL path depth is not equivalent to crawl link-discovery depth.
    # Use the pre-scan crawl budget as the safer recommendation target.
    recommended_max_depth = max(3, pre_scan_max_depth)

    dist = ", ".join(f"d{k}={v}" for k, v in depth_distribution.items())
    print(f"Pre-scan estimate: pages~{page_count}, max_path_depth={max_observed_depth}")
    if dist:
        print(f"Pre-scan depth distribution: {dist}")
    if hit_limit:
        print(
            "Pre-scan hit its page limit; estimate may be low. "
            "Use a higher --pre-scan-limit for a better estimate."
        )
    print(
        "Pre-scan recommendation: "
        f"--limit {recommended_limit} --max-depth {recommended_max_depth}"
    )

    return {
        "job_id": pre_job_id,
        "estimated_pages": page_count,
        "max_observed_depth": max_observed_depth,
        "depth_distribution": depth_distribution,
        "hit_limit": hit_limit,
        "recommended_limit": recommended_limit,
        "recommended_max_depth": recommended_max_depth,
        "pre_scan_limit": pre_scan_limit,
        "pre_scan_max_depth": pre_scan_max_depth,
    }


def crawl_and_index(
    url: str,
    limit: int = 100,
    max_depth: int = 3,
    api_url: str = DEFAULT_API_URL,
    poll_interval: int = 5,
    timeout: int = 600,
    extra_formats: list[str] | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    telemetry_enabled: bool = True,
    telemetry_file: str = str(DEFAULT_TELEMETRY_FILE),
    pre_scan_result: dict[str, Any] | None = None,
    app: FirecrawlApp | None = None,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
):
    started_at = datetime.now(timezone.utc)
    if app is None:
        verify_api_available(api_url)
        try:
            app = FirecrawlApp(api_url=api_url)
        except Exception as exc:
            print(f"Failed to initialize Firecrawl client at {api_url}: {exc}")
            sys.exit(1)

    def run_main_crawl_once(run_limit: int, run_depth: int, label: str):
        print(f"Starting crawl of {url} (limit={run_limit}, max_depth={run_depth})")
        try:
            job = app.start_crawl(
                url=url,
                limit=run_limit,
                max_discovery_depth=run_depth,
                include_paths=include_paths,
                exclude_paths=exclude_paths,
                scrape_options=ScrapeOptions(
                    formats=["markdown"],
                    only_main_content=True,
                ),
            )
        except Exception as exc:
            print(f"Failed to start crawl: {exc}")
            sys.exit(1)

        run_job_id = extract_job_id(job)
        if not run_job_id:
            print("Could not determine crawl job ID.")
            sys.exit(1)
        print(f"Job submitted: {run_job_id}")

        status, final_status = poll_crawl_status(
            app=app,
            job_id=run_job_id,
            poll_interval=poll_interval,
            timeout=timeout,
            label=label,
        )
        if final_status != "completed":
            print("Crawl did not complete:", status)
            sys.exit(1)

        raw_docs_local = getattr(status, "data", None) or (
            status.get("data") if isinstance(status, dict) else []
        )
        return run_job_id, final_status, raw_docs_local

    crawl_attempts: list[dict[str, Any]] = []
    job_id, final_status, raw_docs = run_main_crawl_once(
        run_limit=limit,
        run_depth=max_depth,
        label="crawl",
    )
    crawl_attempts.append(
        {
            "job_id": job_id,
            "limit": limit,
            "max_depth": max_depth,
            "document_count": len(raw_docs),
        }
    )

    expected_pages = None
    if pre_scan_result and isinstance(pre_scan_result.get("estimated_pages"), int):
        expected_pages = pre_scan_result["estimated_pages"]
    retry_needed = (
        expected_pages is not None
        and expected_pages > 0
        and len(raw_docs) < int(ceil(expected_pages * coverage_threshold))
    )
    if retry_needed:
        retry_limit = max(
            limit,
            pre_scan_result.get("recommended_limit", limit) if pre_scan_result else limit,
            int(ceil(expected_pages * 1.4)),
        )
        retry_depth = max(
            max_depth,
            pre_scan_result.get("pre_scan_max_depth", max_depth) if pre_scan_result else max_depth,
            max_depth + 2,
        )
        print(
            "Coverage retry triggered: "
            f"main crawl returned {len(raw_docs)} vs pre-scan estimate {expected_pages}. "
            f"Retrying with limit={retry_limit}, max_depth={retry_depth}."
        )
        retry_job_id, retry_status, retry_raw_docs = run_main_crawl_once(
            run_limit=retry_limit,
            run_depth=retry_depth,
            label="coverage-retry",
        )
        crawl_attempts.append(
            {
                "job_id": retry_job_id,
                "limit": retry_limit,
                "max_depth": retry_depth,
                "document_count": len(retry_raw_docs),
            }
        )
        if len(retry_raw_docs) > len(raw_docs):
            print(
                f"Coverage retry improved document count: {len(raw_docs)} -> {len(retry_raw_docs)}."
            )
            job_id = retry_job_id
            final_status = retry_status
            raw_docs = retry_raw_docs
            limit = retry_limit
            max_depth = retry_depth
        else:
            print(
                "Coverage retry did not improve document count. "
                "Keeping initial crawl result."
            )

    if not raw_docs:
        print("No documents returned.")
        sys.exit(1)

    def _doc_to_dict(doc):
        if hasattr(doc, "model_dump"):
            return doc.model_dump()
        return doc

    docs = []
    for doc in raw_docs:
        doc_dict = _doc_to_dict(doc)
        metadata = doc_dict.get("metadata") or {}
        if not metadata.get("sourceURL"):
            metadata["sourceURL"] = metadata.get("url", url)
        doc_dict["metadata"] = metadata
        docs.append(doc_dict)

    # Sort by URL for deterministic output
    docs = sorted(docs, key=lambda d: d["metadata"].get("sourceURL", ""))
    max_observed_depth, depth_distribution = build_depth_stats(docs)

    # Prepare output folder
    domain = domain_from_url(url)
    short_name = domain.split(".")[0] if "." in domain else domain
    out_dir = OUTPUT_ROOT / domain
    out_dir.mkdir(parents=True, exist_ok=True)

    # Add numeric IDs to each document for LLM navigation
    indexed_docs = []
    for idx, doc in enumerate(docs, 1):
        indexed_doc = {"id": idx, **doc}
        indexed_docs.append(indexed_doc)

    # Write raw JSON with IDs
    json_path = out_dir / f"{short_name}.json"
    json_path.write_text(json.dumps(indexed_docs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved raw JSON to {json_path}")

    # Build indexed markdown
    lines = [
        "# Knowledge Base",
        "",
        f"Source: {url}",
        f"Raw JSON: `{short_name}.json`",
        "",
        f"Crawl completed: {len(docs)} documents",
        "",
        "## Index",
    ]
    for idx, doc in enumerate(docs, 1):
        metadata = doc["metadata"]
        url_src = metadata.get("sourceURL") or metadata.get("url") or url
        title = metadata.get("title") or url_src
        lines.append(f"{idx}. [{title}](#doc-{idx}) – {url_src} (id: {idx})")

    lines.append("")
    for idx, doc in enumerate(docs, 1):
        metadata = doc["metadata"]
        url_src = metadata.get("sourceURL") or metadata.get("url") or url
        title = metadata.get("title") or url_src
        body = (doc.get("markdown") or "").strip() or "_No markdown content returned._"
        lines += [
            f"## Document {idx} — {title} {{#doc-{idx}}}",
            f"[{url_src}]({url_src})",
            "",
            body,
            ""
        ]

    markdown_content = "\n".join(lines)
    md_path = out_dir / f"{short_name}_index.md"
    md_path.write_text(markdown_content, encoding="utf-8")
    print(f"Saved indexed markdown to {md_path}")

    if extra_formats:
        export_additional_formats(markdown_content, out_dir, short_name, extra_formats)

    if max_observed_depth >= 0:
        dist = ", ".join(f"d{k}={v}" for k, v in depth_distribution.items())
        print(f"Depth check: max URL path depth observed = {max_observed_depth}")
        if dist:
            print(f"Depth distribution: {dist}")

    if limit and len(docs) >= limit:
        print(
            f"Warning: reached --limit ({limit}) with {len(docs)} documents. "
            "Consider increasing --limit for broader coverage."
        )

    if max_observed_depth >= max_depth:
        print(
            f"Warning: observed URL path depth ({max_observed_depth}) is >= "
            f"--max-depth ({max_depth}). Consider increasing --max-depth."
        )

    if telemetry_enabled:
        finished_at = datetime.now(timezone.utc)
        duration_seconds = round((finished_at - started_at).total_seconds(), 2)
        telemetry_target = resolve_repo_relative(telemetry_file)
        telemetry_record = {
            "timestamp_utc": finished_at.isoformat(),
            "job_id": job_id,
            "pre_scan_job_id": pre_scan_result.get("job_id") if pre_scan_result else None,
            "url": url,
            "api_url": api_url,
            "status": final_status,
            "duration_seconds": duration_seconds,
            "configured_limit": limit,
            "configured_max_depth": max_depth,
            "coverage_threshold": coverage_threshold,
            "include_paths": include_paths or [],
            "exclude_paths": exclude_paths or [],
            "document_count": len(docs),
            "max_observed_url_path_depth": max_observed_depth,
            "depth_distribution": depth_distribution,
            "pre_scan": pre_scan_result or {},
            "crawl_attempts": crawl_attempts,
            "output_dir": str(out_dir),
            "output_files": [
                str(json_path),
                str(md_path),
            ],
        }
        append_telemetry_record(telemetry_target, telemetry_record)


def main():
    parser = argparse.ArgumentParser(
        description="Crawl a site and produce a single indexed markdown file.",
        epilog="Example: python tools/crawl_to_markdown.py https://example.com --limit 50"
    )
    parser.add_argument("url", nargs="?", help="Target URL to crawl")
    parser.add_argument("--limit", type=int, default=100, help="Maximum pages to crawl")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum crawl depth")
    parser.add_argument("--api-url", default=None, help="Firecrawl API base URL (default: http://localhost:3002)")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between status checks")
    parser.add_argument("--timeout", type=int, default=600, help="Max seconds to wait for crawl completion")
    parser.add_argument(
        "--extra-formats",
        default="",
        help="Comma-separated list of extra exports (supported: txt,html). Leave blank to be prompted.",
    )
    parser.add_argument(
        "--include-paths",
        default="",
        help="Comma-separated list of path globs to include (e.g., /docs/*). Leave blank to be prompted.",
    )
    parser.add_argument(
        "--exclude-paths",
        default="",
        help="Comma-separated list of path globs to exclude (e.g., /blog/*). Leave blank to be prompted.",
    )
    parser.add_argument(
        "--telemetry-file",
        default=str(DEFAULT_TELEMETRY_FILE),
        help="Telemetry JSONL path (relative to repo root unless absolute).",
    )
    parser.add_argument(
        "--disable-telemetry",
        action="store_true",
        help="Disable local telemetry logging.",
    )
    parser.add_argument(
        "--pre-scan",
        dest="pre_scan",
        action="store_true",
        help="Enable lightweight pre-scan estimation before crawling (default: enabled).",
    )
    parser.add_argument(
        "--no-pre-scan",
        dest="pre_scan",
        action="store_false",
        help="Disable lightweight pre-scan estimation.",
    )
    parser.add_argument(
        "--auto-tune",
        dest="auto_tune",
        action="store_true",
        help="Enable auto-tune from pre-scan recommendations (default: enabled).",
    )
    parser.add_argument(
        "--no-auto-tune",
        dest="auto_tune",
        action="store_false",
        help="Disable auto-tuning from pre-scan recommendations.",
    )
    parser.add_argument(
        "--pre-scan-limit",
        type=int,
        default=200,
        help="Max pages for pre-scan estimation crawl (default: 200).",
    )
    parser.add_argument(
        "--pre-scan-max-depth",
        type=int,
        default=8,
        help="Max depth for pre-scan estimation crawl (default: 8).",
    )
    parser.add_argument(
        "--pre-scan-timeout",
        type=int,
        default=300,
        help="Timeout in seconds for pre-scan estimation (default: 300).",
    )
    parser.add_argument(
        "--coverage-threshold",
        type=float,
        default=DEFAULT_COVERAGE_THRESHOLD,
        help="Minimum main-crawl coverage ratio vs pre-scan estimate before retry (default: 0.9).",
    )
    parser.set_defaults(pre_scan=True, auto_tune=True)
    args = parser.parse_args()

    if args.url:
        target_url = args.url
    else:
        target_url = input("Enter the website URL to crawl (e.g., https://www.example.com): ").strip()
        if not target_url:
            print("A target URL is required.")
            sys.exit(1)

    api_url = args.api_url or input(f"Firecrawl API URL [{DEFAULT_API_URL}]: ").strip() or DEFAULT_API_URL

    if args.extra_formats:
        extra_formats = [fmt.strip().lower() for fmt in args.extra_formats.split(",") if fmt.strip()]
    else:
        extra_formats = ["txt", "html"] if prompt_yes_no("Generate additional format: txt/html exports?", default=True) else []

    include_paths = parse_path_list(args.include_paths) if args.include_paths else prompt_path_filters("include")
    exclude_paths = parse_path_list(args.exclude_paths) if args.exclude_paths else prompt_path_filters("exclude")

    verify_api_available(api_url)
    try:
        app = FirecrawlApp(api_url=api_url)
    except Exception as exc:
        print(f"Failed to initialize Firecrawl client at {api_url}: {exc}")
        sys.exit(1)

    pre_scan_result = None
    effective_limit = args.limit
    effective_max_depth = args.max_depth
    if args.pre_scan:
        pre_scan_result = run_pre_scan(
            app=app,
            url=target_url,
            pre_scan_limit=args.pre_scan_limit,
            pre_scan_max_depth=args.pre_scan_max_depth,
            poll_interval=args.poll_interval,
            timeout=args.pre_scan_timeout,
        )
        if pre_scan_result and args.auto_tune:
            tuned_limit = max(effective_limit, pre_scan_result["recommended_limit"])
            tuned_max_depth = max(
                effective_max_depth, pre_scan_result["recommended_max_depth"]
            )
            if tuned_limit != effective_limit or tuned_max_depth != effective_max_depth:
                print(
                    "Auto-tune applied: "
                    f"limit {effective_limit} -> {tuned_limit}, "
                    f"max-depth {effective_max_depth} -> {tuned_max_depth}"
                )
            effective_limit = tuned_limit
            effective_max_depth = tuned_max_depth
        elif pre_scan_result and not args.auto_tune:
            print("Pre-scan completed. Auto-tune is disabled (--no-auto-tune).")
    elif args.auto_tune:
        print("Auto-tune requested but pre-scan is disabled; no tuning applied.")

    crawl_and_index(
        target_url,
        limit=effective_limit,
        max_depth=effective_max_depth,
        api_url=api_url,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        extra_formats=extra_formats,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        telemetry_enabled=not args.disable_telemetry,
        telemetry_file=args.telemetry_file,
        pre_scan_result=pre_scan_result,
        app=app,
        coverage_threshold=args.coverage_threshold,
    )


if __name__ == "__main__":
    main()
