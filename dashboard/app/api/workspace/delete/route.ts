import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function DELETE(req: NextRequest) {
  const { userId } = auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  try {
    const { workspace_id } = await req.json()
    const r = await fetchFromFastAPI(`/workspace/${workspace_id}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', 'X-Workspace-Id': workspace_id },
    })
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
