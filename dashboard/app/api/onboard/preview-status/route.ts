import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url)
    const jobId = searchParams.get('job_id') || ''
    const workspaceId = searchParams.get('workspace_id') || ''
    if (!jobId) return NextResponse.json({ detail: 'job_id required' }, { status: 400 })
    const r = await fetchFromFastAPI(
      `/onboard/preview-status/${jobId}?workspace_id=${workspaceId}`,
      { cache: 'no-store' }
    )
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
