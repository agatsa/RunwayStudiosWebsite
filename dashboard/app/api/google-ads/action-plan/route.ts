import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  const r = await fetchFromFastAPI(`/upload/google-action-plan?workspace_id=${ws}`)
  const text = await r.text()
  try {
    const data = JSON.parse(text)
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ action_plan: [] }, { status: 200 })
  }
}
