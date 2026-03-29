import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'
import { auth } from '@clerk/nextjs/server'

export async function DELETE(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const { userId } = auth()
    const workspaceId = req.nextUrl.searchParams.get('workspace_id') || ''
    const r = await fetchFromFastAPI(
      `/team/member/${params.id}?workspace_id=${workspaceId}`,
      { method: 'DELETE', headers: { 'X-Clerk-User-Id': userId ?? '' } },
    )
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}

export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const { userId } = auth()
    const body = await req.json()
    const r = await fetchFromFastAPI(`/team/member/${params.id}/role`, {
      method: 'PATCH',
      body: JSON.stringify(body),
      headers: { 'X-Clerk-User-Id': userId ?? '' },
    })
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
