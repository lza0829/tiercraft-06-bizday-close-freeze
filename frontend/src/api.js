async function readError(res) {
  const text = await res.text()
  try {
    const obj = JSON.parse(text)
    const detail = obj.detail
    if (detail == null) return text
    if (typeof detail === 'string') return detail
    if (typeof detail === 'object') return detail.原因 || JSON.stringify(detail)
    return String(detail)
  } catch {
    return text
  }
}

export async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}
