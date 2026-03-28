import { NextRequest, NextResponse } from 'next/server'

// One-click login for Razorpay KYC team — no OTP, no password prompt.
// Visiting /api/demo-access?key=rp2026 generates a fresh Clerk sign-in token
// for the demo account and redirects straight into the dashboard.

const SECRET = 'rp2026'
const DEMO_USER_ID = 'user_3BZMDUomatvsLFk9uLuroINLtq5' // demo@runwaystudios.co

export async function GET(req: NextRequest) {
  const key = req.nextUrl.searchParams.get('key')
  if (key !== SECRET) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const res = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.CLERK_SECRET_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ user_id: DEMO_USER_ID, expires_in_seconds: 300 }),
  })

  const data = await res.json()
  if (!res.ok || !data.token) {
    return NextResponse.json({ error: 'Failed to generate token', detail: data }, { status: 500 })
  }

  // Clerk's <SignIn> component picks up __clerk_ticket from the URL hash
  // and completes sign-in with zero user interaction.
  const redirect = `https://app.runwaystudios.co/sign-in#__clerk_ticket=${data.token}`
  return NextResponse.redirect(redirect)
}
