import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function DELETE(req: NextRequest, { params }: { params: { id: string } }) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/products/${params.id}?workspace_id=${ws}`, {
    method: 'DELETE',
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  // POST /api/products/[id] with ?action=resync
  const action = req.nextUrl.searchParams.get('action')
  if (action === 'resync') {
    const body = await req.json()
    const r = await fetchFromFastAPI(`/products/${params.id}/resync`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  }
  return NextResponse.json({ detail: 'Unknown action' }, { status: 400 })
}
