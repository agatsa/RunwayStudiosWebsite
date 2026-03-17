import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/app-growth/aso/keywords?workspace_id=${ws}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const action = body.action ?? 'add'
  if (action === 'analyze') {
    const r = await fetchFromFastAPI('/app-growth/aso/analyze', { method: 'POST', body: JSON.stringify(body) })
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  }
  const r = await fetchFromFastAPI('/app-growth/aso/keywords/add', { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const kwId = searchParams.get('id') ?? ''
  const ws = searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/app-growth/aso/keywords/${kwId}?workspace_id=${ws}`, { method: 'DELETE' })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
