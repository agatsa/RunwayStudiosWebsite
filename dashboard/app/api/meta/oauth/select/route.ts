import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(request: NextRequest) {
  const body = await request.json()
  const r = await fetchFromFastAPI('/meta/oauth/select-account', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.text().then(t => t ? JSON.parse(t) : {})
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
