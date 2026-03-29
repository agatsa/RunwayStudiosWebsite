'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useUser, SignIn } from '@clerk/nextjs'
import { Loader2, CheckCircle, XCircle } from 'lucide-react'

interface InviteInfo {
  invite_id: string
  workspace_id: string
  workspace_name: string
  email: string
  role: string
  expires_at: string
}

export default function InviteClient() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const router = useRouter()
  const { isLoaded, isSignedIn, user } = useUser()

  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState(false)
  const [accepted, setAccepted] = useState(false)

  // Step 1: load invite info
  useEffect(() => {
    if (!token) { setError('No invite token found.'); setLoading(false); return }
    fetch(`/api/invite/info?token=${token}`)
      .then(r => r.json())
      .then(d => {
        if (d.detail) setError(d.detail)
        else setInfo(d)
      })
      .catch(() => setError('Failed to load invite.'))
      .finally(() => setLoading(false))
  }, [token])

  // Step 2: once logged in + info loaded, auto-accept
  useEffect(() => {
    if (!isLoaded || !isSignedIn || !info || accepted || accepting) return
    const userEmail = user.primaryEmailAddress?.emailAddress ?? ''
    if (userEmail.toLowerCase() !== info.email.toLowerCase()) return  // wrong account

    setAccepting(true)
    fetch('/api/invite/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token,
        clerk_user_id: user.id,
        email: userEmail,
        name: user.fullName ?? '',
      }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.ok) {
          setAccepted(true)
          setTimeout(() => router.replace(`/home?ws=${d.workspace_id}`), 1500)
        } else {
          setError(d.detail ?? 'Failed to accept invite.')
        }
      })
      .catch(() => setError('Failed to accept invite.'))
      .finally(() => setAccepting(false))
  }, [isLoaded, isSignedIn, info, user, token, accepted, accepting, router])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 max-w-md w-full text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Invite unavailable</h1>
          <p className="text-gray-500 text-sm">{error}</p>
          <a href="/sign-in" className="mt-6 inline-block text-sm text-blue-600 hover:underline">
            Go to sign in
          </a>
        </div>
      </div>
    )
  }

  if (accepted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 max-w-md w-full text-center">
          <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-gray-900 mb-2">You&apos;re in!</h1>
          <p className="text-gray-500 text-sm">Redirecting to {info?.workspace_name}…</p>
        </div>
      </div>
    )
  }

  // Show invite card + Clerk sign-in if not logged in
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-md w-full space-y-6">
        {/* Invite card */}
        {info && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 text-center">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-gray-900 text-white text-xl font-bold mb-4">
              {info.workspace_name.charAt(0).toUpperCase()}
            </div>
            <h1 className="text-lg font-semibold text-gray-900">
              Join <span className="text-blue-600">{info.workspace_name}</span>
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              You&apos;ve been invited as a <strong>{info.role}</strong>
            </p>
            <p className="text-xs text-gray-400 mt-1">Sent to {info.email}</p>
          </div>
        )}

        {/* Auth */}
        {isLoaded && !isSignedIn && info && (
          <div>
            <p className="text-center text-sm text-gray-500 mb-4">
              Sign in or create an account to accept
            </p>
            <SignIn
              appearance={{ elements: { rootBox: 'w-full', card: 'shadow-sm border border-gray-200 rounded-2xl' } }}
              redirectUrl={`/invite?token=${token}`}
              initialValues={{ emailAddress: info.email }}
            />
          </div>
        )}

        {isLoaded && isSignedIn && !accepted && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 text-center">
            {accepting ? (
              <><Loader2 className="h-6 w-6 animate-spin text-gray-400 mx-auto mb-2" /><p className="text-sm text-gray-500">Joining workspace…</p></>
            ) : (
              <p className="text-sm text-gray-500">
                Logged in as {user.primaryEmailAddress?.emailAddress}.<br />
                {user.primaryEmailAddress?.emailAddress?.toLowerCase() !== info?.email.toLowerCase()
                  ? <span className="text-red-500">This invite was sent to <strong>{info?.email}</strong>. Please sign in with that email.</span>
                  : 'Accepting invite…'}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
