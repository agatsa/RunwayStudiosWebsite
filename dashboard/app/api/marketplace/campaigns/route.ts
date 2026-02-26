import { fetchFromFastAPI } from '@/lib/api'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(req: NextRequest) {
  const ws   = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const days = req.nextUrl.searchParams.get('days') ?? '365'
  const r = await fetchFromFastAPI(`/marketplace/campaigns?workspace_id=${ws}&days=${days}`)
  const data = await r.json()
  return NextResponse.json(data)
}
