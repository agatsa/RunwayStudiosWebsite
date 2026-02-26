import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('ws') ?? ''
  const r = await fetchFromFastAPI(`/google/accessible-customers?workspace_id=${ws}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.status })
}
