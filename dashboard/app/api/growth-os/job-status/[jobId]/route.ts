import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(
  req: NextRequest,
  { params }: { params: { jobId: string } }
) {
  try {
    const wsId = req.nextUrl.searchParams.get('workspace_id') ?? ''
    const r = await fetchFromFastAPI(
      `/growth-os/job-status/${params.jobId}?workspace_id=${wsId}`
    )
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
