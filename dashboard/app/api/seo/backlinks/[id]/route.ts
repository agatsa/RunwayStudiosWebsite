import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()
  const r = await fetchFromFastAPI(`/seo/backlinks/${params.id}`, { method: 'PATCH', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function DELETE(req: NextRequest, { params }: { params: { id: string } }) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/seo/backlinks/${params.id}?workspace_id=${ws}`, { method: 'DELETE' })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
