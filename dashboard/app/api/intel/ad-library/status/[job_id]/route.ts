import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(
  req: NextRequest,
  { params }: { params: { job_id: string } }
) {
  const r = await fetchFromFastAPI(`/intel/ad-library/status/${params.job_id}`)
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
