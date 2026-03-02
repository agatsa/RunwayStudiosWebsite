import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function POST(req: NextRequest) {
  const { userId } = auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const body = await req.json()
    const r = await fetchFromFastAPI('/workspace/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, clerk_user_id: userId }),
    })
    // 409 means workspace already exists — return it gracefully
    if (r.status === 409) {
      return NextResponse.json({ workspace_exists: true }, { status: 200 })
    }
    const text = await r.text()
    const data = text ? JSON.parse(text) : {}
    return NextResponse.json(data, { status: r.ok ? 200 : r.status })
  } catch (e) {
    return NextResponse.json({ detail: 'Service unavailable, please try again.' }, { status: 503 })
  }
}
