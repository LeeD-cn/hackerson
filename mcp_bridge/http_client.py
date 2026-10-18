"""HTTP transport only; authorization and business rules belong to the backend."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx


class ConfigurationError(ValueError):
    """A safe-to-display configuration error without environment values."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    task_token: str = field(repr=False)
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        origin = env.get('RELAY_API_URL', '').strip()
        if not origin:
            raise ConfigurationError('RELAY_API_URL is required (HTTP(S) origin only).')
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme in {'http', 'https'}
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {'', '/'}
                and not parsed.query
                and not parsed.fragment
                and '?' not in origin
                and '#' not in origin
                and not any(character.isspace() for character in origin)
                and '\\' not in origin
            )
            parsed.port  # Validate the port without putting its value in an error.
            httpx.URL(origin)
        except (ValueError, httpx.InvalidURL):
            valid = False
        if not valid:
            raise ConfigurationError(
                'RELAY_API_URL must be an HTTP(S) origin without credentials, path, query or fragment.'
            )
        token = env.get('RELAY_TASK_TOKEN', '')
        if not token or any(ord(character) < 33 or ord(character) > 126 for character in token):
            raise ConfigurationError('RELAY_TASK_TOKEN is required and must be a nonempty ASCII token without whitespace.')
        try:
            timeout = float(env.get('RELAY_HTTP_TIMEOUT_SECONDS', '10'))
        except ValueError:
            timeout = float('nan')
        if not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ConfigurationError('RELAY_HTTP_TIMEOUT_SECONDS must be greater than 0 and at most 300.')
        return cls(origin.rstrip('/'), token, timeout)


def redact(value: Any, token: str) -> Any:
    """Never return the configured credential, including inside backend error details."""
    if isinstance(value, str):
        return value.replace(token, '[REDACTED]') if token else value
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    return value


class BackendError(Exception):
    """Internal transport exception, not a new shared response contract."""

    def __init__(self, error: dict[str, Any]):
        self.error = error
        super().__init__(error['message'])


class RelayHTTPClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            headers={'Authorization': f'Bearer {settings.task_token}', 'Accept': 'application/json'},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def __aenter__(self) -> RelayHTTPClient:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.__aexit__(*args)

    async def call(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Deliberately no retries, redirects, role selection or database access.
        try:
            response = await self._client.post(
                f'{self.settings.api_url}/api/tools/{action}', json=arguments
            )
        except httpx.TimeoutException:
            raise BackendError({
                'code': 'backend_timeout',
                'message': 'Backend request timed out. A write may have succeeded; read the current context before deciding what to do. Do not blindly retry.',
            }) from None
        except httpx.RequestError:
            raise BackendError({
                'code': 'backend_unreachable',
                'message': 'Cannot reach the backend. Check RELAY_API_URL and backend availability. A write result is unknown; read the current context before resubmitting.',
            }) from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200:
            error = payload.get('error') if isinstance(payload, dict) else None
            if isinstance(error, dict) and isinstance(error.get('code'), str) and isinstance(error.get('message'), str):
                safe_error = {'code': error['code'], 'message': error['message']}
                if 'details' in error:
                    safe_error['details'] = error['details']
            else:
                code, message = {
                    401: ('unauthorized', 'Task token is missing, invalid or revoked. Check RELAY_TASK_TOKEN.'),
                    403: ('forbidden', 'This task is not authorized for the operation. Do not switch to an administrator identity.'),
                    404: ('not_found', 'The target is unavailable or the backend action is not implemented.'),
                    409: ('version_conflict', 'Backend rejected a conflicting operation. Read the latest context and compare before resubmitting.'),
                    422: ('invalid_input', 'Backend rejected the input. Check the shared request contract.'),
                }.get(response.status_code, ('backend_http_error', 'Backend returned an unsuccessful HTTP response. Check the backend service.'))
                safe_error = {'code': code, 'message': message}
            raise BackendError(redact(safe_error, self.settings.task_token))
        if not isinstance(payload, dict):
            raise BackendError({
                'code': 'invalid_backend_response',
                'message': 'Backend must return a JSON object for a successful tool call.',
            })
        return redact(payload, self.settings.task_token)
