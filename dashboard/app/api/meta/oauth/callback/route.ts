import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl
  const code  = searchParams.get('code')  ?? ''
  const state = searchParams.get('state') ?? '' // workspace_id
  const error = searchParams.get('error')

  // Use the configured public app URL to avoid Cloud Run's internal 0.0.0.0:3000 origin
  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'https://app.runwaystudios.co'

  if (error) {
    const desc = searchParams.get('error_description') ?? error
    return NextResponse.redirect(
      `${appUrl}/settings?ws=${state}&meta_error=${encodeURIComponent(desc)}`
    )
  }

  if (!code || !state) {
    return NextResponse.redirect(`${appUrl}/settings?meta_error=missing_params`)
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
        `${appUrl}/settings?ws=${state}&meta_error=${encodeURIComponent(text)}`
      )
    }

    const data = await r.json()
    if (data.status === 'connected') {
      return NextResponse.redirect(`${appUrl}/settings?ws=${state}&meta_connected=1`)
    } else {
      // Multiple ad accounts — redirect to account picker
      return NextResponse.redirect(`${appUrl}/settings?ws=${state}&meta_session=${data.session_id}`)
    }
  } catch {
    return NextResponse.redirect(
      `${appUrl}/settings?ws=${state}&meta_error=server_error`
    )
  }
}
