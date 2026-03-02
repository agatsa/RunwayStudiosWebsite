import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl
  const ws = searchParams.get('ws') ?? ''
  if (!ws) {
    return NextResponse.redirect(new URL('/settings?meta_error=missing_params', origin))
  }

  try {
    const r = await fetchFromFastAPI(`/meta/oauth/start?workspace_id=${ws}`)
    if (!r.ok) {
      const text = await r.text().catch(() => 'server_error')
      return NextResponse.redirect(
        new URL(`/settings?ws=${ws}&meta_error=${encodeURIComponent(text)}`, origin)
      )
    }
    const data = await r.json()
    return NextResponse.redirect(data.oauth_url)
  } catch {
    return NextResponse.redirect(
      new URL(`/settings?ws=${ws}&meta_error=server_error`, origin)
    )
  }
}
