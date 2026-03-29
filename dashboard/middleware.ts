import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'

const isPublicRoute = createRouteMatcher([
  '/sign-in(.*)',
  '/sign-up(.*)',
  '/api/webhooks(.*)',
  // OAuth callbacks — Shopify/Meta/Google redirect here without a Clerk session
  '/api/shopify/callback(.*)',
  '/api/meta/oauth/callback(.*)',
  '/api/google/oauth/callback(.*)',
  // Public email unsubscribe (token-based, no session needed)
  '/unsubscribe(.*)',
  // Team invite landing page (user may not be logged in yet)
  '/invite(.*)',
  // Internal debug route for email domain diagnosis
  '/api/email/domain/debug(.*)',
  // Onboarding funnel — publicly accessible, auth handled inside page
  // /onboard/sso-callback is where Clerk lands after Google OAuth from the embedded <SignIn>
  '/onboard(.*)',
  '/api/onboard(.*)',
  // One-click demo login for Razorpay KYC team (generates Clerk sign-in token, no OTP)
  '/api/demo-access(.*)',
])

export default clerkMiddleware((auth, request) => {
  if (!isPublicRoute(request)) {
    auth().protect()
  }
})

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}
