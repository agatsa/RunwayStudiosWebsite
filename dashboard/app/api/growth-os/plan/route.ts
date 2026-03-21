import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const workspace_id = searchParams.get('workspace_id') ?? ''
  const plan_id = searchParams.get('plan_id') ?? ''
  const r = await fetchFromFastAPI(
    `/growth-os/plan?workspace_id=${encodeURIComponent(workspace_id)}&plan_id=${encodeURIComponent(plan_id)}`
  )
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
