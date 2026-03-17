import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const action = req.nextUrl.searchParams.get('action') ?? 'status'
  const r = await fetchFromFastAPI(`/seo/wordpress/${action}?workspace_id=${ws}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const action = body.action ?? 'connect'
  const r = await fetchFromFastAPI(`/seo/wordpress/${action}`, { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
