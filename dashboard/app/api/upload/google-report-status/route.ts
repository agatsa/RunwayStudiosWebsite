import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  try {
    const r = await fetchFromFastAPI(`/upload/google-report-status?workspace_id=${ws}`)
    const text = await r.text()
    try {
      return NextResponse.json(JSON.parse(text), { status: r.ok ? 200 : r.status })
    } catch {
      return NextResponse.json({ detail: text.slice(0, 200) }, { status: r.status || 500 })
    }
  } catch (err) {
    return NextResponse.json({ detail: String(err) }, { status: 500 })
  }
}
