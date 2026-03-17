import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

// GET /api/seo?action=status|keywords|pages&workspace_id=...
export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const action = searchParams.get('action') ?? 'status'
  const ws     = searchParams.get('workspace_id') ?? ''
  const days   = searchParams.get('days') ?? '28'
  const limit  = searchParams.get('limit') ?? '50'
  const site   = searchParams.get('site_url') ?? ''

  let path = ''
  if (action === 'keywords') {
    path = `/seo/keywords?workspace_id=${ws}&days=${days}&limit=${limit}${site ? `&site_url=${encodeURIComponent(site)}` : ''}`
  } else if (action === 'pages') {
    path = `/seo/pages?workspace_id=${ws}&days=${days}&limit=${limit}${site ? `&site_url=${encodeURIComponent(site)}` : ''}`
  } else {
    path = `/seo/status?workspace_id=${ws}`
  }

  const r = await fetchFromFastAPI(path)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

// POST /api/seo — audit-url or set-site
export async function POST(req: NextRequest) {
  const body = await req.json()
  const action = body.action ?? 'audit'
  const path = action === 'set-site' ? '/seo/set-site' : '/seo/audit-url'
  const r = await fetchFromFastAPI(path, { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
