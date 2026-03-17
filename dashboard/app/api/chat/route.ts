import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'https://agent-swarm-771420308292.asia-south1.run.app'
const API_KEY  = process.env.BACKEND_API_KEY ?? ''

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const r = await fetch(`${BACKEND}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify(body),
    })
    const text = await r.text()
    try {
      const data = JSON.parse(text)
      return NextResponse.json(data, { status: r.status })
    } catch {
      console.error('Chat backend non-JSON response:', r.status, text.slice(0, 500))
      return NextResponse.json({ detail: `AI service error (${r.status}). Please try again.` }, { status: 500 })
    }
  } catch (e) {
    console.error('Chat proxy error:', e)
    return NextResponse.json({ detail: 'Failed to reach AI service. Please try again.' }, { status: 500 })
  }
}
