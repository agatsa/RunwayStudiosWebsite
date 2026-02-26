import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl

  // Inside a Cloud Run container, req.nextUrl.origin resolves to the internal
  // address (0.0.0.0:3000). Use x-forwarded-host to get the real public URL.
  const fwdHost = req.headers.get('x-forwarded-host')
  const fwdProto = req.headers.get('x-forwarded-proto') ?? 'https'
  const origin = fwdHost ? `${fwdProto}://${fwdHost}` : req.nextUrl.origin
  const code = searchParams.get('code')
  const state = searchParams.get('state')
  const error = searchParams.get('error')

  // User denied access
  if (error) {
    return NextResponse.redirect(
      `${origin}/settings?google_error=${encodeURIComponent(error)}`,
    )
  }

  if (!code || !state) {
    return NextResponse.redirect(`${origin}/settings?google_error=missing_params`)
  }

  // Decode workspace_id from state
  let workspaceId: string
  try {
    workspaceId = Buffer.from(state, 'base64url').toString('utf-8')
  } catch {
    return NextResponse.redirect(`${origin}/settings?google_error=invalid_state`)
  }

  const clientId = process.env.GOOGLE_CLIENT_ID
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET
  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI

  if (!clientId || !clientSecret || !redirectUri) {
    return NextResponse.redirect(
      `${origin}/settings?ws=${workspaceId}&google_error=server_not_configured`,
    )
  }

  // Exchange authorization code for tokens
  let tokens: { access_token: string; refresh_token?: string }
  try {
    const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: redirectUri,
        grant_type: 'authorization_code',
      }),
    })
    if (!tokenRes.ok) {
      const msg = await tokenRes.text()
      console.error('[google/oauth/callback] Token exchange failed:', msg)
      return NextResponse.redirect(
        `${origin}/settings?ws=${workspaceId}&google_error=token_exchange_failed`,
      )
    }
    tokens = await tokenRes.json()
  } catch (e) {
    console.error('[google/oauth/callback] Token exchange error:', e)
    return NextResponse.redirect(
      `${origin}/settings?ws=${workspaceId}&google_error=token_exchange_error`,
    )
  }

  // Google only returns refresh_token on first authorisation with prompt=consent
  if (!tokens.refresh_token) {
    return NextResponse.redirect(
      `${origin}/settings?ws=${workspaceId}&google_error=no_refresh_token`,
    )
  }

  // Ask FastAPI to auto-discover customer_id + youtube_channel_id and save.
  // Pass client_id/secret from dashboard env so agent-swarm doesn't need them as its own env vars.
  try {
    const saveRes = await fetchFromFastAPI('/google/oauth/save', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
        client_id: clientId,
        client_secret: clientSecret,
      }),
    })
    if (!saveRes.ok) {
      const msg = await saveRes.text()
      console.error('[google/oauth/callback] FastAPI save failed:', saveRes.status, msg)
      // 422 = no Google Ads account found; 500 = server misconfiguration
      const errCode = saveRes.status === 422 ? 'no_ads_account' : 'save_failed'
      return NextResponse.redirect(
        `${origin}/settings?ws=${workspaceId}&google_error=${errCode}`,
      )
    }
  } catch (e) {
    console.error('[google/oauth/callback] FastAPI unreachable:', e)
    return NextResponse.redirect(
      `${origin}/settings?ws=${workspaceId}&google_error=fastapi_unreachable`,
    )
  }

  return NextResponse.redirect(
    `${origin}/settings?ws=${workspaceId}&google_connected=1`,
  )
}
