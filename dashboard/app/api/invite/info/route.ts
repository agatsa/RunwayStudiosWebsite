import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  try {
    const token = req.nextUrl.searchParams.get('token') || ''
    const r = await fetchFromFastAPI(`/invite/info?token=${token}`)
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
