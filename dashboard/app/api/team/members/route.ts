import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'
import { auth } from '@clerk/nextjs/server'

export async function GET(req: NextRequest) {
  try {
    const { userId } = auth()
    const workspaceId = req.nextUrl.searchParams.get('workspace_id') || ''
    const r = await fetchFromFastAPI(`/team/members?workspace_id=${workspaceId}`, {
      headers: { 'X-Clerk-User-Id': userId ?? '' },
    })
    const data = await r.json()
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch {
    return NextResponse.json({ detail: 'Service unavailable' }, { status: 503 })
  }
}
