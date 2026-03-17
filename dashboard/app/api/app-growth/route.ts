import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

// GET /api/app-growth?action=status&workspace_id=...
// POST /api/app-growth  { action: 'connect', ...fields }
export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const action = searchParams.get('action') ?? 'status'
  const ws = searchParams.get('workspace_id') ?? ''
  const days = searchParams.get('days') ?? '30'

  let path = ''
  if (action === 'funnel') {
    path = `/app-growth/attribution/funnel?workspace_id=${ws}&days=${days}`
  } else if (action === 'growth-plan') {
    path = `/app-growth/growth-plan/latest?workspace_id=${ws}`
  } else {
    path = `/app-growth/status?workspace_id=${ws}`
  }

  const r = await fetchFromFastAPI(path)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const action = body.action ?? 'connect'

  let path = ''
  if (action === 'growth-plan') {
    path = '/app-growth/growth-plan'
  } else {
    path = '/app-growth/connect'
  }

  const r = await fetchFromFastAPI(path, { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
