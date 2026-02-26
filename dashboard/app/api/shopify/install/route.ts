import { NextRequest, NextResponse } from 'next/server'

const SHOPIFY_API_KEY    = process.env.SHOPIFY_API_KEY    ?? ''
const SHOPIFY_API_SECRET = process.env.SHOPIFY_API_SECRET ?? ''
const SHOPIFY_SCOPES     = process.env.SHOPIFY_SCOPES     ?? 'read_products,read_inventory'
const REDIRECT_URI       = process.env.SHOPIFY_OAUTH_REDIRECT_URI
  ?? `${process.env.NEXT_PUBLIC_APP_URL ?? 'https://dashboard-771420308292.asia-south1.run.app'}/api/shopify/callback`

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const shop = (searchParams.get('shop') ?? '').trim().toLowerCase()
  const ws   = searchParams.get('ws') ?? ''

  if (!shop || !ws) {
    return NextResponse.json({ error: 'shop and ws params required' }, { status: 400 })
  }
  if (!SHOPIFY_API_KEY || !SHOPIFY_API_SECRET) {
    return NextResponse.json({ error: 'Shopify app not configured on server' }, { status: 503 })
  }

  // Ensure domain is in myshopify.com form or use as-is (custom domains work too)
  const shopHost = shop.replace(/^https?:\/\//, '').replace(/\/$/, '')

  // Encode workspace_id in state (base64url)
  const state = Buffer.from(JSON.stringify({ ws, nonce: Date.now() })).toString('base64url')

  const params = new URLSearchParams({
    client_id:          SHOPIFY_API_KEY,
    scope:              SHOPIFY_SCOPES,
    redirect_uri:       REDIRECT_URI,
    state,
    'grant_options[]':  'per-user',
  })

  const oauthUrl = `https://${shopHost}/admin/oauth/authorize?${params.toString()}`
  return NextResponse.redirect(oauthUrl)
}
