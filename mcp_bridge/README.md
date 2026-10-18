# MCP bridge

This stdio adapter exposes the MCP-01 task tools and forwards requests to the shared HTTP backend. The server uses the official Python MCP SDK 1.x, does not access SQLite, and never accepts a caller task identity or role parameter. The backend derives identity and enforces permissions from the bearer token.

## Environment

| Variable | Required | Meaning |
| --- | --- | --- |
| `RELAY_API_URL` | yes | HTTP(S) backend origin, for example `http://127.0.0.1:8765`; do not append `/api` or a path. |
| `RELAY_TASK_TOKEN` | yes | Task token issued by the backend. Keep it out of source control and logs. |
| `RELAY_HTTP_TIMEOUT_SECONDS` | no | HTTP timeout in seconds, default `10`; allowed range is greater than 0 and at most 300. |

The adapter requires a task token for each process. Keep the token in the local process environment or your MCP client's protected environment configuration. Never put a real token in a checked-in config file.

## Run directly

From the repository root, set the two required variables in the current PowerShell session, then run:

```powershell
$env:RELAY_API_URL = 'http://127.0.0.1:8765'
$env:RELAY_TASK_TOKEN = '<task-token-from-backend>'
\.venv\Scripts\python.exe -B .\mcp_bridge\server.py
```

The process speaks MCP only on stdin/stdout. Diagnostics go to stderr. Press Ctrl+C to stop it.

## Codex stdio configuration

Add this server entry to the local Codex MCP configuration, substituting absolute paths for this checkout. `env_vars` forwards the task token from the environment in which Codex runs; set `RELAY_TASK_TOKEN` in that environment before starting Codex. The token is intentionally not included in the example.

```toml
[mcp_servers.relay]
command = 'D:\Projects\hackerson\.venv\Scripts\python.exe'
args = ['-B', 'D:\Projects\hackerson\mcp_bridge\server.py']
env_vars = ['RELAY_TASK_TOKEN']

[mcp_servers.relay.env]
RELAY_API_URL = 'http://127.0.0.1:8765'
```

Use a distinct backend-issued token for each task. An explicit `cwd` is not required; the entry point resolves the repository from its own file path. For remote backends, set an address reachable from this machine and use HTTPS where appropriate.

## MCP-01 tools

The adapter exposes only `get_my_context`, `update_my_context` and `query_module`. Their input schemas come from the shared Pydantic request models. `query_module.task_id` is the query target; identity for all three tools remains bound to the process token.

Context updates pass `expected_version` and explicitly supplied fields to the backend without business validation or automatic write retries. Omitted fields remain omitted; explicit `null` is forwarded for the backend to ignore; `""` is forwarded to clear a field. A stale version remains a backend 409, and callers should reread and compare before deciding what to do.

## Checks

```powershell
\.venv\Scripts\python.exe -B .\scripts\check_contracts.py
\.venv\Scripts\python.exe -B -m pytest .\mcp_bridge\tests -q --basetemp=.tmp/pytest -o cache_dir=.cache/pytest
```

The stdio integration tests start an actual MCP SDK client and subprocess against an in-process simulated HTTP backend. They verify discovery, forwarding, error mapping and transport failures; they do not constitute real-backend integration. Real backend checks still require a backend address and task test tokens.
