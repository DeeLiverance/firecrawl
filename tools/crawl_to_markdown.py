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
from pathlib import Path
from urllib.parse import urlparse
from html import escape

import requests
from firecrawl import FirecrawlApp
from firecrawl.v2.types import ScrapeOptions

DEFAULT_API_URL = "http://localhost:3002"


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
):
    verify_api_available(api_url)

    try:
        app = FirecrawlApp(api_url=api_url)
    except Exception as exc:
        print(f"Failed to initialize Firecrawl client at {api_url}: {exc}")
        sys.exit(1)

    print(f"Starting crawl of {url}")
    try:
        job = app.start_crawl(
            url=url,
            limit=limit,
            max_discovery_depth=max_depth,
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

    job_id = getattr(job, "id", None) or (job.get("id") if isinstance(job, dict) else None)
    if not job_id:
        print("Could not determine crawl job ID.")
        sys.exit(1)
    print(f"Job submitted: {job_id}")

    start_time = time.time()
    last_state = None
    while True:
        status = app.get_crawl_status(job_id)
        state = getattr(status, "status", None) or (status.get("status") if isinstance(status, dict) else "")
        completed = getattr(status, "completed", None)
        total = getattr(status, "total", None)
        if state != last_state:
            sentence = f"Status: {state}"
        else:
            sentence = f"Status: {state}"
        if completed is not None or total is not None:
            sentence += f" ({completed or 0}/{total or '?'})"
        print(sentence)
        last_state = state
        if state in {"completed", "failed", "cancelled"}:
            break
        if timeout and (time.time() - start_time) > timeout:
            print(f"Crawl timed out after {timeout} seconds.")
            sys.exit(1)
        time.sleep(max(1, poll_interval))

    final_status = getattr(status, "status", None) or (status.get("status") if isinstance(status, dict) else "")
    if final_status != "completed":
        print("Crawl did not complete:", status)
        sys.exit(1)

    raw_docs = getattr(status, "data", None) or (status.get("data") if isinstance(status, dict) else [])
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

    # Prepare output folder
    domain = domain_from_url(url)
    short_name = domain.split(".")[0] if "." in domain else domain
    out_dir = Path("output") / domain
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

    crawl_and_index(
        target_url,
        limit=args.limit,
        max_depth=args.max_depth,
        api_url=api_url,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        extra_formats=extra_formats,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
    )


if __name__ == "__main__":
    main()
