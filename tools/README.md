# Crawl to Markdown Tool

A Python script that crawls a website and generates RAG-ready output files for LLM consumption.

## Features

- Crawls entire websites with configurable depth and limits
- Generates indexed markdown files with document IDs
- Creates JSON output with structured data and numeric IDs
- Optional additional formats (TXT, HTML)
- Interactive prompts for missing parameters
- Docker API health checks
- Domain-based output naming
- Include/exclude path filters (e.g., crawl only `/docs/*`)
- Coverage checks (warns when `--limit`/`--max-depth` may clip results)
- Coverage retry (automatically retries crawl if main result is far below pre-scan estimate)
- Telemetry logging to `output/_telemetry/crawl_runs.jsonl`

## Requirements

- Python 3.7+
- Firecrawl Python SDK v2
- Docker and Docker Compose (for local API server)

## Setup

1. Start the Firecrawl API server:

   ```bash
   docker compose up -d
   ```

2. Install the Python SDK:

   ```bash
   cd apps/python-sdk
   pip install -e .
   ```

## Usage

### Basic Usage

```bash
python tools/crawl_to_markdown.py
```

The script will prompt for:

- URL to crawl (default: https://www.biotunechiropractic.com.au/)
- API endpoint (default: http://localhost:3002)
- Additional format generation (default: yes)
- Include/exclude path patterns (press Enter to skip)

### Advanced Usage

```bash
python tools/crawl_to_markdown.py \
  "https://example.com" \
  --api-url "http://localhost:3002" \
  --limit 50 \
  --max-depth 2 \
  --extra-formats txt,html \
  --include-paths "/docs/*" \
  --exclude-paths "/blog/*"
```

### Default Pre-Scan + Auto-Tune

```bash
python tools/crawl_to_markdown.py \
  "https://docs.api.pracsuite.com/" \
  --pre-scan-limit 300 \
  --pre-scan-max-depth 8
```

Pre-scan and auto-tune are enabled by default. The script estimates page count/depth first, then raises `--limit`/`--max-depth` when needed.

To skip it:

```bash
python tools/crawl_to_markdown.py "https://example.com" --no-pre-scan --no-auto-tune
```

### Docs-only Example

```bash
python tools/crawl_to_markdown.py \
  "https://elevenlabs.io/docs/" \
  --include-paths "/docs/*" \
  --extra-formats ""
```

### Parameters

- `url`: Website URL to crawl (positional)
- `--api-url`: Firecrawl API endpoint
- `--limit`: Maximum number of pages (default: 100)
- `--max-depth`: Maximum crawl depth (default: 3)
- `--extra-formats`: Additional formats (txt,html)
- `--include-paths`: Comma-separated path globs to include (e.g., `/docs/*`)
- `--exclude-paths`: Comma-separated path globs to exclude (e.g., `/blog/*`)
- `--poll-interval`: Status polling interval in seconds (default: 5)
- `--timeout`: Crawl timeout in seconds (default: 600)
- `--telemetry-file`: JSONL file for crawl telemetry (default: `output/_telemetry/crawl_runs.jsonl`)
- `--disable-telemetry`: Turn off telemetry logging
- `--pre-scan`: Enable lightweight estimation before the main crawl (default: on)
- `--no-pre-scan`: Disable pre-scan
- `--auto-tune`: Enable applying pre-scan recommendations (default: on)
- `--no-auto-tune`: Disable applying pre-scan recommendations
- `--pre-scan-limit`: Max pages pre-scan can explore (default: 200)
- `--pre-scan-max-depth`: Max depth used by pre-scan (default: 8)
- `--pre-scan-timeout`: Pre-scan timeout in seconds (default: 300)
- `--coverage-threshold`: Minimum main-crawl coverage vs pre-scan estimate before retry (default: 0.9)

## Output

Files are saved to repo-root `output/<domain>/`:

- `<domain>.json` - Structured data with document IDs
- `<domain>_index.md` - Indexed markdown with JSON references
- `<domain>.txt` - Plain text (optional)
- `<domain>.html` - HTML format (optional)

## Example

```bash
python tools/crawl_to_markdown.py "https://www.biotunechiropractic.com.au/"
```

Output:
```
output/biotunechiropractic.com.au/
├── biotunechiropractic.json
├── biotunechiropractic_index.md
├── biotunechiropractic.txt
└── biotunechiropractic.html
```

## Keeping Local Outputs Safe During Upstream Syncs

Use `tools/sync_firecrawl.py` to merge upstream updates without losing local tooling/output:

```bash
python tools/sync_firecrawl.py \
  --remote upstream \
  --branch main \
  --protected tools,output
```

The script:

1. Verifies the working tree is clean.
2. Archives the protected directories.
3. Fetches and merges the specified upstream branch.
4. Restores and stages the protected directories so their contents stay untouched.

## Notes

- The script automatically checks if the Docker API is running
- Pre-scan + auto-tune runs by default and adds an extra crawl step before the main crawl
- If main crawl returns far fewer pages than pre-scan estimate, the script retries once with stronger depth/limit
- JSON files include numeric IDs for easy LLM reference
- Markdown files include links to corresponding JSON data
- Telemetry logs include job id, runtime, depth distribution, and coverage signals
- Use Ctrl+C to cancel crawling at any time
