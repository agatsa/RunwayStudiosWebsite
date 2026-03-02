import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl
  const code  = searchParams.get('code')  ?? ''
  const state = searchParams.get('state') ?? '' // workspace_id
  const error = searchParams.get('error')

  if (error) {
    const desc = searchParams.get('error_description') ?? error
    return NextResponse.redirect(
      new URL(`/settings?ws=${state}&meta_error=${encodeURIComponent(desc)}`, origin)
    )
  }

  if (!code || !state) {
    return NextResponse.redirect(new URL('/settings?meta_error=missing_params', origin))
  }

  try {
    const r = await fetchFromFastAPI('/meta/oauth/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: state, code }),
    })

    if (!r.ok) {
      const text = await r.text()
      return NextResponse.redirect(
        new URL(`/settings?ws=${state}&meta_error=${encodeURIComponent(text)}`, origin)
      )
    }

    const data = await r.json()
    if (data.status === 'connected') {
      return NextResponse.redirect(
        new URL(`/settings?ws=${state}&meta_connected=1`, origin)
      )
    } else {
      // Multiple ad accounts — redirect to account picker
      return NextResponse.redirect(
        new URL(`/settings?ws=${state}&meta_session=${data.session_id}`, origin)
      )
    }
  } catch {
    return NextResponse.redirect(
      new URL(`/settings?ws=${state}&meta_error=server_error`, origin)
    )
  }
}
