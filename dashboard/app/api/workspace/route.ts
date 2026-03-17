import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const workspaceId = req.nextUrl.searchParams.get('workspace_id') ?? ''
  if (!workspaceId) return NextResponse.json({ error: 'workspace_id required' }, { status: 400 })
  const r = await fetchFromFastAPI(`/workspace/get?workspace_id=${workspaceId}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
