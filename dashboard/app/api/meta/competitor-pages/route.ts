import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const workspace_id = searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(
    `/meta/competitor-pages?workspace_id=${encodeURIComponent(workspace_id)}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/meta/competitor-pages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function DELETE(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/meta/competitor-pages', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
