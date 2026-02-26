import { fetchFromFastAPI } from '@/lib/api'
import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/upload/amazon-ads', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.status })
}
