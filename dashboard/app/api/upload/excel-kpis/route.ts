import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const r = await fetchFromFastAPI('/upload/excel-kpis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    // Use text() first so we never throw on empty/non-JSON responses from FastAPI
    const text = await r.text()
    try {
      const data = JSON.parse(text)
      return NextResponse.json(data, { status: r.ok ? 200 : r.status })
    } catch {
      // FastAPI returned non-JSON (empty body, HTML error, etc.)
      return NextResponse.json(
        { detail: `Backend error (HTTP ${r.status}): ${text.slice(0, 300) || '(empty response)'}` },
        { status: r.status || 500 },
      )
    }
  } catch (err) {
    // Network error, timeout, or req.json() failure
    return NextResponse.json(
      { detail: `Upload failed: ${err instanceof Error ? err.message : String(err)}` },
      { status: 500 },
    )
  }
}
