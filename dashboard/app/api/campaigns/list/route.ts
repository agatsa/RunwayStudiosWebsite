import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const days = req.nextUrl.searchParams.get('days') ?? '365'

  const [metaRes, uploadedRes] = await Promise.allSettled([
    fetchFromFastAPI(`/meta/campaigns?workspace_id=${ws}`),
    fetchFromFastAPI(`/upload/campaigns?workspace_id=${ws}&days=${days}`),
  ])

  const ok = (r: PromiseSettledResult<Response>) =>
    r.status === 'fulfilled' && r.value.ok ? r.value.json() : Promise.resolve(null)

  const [meta, uploaded] = await Promise.all([ok(metaRes), ok(uploadedRes)])

  return NextResponse.json({
    campaigns: meta?.campaigns ?? [],
    uploaded_campaigns: uploaded?.campaigns ?? [],
  })
}
