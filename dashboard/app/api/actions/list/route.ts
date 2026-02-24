import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws     = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const status = req.nextUrl.searchParams.get('status') ?? 'pending'
  const limit  = req.nextUrl.searchParams.get('limit') ?? '50'
  const r = await fetchFromFastAPI(
    `/actions/list?workspace_id=${ws}&status=${status}&limit=${limit}`,
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
