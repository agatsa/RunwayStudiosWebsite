import { NextRequest, NextResponse } from 'next/server'
import crypto from 'crypto'
import { fetchFromFastAPI } from '@/lib/api'

const SHOPIFY_API_KEY    = process.env.SHOPIFY_API_KEY    ?? ''
const SHOPIFY_API_SECRET = process.env.SHOPIFY_API_SECRET ?? ''

function validateHmac(params: URLSearchParams): boolean {
  const received = params.get('hmac') ?? ''
  const sorted = Array.from(params.entries())
    .filter(([k]) => k !== 'hmac')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join('&')
  const expected = crypto
    .createHmac('sha256', SHOPIFY_API_SECRET)
    .update(sorted)
    .digest('hex')
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(received.padEnd(expected.length, ' ')))
}

export async function GET(req: NextRequest) {
  const { searchParams, origin } = new URL(req.url)
  const code  = searchParams.get('code')  ?? ''
  const shop  = searchParams.get('shop')  ?? ''
  const state = searchParams.get('state') ?? ''

  // --- Decode workspace_id from state ---
  let workspaceId = ''
  try {
    const decoded = JSON.parse(Buffer.from(state, 'base64url').toString('utf-8'))
    workspaceId = decoded.ws ?? ''
  } catch {
    return NextResponse.redirect(`${origin}/settings?shopify_error=invalid_state`)
  }

  if (!workspaceId) {
    return NextResponse.redirect(`${origin}/settings?shopify_error=invalid_state`)
  }

  // --- Validate HMAC ---
  if (SHOPIFY_API_SECRET && !validateHmac(searchParams)) {
    return NextResponse.redirect(`${origin}/settings?ws=${workspaceId}&shopify_error=hmac_failed`)
  }

  if (!code || !shop) {
    return NextResponse.redirect(`${origin}/settings?ws=${workspaceId}&shopify_error=missing_params`)
  }

  // --- Exchange code for access token ---
  let accessToken = ''
  let scope = ''
  try {
    const tokenRes = await fetch(`https://${shop}/admin/oauth/access_token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id:     SHOPIFY_API_KEY,
        client_secret: SHOPIFY_API_SECRET,
        code,
      }),
    })
    if (!tokenRes.ok) {
      throw new Error(`Token exchange failed: ${tokenRes.status}`)
    }
    const tokenData = await tokenRes.json()
    accessToken = tokenData.access_token ?? ''
    scope       = tokenData.scope ?? ''
  } catch (e) {
    console.error('Shopify token exchange error:', e)
    return NextResponse.redirect(`${origin}/settings?ws=${workspaceId}&shopify_error=token_exchange_failed`)
  }

  // --- Save to backend (sync products + register webhooks) ---
  try {
    const saveRes = await fetchFromFastAPI('/shopify/save-connection', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        shop_domain:  shop,
        access_token: accessToken,
        scope,
      }),
    })
    if (!saveRes.ok) {
      const err = await saveRes.json().catch(() => ({}))
      throw new Error(err.detail ?? 'Save failed')
    }
  } catch (e) {
    console.error('Shopify save-connection error:', e)
    return NextResponse.redirect(`${origin}/settings?ws=${workspaceId}&shopify_error=save_failed`)
  }

  return NextResponse.redirect(`${origin}/settings?ws=${workspaceId}&shopify_connected=1`)
}
