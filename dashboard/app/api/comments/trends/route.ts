import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const ws     = searchParams.get('workspace_id') ?? ''
  const days   = searchParams.get('days') ?? '30'
  const source = searchParams.get('source') ?? 'all'
  const r = await fetchFromFastAPI(
    `/comments/trends?workspace_id=${ws}&days=${days}&source=${source}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
