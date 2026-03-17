import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const kwId = req.nextUrl.searchParams.get('keyword_id') ?? ''
  const path = kwId
    ? `/app-growth/aso/rank-history?workspace_id=${ws}&keyword_id=${kwId}`
    : `/app-growth/aso/rank-trend?workspace_id=${ws}`
  const r = await fetchFromFastAPI(path)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
