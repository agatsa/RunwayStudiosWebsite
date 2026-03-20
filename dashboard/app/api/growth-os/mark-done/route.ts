import { NextRequest, NextResponse } from 'next/server'

const API = process.env.NEXT_PUBLIC_AGENT_API_URL ?? 'https://agent-swarm-771420308292.asia-south1.run.app'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const res = await fetch(`${API}/growth-os/action/done`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
