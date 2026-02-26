import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const r = await fetchFromFastAPI('/upload/auction-insights', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const text = await r.text()
    try {
      return NextResponse.json(JSON.parse(text), { status: r.ok ? 200 : r.status })
    } catch {
      return NextResponse.json(
        { detail: `Backend error (HTTP ${r.status}): ${text.slice(0, 300) || '(empty response)'}` },
        { status: r.status || 500 },
      )
    }
  } catch (err) {
    return NextResponse.json(
      { detail: `Upload failed: ${err instanceof Error ? err.message : String(err)}` },
      { status: 500 },
    )
  }
}
