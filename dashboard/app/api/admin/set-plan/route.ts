import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  const adminToken = process.env.ADMIN_TOKEN ?? ''
  const body = await req.json()
  const r = await fetchFromFastAPI('/admin/set-plan', {
    method: 'POST',
    headers: { 'X-Admin-Token': adminToken },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
