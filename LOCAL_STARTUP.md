# Firecrawl Local Startup Guide

This is a practical startup guide for your local Firecrawl workspace, including:

- Syncing the latest upstream code without losing local `tools/` and `output/`
- Starting Firecrawl with Docker Desktop
- Verifying the API is live
- Running your custom crawl tool

## Quick Daily Workflow

1. Start Docker Desktop and wait until the engine says "Running".
2. Sync upstream safely:

   ```powershell
   python tools/sync_firecrawl.py --remote upstream --branch main --protected tools,output
   ```

3. Start Firecrawl:

   ```powershell
   docker compose up -d
   ```

4. Verify API:

   ```powershell
   (Invoke-WebRequest http://localhost:3002/test).Content
   ```

5. Run crawler tool:

   ```powershell
   python tools/crawl_to_markdown.py --url "https://example.com"
   ```

## First-Time Setup

### 1) Prerequisites

- Docker Desktop
- Python 3.7+
- Node.js
- pnpm (v9+ recommended by project docs)

### 2) (Recommended) Create a Python virtual environment for local tools

You do not need a `.venv` to start Firecrawl with Docker.
Use a `.venv` for Python tooling (`tools/crawl_to_markdown.py`, `tools/sync_firecrawl.py`) to keep dependencies isolated.

From repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e apps/python-sdk
pip install requests
```

When opening a new terminal later, reactivate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3) Configure API env file once

From repo root:

```powershell
if (!(Test-Path "apps/api/.env")) { Copy-Item "apps/api/.env.example" "apps/api/.env" }
```

Default local values in `apps/api/.env` should include:

- `PORT=3002`
- `HOST=0.0.0.0`
- `REDIS_URL=redis://localhost:6379`
- `REDIS_RATE_LIMIT_URL=redis://localhost:6379`
- `NUQ_DATABASE_URL=postgres://postgres:postgres@localhost:5433/postgres`

## Sync Upstream Safely

Use your custom sync script to pull upstream while preserving local `tools/` and `output/`.

```powershell
python tools/sync_firecrawl.py --remote upstream --branch main --protected tools,output
```

Notes:

- Script requires a clean working tree before running.
- Script flow: archive protected dirs, fetch/merge upstream, restore/stage protected dirs.
- If you do not have an `upstream` remote yet:

  ```powershell
  git remote add upstream https://github.com/firecrawl/firecrawl.git
  ```

## Start Firecrawl

1. Ensure Docker Desktop is running.
2. From repo root:

   ```powershell
   docker compose up -d
   ```

3. Optional: watch logs:

   ```powershell
   docker compose logs -f
   ```

4. Stop services when done:

   ```powershell
   docker compose down
   ```

## Verify the App

Health endpoint:

```powershell
(Invoke-WebRequest http://localhost:3002/test).Content
```

Expected response: `Hello, world!`

Queue UI:

- `http://localhost:3002/admin/CHANGEME/queues`

## Run Custom Tools

### Crawl to Markdown

Interactive:

```powershell
python tools/crawl_to_markdown.py
```

Direct args:

```powershell
python tools/crawl_to_markdown.py `
  --url "https://example.com" `
  --api-url "http://localhost:3002" `
  --limit 50 `
  --max-depth 2 `
  --include-paths "/docs/*" `
  --exclude-paths "/blog/*"
```

Outputs are written to:

- `output/<domain>/<short_name>.json`
- `output/<domain>/<short_name>_index.md`
- optional `txt/html` exports

## Troubleshooting

- `Cannot connect to Docker daemon`: Docker Desktop is not fully started yet.
- `localhost:3002 not reachable`: run `docker compose ps` and inspect `docker compose logs -f`.
- Sync script says worktree not clean: commit/stash changes, then rerun.
- Crawler cannot reach API: confirm `http://localhost:3002` is up before running tool.
