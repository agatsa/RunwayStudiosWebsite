import { NextRequest, NextResponse } from 'next/server'

const SCOPES = [
  'https://www.googleapis.com/auth/adwords',
  'https://www.googleapis.com/auth/yt-analytics.readonly',
  'https://www.googleapis.com/auth/youtube.readonly',
  'https://www.googleapis.com/auth/analytics.readonly',
  'https://www.googleapis.com/auth/webmasters.readonly',
].join(' ')

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get('ws') ?? ''
  if (!ws) {
    return NextResponse.json({ error: 'ws (workspace_id) is required' }, { status: 400 })
  }

  const clientId = process.env.GOOGLE_CLIENT_ID
  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI

  if (!clientId || !redirectUri) {
    return NextResponse.json(
      { error: 'GOOGLE_CLIENT_ID / GOOGLE_OAUTH_REDIRECT_URI not configured on server' },
      { status: 500 },
    )
  }

  const state = Buffer.from(ws).toString('base64url')

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: SCOPES,
    access_type: 'offline',
    prompt: 'consent',  // always returns refresh_token
    state,
  })

  return NextResponse.redirect(
    `https://accounts.google.com/o/oauth2/v2/auth?${params}`,
  )
}
