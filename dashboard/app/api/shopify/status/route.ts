import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const workspaceId = searchParams.get('workspace_id') ?? ''
  if (!workspaceId) return NextResponse.json({ connected: false })
  const r = await fetchFromFastAPI(`/shopify/status?workspace_id=${workspaceId}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
