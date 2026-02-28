import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const ws     = searchParams.get('workspace_id') ?? ''
  const source = searchParams.get('source') ?? 'all'
  const limit  = searchParams.get('limit') ?? '50'
  const offset = searchParams.get('offset') ?? '0'
  const days   = searchParams.get('days') ?? '0'
  const r = await fetchFromFastAPI(
    `/comments/feed?workspace_id=${ws}&source=${source}&limit=${limit}&offset=${offset}&days=${days}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
