*English | [Deutsch](README_de.md)*

# pp-mcp — MCP Server for Portfolio Performance

A read-only MCP server that provides filtered account and portfolio data from one or
more [Portfolio Performance](https://www.portfolio-performance.info/) `.portfolio`
files — e.g. to generate reports from them (transactions of an account,
distributions/interest/taxes for a period, etc.). It also values holdings, computes
realized and unrealized gains (FIFO by default, as German tax law requires, or
Portfolio Performance's moving-average method) and can simulate the gain of a planned
sale (`simulate_sale`) as the basis for a tax estimate.

Files are only **read**, never modified. Supports unencrypted and AES-encrypted
(password-protected) files. Works as a standard [MCP](https://modelcontextprotocol.io)
server with any MCP-compatible AI assistant (Claude, etc.) or your own scripts.

**📖 Full documentation is in the [Wiki](https://github.com/Nokke32/pp-mcp/wiki)**
— installation (local & Docker, single- & multi-source), connecting AI assistants
(Claude Desktop, Claude Code, others), example prompts, and the complete tool
reference (parameters/return values) for scripting against pp-mcp directly.

## Quick start

```bash
pip install -r requirements.txt
export PP_FILE_PATH=/path/to/file.portfolio
python -m src.main   # from the repo root; runs on http://localhost:8080
```

Or with Docker:

```bash
cp .env.example .env
docker-compose -f docker-compose.dev.yml up -d --build
```

See the [Installation](https://github.com/Nokke32/pp-mcp/wiki/Installation) wiki
page for the production/multi-source Docker setup, all environment variables, and
connecting an AI assistant
([Configuring AI Tools](https://github.com/Nokke32/pp-mcp/wiki/Configuring-AI-Tools)).

## Terminology

Portfolio Performance uses the word "portfolio" for two different things, which can
be ambiguous — pp-mcp uses these terms consistently everywhere (tool descriptions,
parameters, the wiki):

- **Source** (parameter `source`) — one complete `.portfolio` file, i.e. one
  configured data source. See `list_data_sources`.
- **Portfolio** (parameter `portfolio_name`) — a securities portfolio/depot *within*
  a source (Portfolio Performance's own internal term for this object). See
  `list_portfolios`.
- **Account** (parameter `account`) — a cash account within a source. See
  `list_accounts`.
- **Security** (parameter `security`) — a stock, fund, ETF, etc. See `list_securities`.

If it's unclear whether "portfolio" refers to a source or a portfolio/depot in a
given context, check `list_data_sources` and `list_portfolios` to see which one
actually matches.

## Changes

A summary of notable changes, newest first. Parameters and return values of all tools
are described in the
[Function Reference](https://github.com/Nokke32/pp-mcp/wiki/Scripts-Function-Reference).

**2026-11**
- Realized and unrealized gains now use **FIFO by default** (as German tax law
  requires); the new `method` parameter (`fifo` | `moving_average`) switches back to
  Portfolio Performance's moving-average method.
- `get_unrealized_gains` can return the remaining purchase lots per position
  (`include_lots`, on automatically when `security` is set).
- New tool **`simulate_sale`**: computes cost basis, proceeds and gain of a planned
  (partial) sale from the FIFO lots of one portfolio — books nothing, calculates no
  taxes.

**2026-08**
- Documentation moved to the
  [Wiki](https://github.com/Nokke32/pp-mcp/wiki); the README is now a short
  overview.
- `mcp` dependency pinned to `<2` (v2 has breaking changes).
- `docker-compose.yml`: optional `MCP_BIND_HOST` for binding the port directly
  (e.g. in a VPN).

**2026-07**
- **Multi-source:** one server instance serves several `.portfolio` files
  (`PP_PORTFOLIOS_CONFIG`, `source` parameter, `list_data_sources`).
- New tools for prices (`get_latest_price`, `get_price_history`, `get_price_on`,
  `list_latest_prices`), valuation (`get_holdings`, `get_holdings_history`), gains
  (`get_unrealized_gains`, `get_realized_gains`), `get_account_balance`, taxonomies /
  asset allocation (`list_taxonomies`, `get_asset_allocation`) and
  `list_investment_plans`.
- `list_price_feeds` / `refresh_prices`: fetch missing prices via the Ariva feed.
- `stdio` transport in addition to `streamable-http`/`sse`
  ([Configuring AI Tools](https://github.com/Nokke32/pp-mcp/wiki/Configuring-AI-Tools)).
- Security hardening: sanitized error messages, enforceable auth
  (`MCP_AUTH_TOKEN`), `MCP_SERVER_HOST` defaults to `127.0.0.1`.
- Fixed price scaling in the parser; configurable `LOG_LEVEL`; tool descriptions in
  English; MIT license.

## Historical ECB rates for Python callers

```python
from src.ecb_rates import load_ecb_rates

usd_to_eur = load_ecb_rates().history("USD", "EUR")
```

This returns EUR per USD on ECB observation dates. The library refreshes the
historical archive on demand when the cache is missing or more than an hour old
and falls back to the last valid cache if a refresh fails. Set
`PP_ECB_CACHE_DIR` to use a different cache directory, or pass a local ECB ZIP or
CSV path to `load_ecb_rates` for offline use.

## Structure

- `src/config.py` — Pydantic settings (env / `.env`).
- `src/portfolio.py` — `Portfolio` class (mtime-based cache, name↔UUID resolution,
  filtering & aggregation, one instance per source) + `PortfolioRegistry` (manages
  multiple `Portfolio` instances based on the configured sources, one per `source` id).
- `src/mcp_server.py` — FastMCP tools (thin wrappers around the registry), optional bearer auth.
- `src/price_feed.py` — SSRF-protected scraper for the `GENERIC_HTML_TABLE` price feed
  (ariva.de), used by `refresh_prices`.
- `src/main.py` — server startup.
- `src/pp_parser/` — vendored parser (decrypts/decompresses the file, reads protobuf).
