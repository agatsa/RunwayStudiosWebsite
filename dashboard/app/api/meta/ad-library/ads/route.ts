import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const workspace_id = searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(
    `/meta/ad-library/ads?workspace_id=${encodeURIComponent(workspace_id)}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
