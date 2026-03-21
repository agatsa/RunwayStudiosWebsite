import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const ws  = searchParams.get('workspace_id') || ''
  const job = searchParams.get('job_id') || ''
  const url = job
    ? `/brand-intel/status?workspace_id=${ws}&job_id=${job}`
    : `/brand-intel/status?workspace_id=${ws}`
  const r = await fetchFromFastAPI(url, { cache: 'no-store' })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
