import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const list_id = req.nextUrl.searchParams.get('list_id') ?? ''
  const page = req.nextUrl.searchParams.get('page') ?? '1'
  const limit = req.nextUrl.searchParams.get('limit') ?? '50'
  const r = await fetchFromFastAPI(`/email/contacts?workspace_id=${ws}&list_id=${list_id}&page=${page}&limit=${limit}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
