import { NextRequest, NextResponse } from 'next/server'
import { fetchFromFastAPI } from '@/lib/api'

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl
  const ws = searchParams.get('ws') ?? ''

  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'https://app.runwaystudios.co'

  if (!ws) {
    return NextResponse.redirect(`${appUrl}/settings?meta_error=missing_params`)
  }

  try {
    const r = await fetchFromFastAPI(`/meta/oauth/start?workspace_id=${ws}`)
    if (!r.ok) {
      const text = await r.text().catch(() => 'server_error')
      return NextResponse.redirect(
        `${appUrl}/settings?ws=${ws}&meta_error=${encodeURIComponent(text)}`
      )
    }
    const data = await r.json()
    return NextResponse.redirect(data.oauth_url)
  } catch {
    return NextResponse.redirect(`${appUrl}/settings?ws=${ws}&meta_error=server_error`)
  }
}
