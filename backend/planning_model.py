"""Configurable Chat Completions adapter; never exposes provider bodies or secrets."""
import json
import math
import os
import time
from urllib.parse import urlsplit

import httpx

from .store import fail


class PlanningModel:
    def __init__(self, config=None, transport=None):
        self.config = os.environ if config is None else config
        self.transport = transport

    def generate(self, messages):
        config = self.config
        url = config.get('RELAY_AI_BASE_URL', '').strip().rstrip('/')
        model = config.get('RELAY_AI_MODEL', '').strip()
        key = config.get('RELAY_AI_API_KEY', '').strip()
        key_file = config.get('RELAY_AI_API_KEY_FILE', '').strip()
        if not key and key_file:
            try:
                from pathlib import Path
                key = Path(key_file).read_text(encoding='utf-8').strip()
            except (OSError, UnicodeError):
                fail(503, 'ai_not_configured', '无法读取模型密钥文件，请检查后端配置')
        if not all((url, model, key)):
            fail(503, 'ai_not_configured', '请配置 RELAY_AI_BASE_URL、RELAY_AI_MODEL 和模型密钥')
        try:
            parts = urlsplit(url)
            parts.port  # Validate malformed port values without making any request.
            timeout = float(config.get('RELAY_AI_TIMEOUT_SECONDS', '60'))
            valid = (parts.scheme in ('http', 'https') and parts.hostname and not parts.username
                     and not parts.password and not parts.query and not parts.fragment
                     and math.isfinite(timeout) and 1 <= timeout <= 180)
        except ValueError:
            valid = False
        if not valid:
            fail(503, 'ai_not_configured', '模型地址或超时配置无效')
        # Accept both a host-only URL (as supplied by Paratera) and an API root ending in /v1.
        if not parts.path.strip('/'):
            url += '/v1'
        payload = {'model': model, 'messages': messages, 'stream': False}
        # Some compatible providers do not implement JSON mode; server validation is mandatory either way.
        if config.get('RELAY_AI_JSON_MODE', '1') == '1':
            payload['response_format'] = {'type': 'json_object'}
        deadline = time.monotonic() + timeout
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
                              transport=self.transport, trust_env=False, follow_redirects=False) as client:
                with client.stream('POST', url + '/chat/completions', json=payload,
                                   headers={'Authorization': f'Bearer {key}'}) as response:
                    if response.status_code == 429:
                        fail(503, 'ai_rate_limited', '模型服务限流，请稍后重试')
                    if response.status_code in (401, 403):
                        fail(502, 'ai_auth_failed', '模型服务鉴权失败，请检查后端模型配置')
                    if not 200 <= response.status_code < 300:
                        fail(502, 'ai_upstream_error', '模型服务请求失败，请检查后端模型配置')
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if time.monotonic() > deadline:
                            fail(504, 'ai_timeout', '模型响应超时，请稍后重试')
                        if len(content) > 1_000_000:
                            fail(502, 'ai_invalid_response', '模型响应过大')
            result = json.loads(content)
            choice = result['choices'][0]
            if choice.get('finish_reason') != 'stop':
                fail(502, 'ai_invalid_response', '模型未完整生成规划，请缩小需求后重试')
            text = choice['message']['content']
            if not isinstance(text, str):
                raise ValueError('Expected text')
            return text
        except httpx.TimeoutException:
            fail(504, 'ai_timeout', '模型响应超时，请稍后重试')
        except httpx.HTTPError:
            fail(502, 'ai_unavailable', '无法连接模型服务，请检查后端网络和配置')
        except (ValueError, KeyError, IndexError, TypeError):
            fail(502, 'ai_invalid_response', '模型返回格式无效，请重试')
