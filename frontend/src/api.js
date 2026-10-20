// 公共 API 请求：保留服务器的字段校验信息。
export async function api(path, options = {}) {
  const response = await fetch(path, options)
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  return body
}
export function jsonPost(body, key) {
  return { method: 'POST', headers: { 'Content-Type': 'application/json', ...(key ? {'Idempotency-Key': key} : {}) }, body: JSON.stringify(body) }
}
