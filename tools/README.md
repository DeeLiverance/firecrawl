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
  --url "https://example.com" \
  --api-url "http://localhost:3002" \
  --limit 50 \
  --max-depth 2 \
  --extra-formats txt,html \
  --include-paths "/docs/*" \
  --exclude-paths "/blog/*"
```

### Docs-only Example

```bash
python tools/crawl_to_markdown.py \
  --url "https://elevenlabs.io/docs/" \
  --include-paths "/docs/*" \
  --extra-formats ""
```

### Parameters

- `--url`: Website URL to crawl
- `--api-url`: Firecrawl API endpoint
- `--limit`: Maximum number of pages (default: 100)
- `--max-depth`: Maximum crawl depth (default: 3)
- `--extra-formats`: Additional formats (txt,html)
- `--include-paths`: Comma-separated path globs to include (e.g., `/docs/*`)
- `--exclude-paths`: Comma-separated path globs to exclude (e.g., `/blog/*`)
- `--poll-interval`: Status polling interval in seconds (default: 5)
- `--timeout`: Crawl timeout in seconds (default: 600)

## Output

Files are saved to `output/<domain>/`:

- `<domain>.json` - Structured data with document IDs
- `<domain>_index.md` - Indexed markdown with JSON references
- `<domain>.txt` - Plain text (optional)
- `<domain>.html` - HTML format (optional)

## Example

```bash
python tools/crawl_to_markdown.py --url "https://www.biotunechiropractic.com.au/"
```

Output:
```
output/biotunechiropractic.com.au/
├── biotunechiropractic.json
├── biotunechiropractic_index.md
├── biotunechiropractic.txt
└── biotunechiropractic.html
```

## Notes

- The script automatically checks if the Docker API is running
- JSON files include numeric IDs for easy LLM reference
- Markdown files include links to corresponding JSON data
- Use Ctrl+C to cancel crawling at any time
