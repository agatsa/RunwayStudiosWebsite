import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('workspace_id') ?? ''
  try {
    const r = await fetchFromFastAPI(`/chat/history?workspace_id=${ws}`)
    const data = await r.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ messages: [] })
  }
}
