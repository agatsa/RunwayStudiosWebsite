import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function PATCH(req: NextRequest) {
  const body = await req.json()
  const r = await fetchFromFastAPI('/workspace/reset-onboarding', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
