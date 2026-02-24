import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const { platform, ...rest } = body
  const endpoint = platform === 'google' ? '/google/campaign/budget' : '/meta/campaign/budget'
  const r = await fetchFromFastAPI(endpoint, {
    method: 'POST',
    body: JSON.stringify(rest),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
