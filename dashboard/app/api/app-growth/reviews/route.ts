import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const ws = searchParams.get('workspace_id') ?? ''
  const store = searchParams.get('store') ?? 'all'
  const sentiment = searchParams.get('sentiment') ?? 'all'
  const rating = searchParams.get('rating') ?? '0'
  const limit = searchParams.get('limit') ?? '50'
  const path = `/app-growth/reviews?workspace_id=${ws}&store=${store}&sentiment=${sentiment}&rating=${rating}&limit=${limit}`
  const r = await fetchFromFastAPI(path)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/app-growth/reviews/add', { method: 'POST', body: JSON.stringify(body) })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
