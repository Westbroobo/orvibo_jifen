let csrfToken = ''
export function setCsrf(value: string) { csrfToken = value }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(20_000)
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
  try {
    const response = await fetch(`/api${path}`, {
      method, credentials: 'same-origin', signal: requestSignal,
      headers: { 'Content-Type': 'application/json', ...(method === 'GET' ? {} : { 'X-CSRF-Token': csrfToken }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const data = await response.json().catch(e => { if (requestSignal.aborted) throw e; return {} })
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join('；') : data.detail
      throw new ApiError(detail || '请求失败，请稍后重试', response.status)
    }
    return data as T
  } catch (e) {
    if (signal?.aborted) throw e
    if (timeout.aborted) throw new ApiError(method === 'GET' ? '加载超时，请重试。' : '请求超时，操作结果待确认，请刷新查看。', 408)
    throw e
  }
}
