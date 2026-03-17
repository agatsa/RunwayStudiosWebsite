import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const ws = searchParams.get('workspace_id') ?? ''
  const days = searchParams.get('days') ?? '30'
  const r = await fetchFromFastAPI(`/app-growth/attribution/funnel?workspace_id=${ws}&days=${days}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/app-growth/attribution/webhook', { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
