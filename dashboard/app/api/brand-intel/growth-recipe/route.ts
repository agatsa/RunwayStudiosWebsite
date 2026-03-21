import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const ws = searchParams.get('workspace_id') || ''
  const r = await fetchFromFastAPI(`/brand-intel/growth-recipe?workspace_id=${ws}`, { cache: 'no-store' })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
