# Multi-Browser Automation MCP Server

A FastMCP 3.x server providing multi-engine browser automation via the MCP protocol. Supports Camoufox (Playwright-based), DrissionPage, and Browser Use (AI agent) with datacenter proxy rotation.

## Features

- **Three engines**: Camoufox (anti-detect), DrissionPage (lightweight), Browser Use (AI agent)
- **Proxy support**: 25-datacenter proxy pool (off by default), per-engine application
- **FastMCP 3.x**: Modern SSE/HTTP/stdio transports, Prefect Horizon cloud-ready
- **Browser Use agent**: LLM-driven automation via OpenAI-compatible API (9Router or direct)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install browsers (first time only)
python -m playwright install
camoufox fetch

# Run server (SSE on 127.0.0.1:8000)
fastmcp run server.py

# Or with custom transport/port
fastmcp run server.py --transport http --port 8080
fastmcp run server.py --transport stdio

# Also works directly
python server.py
python server.py --transport http --port 8080
```

## Tools

| Tool | Description |
|------|-------------|
| `set_active_engine(engine)` | Switch active engine: `camoufox` or `drissionpage` |
| `enable_drissionpage(enable)` | Enable/disable DrissionPage (off by default) |
| `set_proxy(enable, proxy?)` | Toggle proxy; optional `proxy` URL overrides random pick |
| `get_proxy_status()` | View current proxy state and pool size |
| `navigate(url)` | Open URL with active engine |
| `get_page_source()` | Get truncated HTML of current page |
| `click_element(selector)` | Click element by CSS/XPath |
| `run_browser_use(task, max_steps?, headless?)` | Run AI agent task (requires LLM) |
| `close_browser()` | Close all browser instances |

## Proxy

`proxies.txt` contains 25 datacenter proxies (user:pass@host:port). Proxy is **disabled by default**.

```python
# Enable with random proxy from pool
await set_proxy(True)

# Enable with specific proxy
await set_proxy(True, "http://user:pass@host:port")

# Disable
await set_proxy(False)
```

When toggling proxy, any running browser restarts automatically to apply the change.

## Browser Use (AI Agent)

Requires an OpenAI-compatible LLM endpoint:

| Env var | Purpose |
|---------|---------|
| `OPENAI_API_KEY` | Direct OpenAI key |
| `OPENAI_BASE_URL` | Custom OpenAI base URL |
| `NINEROUTER_URL` | 9Router gateway URL |
| `NINEROUTER_KEY` | 9Router API key |
| `BROWSER_USE_MODEL` | Model name (default: `gpt-4o`) |

Example task:
```python
await run_browser_use(
    task="Go to github.com, search for 'fastmcp', click first result, return repo stars",
    max_steps=20,
    headless=True
)
```

## Engines

### Camoufox (default)
Playwright-based with anti-detection. Best for sites with bot protection.

### DrissionPage
Lightweight, fast, no Playwright dependency. Enable first:
```python
await enable_drissionpage(True)
await set_active_engine("drissionpage")
```

### Browser Use
AI agent that plans and executes multi-step tasks. Runs isolated Chromium session.

## Project Structure

```
.
├── server.py         # FastMCP server with all tools
├── requirements.txt  # Pinned dependencies
├── proxies.txt       # Proxy pool (gitignored in public, committed to private)
└── LICENSE
```

## Development

```bash
# Check dependencies
pip check

# Lint/type-check (if configured)
ruff check .
mypy .

# Run with auto-reload (FastMCP dev mode)
fastmcp dev server.py
```

## Notes

- `proxies.txt` contains credentials; it's in `.gitignore` and only committed to the private repo.
- First run: `python -m playwright install && camoufox fetch` to download browsers.
- Server binds to `127.0.0.1:8000` by default (SSE). Use `--host 0.0.0.0` for LAN access.