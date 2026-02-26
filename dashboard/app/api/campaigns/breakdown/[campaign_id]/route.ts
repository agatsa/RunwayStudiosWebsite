import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(
  req: NextRequest,
  { params }: { params: { campaign_id: string } }
) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(
    `/meta/campaign-breakdown/${params.campaign_id}?workspace_id=${ws}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
