import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function DELETE(
  req: NextRequest,
  { params }: { params: { platform: string } }
) {
  const body = await req.json()
  const r = await fetchFromFastAPI(`/settings/disconnect/${params.platform}`, {
    method: 'DELETE',
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
