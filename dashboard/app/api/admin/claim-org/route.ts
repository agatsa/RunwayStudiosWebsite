import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  const { userId } = auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const adminToken = process.env.ADMIN_TOKEN ?? ''
  const body = await req.json()
  const r = await fetchFromFastAPI('/admin/claim-org', {
    method: 'POST',
    headers: { 'X-Admin-Token': adminToken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, clerk_user_id: userId }),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
