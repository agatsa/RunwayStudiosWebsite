import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(request: NextRequest) {
  const sessionId = request.nextUrl.searchParams.get('session_id') ?? ''
  if (!sessionId) return NextResponse.json({ error: 'Missing session_id' }, { status: 400 })

  const r = await fetchFromFastAPI(`/meta/oauth/session?session_id=${sessionId}`)
  const data = await r.text().then(t => t ? JSON.parse(t) : {})
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
