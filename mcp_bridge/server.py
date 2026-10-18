"""MCP-01: three task tools over the official MCP Python SDK 1.x stdio transport."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# Support an absolute script entrypoint from Codex regardless of its working directory.
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from contracts.requests import ContextUpdate, Empty, QueryModule
from mcp_bridge.http_client import BackendError, ConfigurationError, RelayHTTPClient, Settings

LOGGER = logging.getLogger('relay.mcp')
REQUEST_MODELS = {
    'get_my_context': Empty,
    'update_my_context': ContextUpdate,
    'query_module': QueryModule,
}
DESCRIPTIONS = {
    'get_my_context': 'Read the latest authorized bootstrap context for the task bound to this process token. No task identity argument.',
    'update_my_context': 'Update this task context using context.version as expected_version. Omitted and null fields are ignored by the backend; an empty string clears a field. At least one non-null update is required by the backend. Never blindly retry a write.',
    'query_module': 'Query a target task published public contract. task_id is the query target, not the caller identity. The backend records the question; mode published_contract does not mean an AI answered it.',
}


def tool_result(payload: dict[str, Any], *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type='text', text=json.dumps(payload, ensure_ascii=False, allow_nan=False))],
        structuredContent=payload,
        isError=is_error,
    )


def create_server(client: RelayHTTPClient) -> Server:
    app = Server('relay-task-bridge', version='0.1.0')

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=name, description=DESCRIPTIONS[name], inputSchema=model.model_json_schema())
            for name, model in REQUEST_MODELS.items()
        ]

    # Pydantic is the shared validator. Disable SDK JSON Schema error messages,
    # which can include rejected literal values and therefore credentials.
    @app.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        model = REQUEST_MODELS.get(name)
        if model is None:
            return tool_result({'error': {'code': 'unknown_tool', 'message': 'This adapter exposes only the three MCP-01 task tools.'}}, is_error=True)
        try:
            request = model.model_validate(arguments)
        except ValidationError:
            # Do not echo arguments, field names from extra inputs, or raw errors.
            return tool_result({'error': {'code': 'invalid_input', 'message': 'Input does not match the shared request schema. Check tools/list for allowed fields and constraints.'}}, is_error=True)
        try:
            # Preserve omitted vs explicit null vs empty string. No business checks here.
            payload = await client.call(name, request.model_dump(mode='json', exclude_unset=True))
            return tool_result(payload)
        except BackendError as exc:
            LOGGER.warning('Backend operation failed for %s', name)
            return tool_result({'error': exc.error}, is_error=True)
        except Exception:
            # Never format raw HTTP exceptions, headers, request bodies or traceback.
            LOGGER.error('Unexpected adapter failure for %s', name)
            return tool_result({'error': {'code': 'internal_error', 'message': 'Adapter could not complete the operation. Check its local configuration and backend health; do not blindly retry writes.'}}, is_error=True)

    return app


def configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s', force=True)
    # Libraries must not emit request URLs, bodies, headers, or protocol payloads.
    for name in ('httpx', 'httpcore', 'mcp'):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.disabled = True


async def serve(settings: Settings) -> None:
    async with RelayHTTPClient(settings) as client:
        app = create_server(client)
        async with stdio_server() as (reader, writer):
            await app.run(reader, writer, app.create_initialization_options())


def main() -> int:
    configure_logging()
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        LOGGER.error('%s', exc)
        return 2
    try:
        anyio.run(serve, settings)
    except KeyboardInterrupt:
        return 0
    except Exception:
        LOGGER.error('MCP stdio process stopped unexpectedly; check local configuration and client connection.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
