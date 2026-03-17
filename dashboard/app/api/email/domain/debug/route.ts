import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const wsId = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/email/domain/debug?workspace_id=${wsId}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
