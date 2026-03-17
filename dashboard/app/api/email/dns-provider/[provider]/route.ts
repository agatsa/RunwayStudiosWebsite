import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function DELETE(req: NextRequest, { params }: { params: { provider: string } }) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/email/dns-provider/${params.provider}?workspace_id=${ws}`, { method: 'DELETE' })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
