#!/usr/bin/env python3
"""
Convert PDF to JSON, one file per page, using Firecrawl.

Firecrawl v2 accepts only http/https URLs. To process local PDFs, this script:
1) Splits the source PDF into one-page PDFs.
2) Serves the temp folder over a local HTTP server.
3) Scrapes each page URL and writes page_XXX.json.
"""

import argparse
import json
import re
import socket
import sys
import threading
import time
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from pypdf import PdfReader, PdfWriter

# Add repo root to path for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

from firecrawl import Firecrawl


class QuietStaticHandler(SimpleHTTPRequestHandler):
    """HTTP handler that suppresses request logs."""

    def log_message(self, _format, *_args):
        return


@contextmanager
def serve_directory(directory: Path):
    """Serve a directory over HTTP on a random free port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    port = sock.getsockname()[1]
    sock.close()

    handler = partial(QuietStaticHandler, directory=str(directory))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)

    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


def extract_text_from_markdown(markdown: str) -> str:
    """Extract plain text from markdown."""
    text = re.sub(r"#+\s*", "", markdown)  # Headers
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # Bold
    text = re.sub(r"\*(.*?)\*", r"\1", text)  # Italic
    text = re.sub(r"`(.*?)`", r"\1", text)  # Inline code
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)  # Links
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)  # Images
    return text.strip()


def build_page_pdf(reader: PdfReader, page_index: int, page_pdf: Path):
    """Write a single PDF page to a standalone PDF file."""
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    with open(page_pdf, "wb") as f:
        writer.write(f)


def process_pdf_page_by_page(
    pdf_path: Path,
    output_dir: Path,
    api_url: str = "http://localhost:3002",
    host_for_container: str = "host.docker.internal",
):
    """Process each page of a PDF into a JSON file."""
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    app = Firecrawl(api_url=api_url)

    print(f"Processing PDF: {pdf_path}")
    print(f"Detected pages: {total_pages}")

    with TemporaryDirectory(prefix="pdf_pages_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)

        for page_index in range(total_pages):
            page_num = page_index + 1
            page_pdf = tmp_dir_path / f"page_{page_num:03d}.pdf"
            build_page_pdf(reader, page_index, page_pdf)

        with serve_directory(tmp_dir_path) as port:
            print(
                f"Serving temp pages on http://{host_for_container}:{port}/ for Firecrawl ingestion."
            )

            for page_index in range(total_pages):
                page_num = page_index + 1
                page_file = f"page_{page_num:03d}.pdf"
                page_url = f"http://{host_for_container}:{port}/{quote(page_file)}"

                print(f"[{page_num}/{total_pages}] Scraping {page_file}...")
                try:
                    doc = app.scrape(
                        page_url,
                        formats=["markdown"],
                        parsers=[{"type": "pdf", "maxPages": 1}],
                    )
                except Exception as exc:
                    print(f"[ERR] Page {page_num} failed: {exc}")
                    if "Connection violated security rules" in str(exc):
                        print(
                            "[HINT] Set ALLOW_LOCAL_WEBHOOKS=true in Docker env and restart the api service."
                        )
                    continue

                markdown = doc.markdown or ""
                metadata = doc.metadata
                page_data = {
                    "page_number": page_num,
                    "total_pages": total_pages,
                    "source_file": pdf_path.name,
                    "content": {
                        "markdown": markdown,
                        "text": extract_text_from_markdown(markdown),
                    },
                    "metadata": {
                        "status_code": getattr(metadata, "status_code", None),
                        "content_type": getattr(metadata, "content_type", None),
                        "source_url": getattr(metadata, "source_url", None),
                        "scrape_id": getattr(metadata, "scrape_id", None),
                        "num_pages_reported": getattr(metadata, "num_pages", None),
                        "warning": getattr(doc, "warning", None),
                    },
                }

                output_file = output_dir / f"page_{page_num:03d}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(page_data, f, indent=2, ensure_ascii=False)

                print(f"[OK] Saved: {output_file}")

    print(f"Completed. Wrote page JSON files to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to per-page JSON using Firecrawl"
    )
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="output/pdf_pages",
        help="Output directory (default: output/pdf_pages)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:3002",
        help="Firecrawl API URL (default: http://localhost:3002)",
    )
    parser.add_argument(
        "--host-for-container",
        default="host.docker.internal",
        help="Host name the API container should use to reach the local HTTP server",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    output_dir = Path(args.output_dir)

    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    if pdf_path.suffix.lower() != ".pdf":
        print(f"Error: File must be a PDF: {pdf_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    process_pdf_page_by_page(
        pdf_path=pdf_path,
        output_dir=output_dir,
        api_url=args.api_url,
        host_for_container=args.host_for_container,
    )


if __name__ == "__main__":
    main()
