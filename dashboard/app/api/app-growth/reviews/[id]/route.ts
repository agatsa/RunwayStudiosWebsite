import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

// PATCH /api/app-growth/reviews/[id] — post live reply to store
export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()
  const r = await fetchFromFastAPI(`/app-growth/reviews/${params.id}/reply-live`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
