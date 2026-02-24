import { NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET() {
  const r = await fetchFromFastAPI('/workspace/list')
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
