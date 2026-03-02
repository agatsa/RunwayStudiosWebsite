import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET() {
  const { userId } = auth()
  if (!userId) {
    return NextResponse.json({ workspaces: [], count: 0 })
  }
  const r = await fetchFromFastAPI('/workspace/list', {
    headers: { 'X-Clerk-User-Id': userId },
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
