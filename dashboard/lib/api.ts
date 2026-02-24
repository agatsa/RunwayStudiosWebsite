/**
 * Server-side helper — calls FastAPI directly (bypasses the Next.js API proxy).
 * Only call this from Server Components or API route handlers.
 */
export async function fetchFromFastAPI(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const base = process.env.FASTAPI_BASE_URL ?? 'http://localhost:8080'
  const token = process.env.CRON_TOKEN ?? ''
  return fetch(`${base}${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Cron-Token': token,
      ...(options.headers ?? {}),
    },
  })
}

/**
 * Client-side helper — calls the Next.js /api proxy routes.
 * Use this in Client Components.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${path} failed (${res.status}): ${text}`)
  }
  return res.json() as Promise<T>
}
