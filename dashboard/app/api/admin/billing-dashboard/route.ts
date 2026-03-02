import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const adminToken = process.env.ADMIN_TOKEN ?? ''
  const r = await fetchFromFastAPI('/admin/billing-dashboard', {
    headers: { 'X-Admin-Token': adminToken },
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
