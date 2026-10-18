export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: { field: string; message: string }[] = []) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store' });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(response.status, payload?.error?.code || 'http_error',
        payload?.error?.message || `服务暂不可用（HTTP ${response.status}），请检查后台及代理配置。`, payload?.error?.details || []);
    }
    if (!payload || typeof payload !== 'object') throw new ApiError(502, 'invalid_response', '服务返回格式异常，请检查后台地址。');
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'network_error', options.method === 'GET'
      ? '无法连接后台健康检查接口，请检查后台服务及代理地址。'
      : '连接中断或请求超时。写入结果可能未知，请刷新列表确认后再操作。');
  } finally {
    window.clearTimeout(timeout);
  }
}

export function call<T>(token: string, action: string, body: object = {}): Promise<T> {
  return request<T>(`/api/tools/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
}

export async function checkHealth(): Promise<void> {
  const health = await request<{ status: string; version: string }>('/health', { method: 'GET' });
  if (health.status !== 'ok' || typeof health.version !== 'string') {
    throw new ApiError(502, 'invalid_health', '后台健康检查返回异常，请检查服务及代理地址。');
  }
}

export function asError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, 'unexpected_error', '操作失败，请稍后重试。');
}
