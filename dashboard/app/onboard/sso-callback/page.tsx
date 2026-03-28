'use client'

import { AuthenticateWithRedirectCallback } from '@clerk/nextjs'

// Clerk's embedded <SignIn> with OAuth (Google) redirects back to
// [mountPath]/sso-callback. Since we mount <SignIn> on /onboard,
// the callback lands here. This component completes the OAuth handshake
// and then Clerk follows sign_in_force_redirect_url → back to /onboard?url=...
export default function OnboardSSOCallback() {
  return <AuthenticateWithRedirectCallback />
}
