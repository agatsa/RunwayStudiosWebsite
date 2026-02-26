import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const days = req.nextUrl.searchParams.get('days') ?? '365'
  const r = await fetchFromFastAPI(`/kpi/summary?workspace_id=${ws}&days=${days}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
