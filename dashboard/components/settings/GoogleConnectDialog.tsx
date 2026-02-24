'use client'

import { useState } from 'react'
import { CheckCircle } from 'lucide-react'

interface Props {
  workspaceId: string
  onConnected: () => void
  onClose: () => void
}

export default function GoogleConnectDialog({ workspaceId, onConnected, onClose }: Props) {
  const [step] = useState<'form' | 'done'>('form')

  const handleOAuth = () => {
    window.location.href = `/api/google/oauth/start?ws=${workspaceId}`
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        {/* Header */}
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 bg-white">
            <svg viewBox="0 0 48 48" className="h-6 w-6">
              <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
              <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
              <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
              <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">Connect Google Ads</h2>
            <p className="text-xs text-gray-500">Link your Google Ads + YouTube + Merchant Center</p>
          </div>
        </div>

        {step === 'form' && (
          <div className="space-y-4">
            {/* What gets connected */}
            <div className="rounded-xl bg-gray-50 p-4 text-xs text-gray-600 space-y-1.5">
              <p className="font-semibold text-gray-800 mb-2">What gets connected automatically:</p>
              <div className="flex items-center gap-2"><span className="text-green-500">✓</span> Google Ads campaigns &amp; spend</div>
              <div className="flex items-center gap-2"><span className="text-green-500">✓</span> YouTube channel &amp; analytics</div>
              <div className="flex items-center gap-2"><span className="text-green-500">✓</span> Merchant Center product feed</div>
            </div>

            {/* Single OAuth button */}
            <button
              onClick={handleOAuth}
              className="flex w-full items-center justify-center gap-3 rounded-xl border-2 border-blue-200 bg-blue-50 px-4 py-3.5 text-sm font-semibold text-blue-700 transition hover:bg-blue-100 active:scale-[0.99]"
            >
              <svg viewBox="0 0 48 48" className="h-5 w-5 shrink-0">
                <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
              Continue with Google
            </button>
            <p className="text-center text-xs text-gray-400">
              You&apos;ll be asked to choose your Google account and approve access.
              We never store your password.
            </p>

            <button
              onClick={onClose}
              className="w-full rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        )}

        {step === 'done' && (
          <div className="flex flex-col items-center gap-3 py-4">
            <CheckCircle className="h-12 w-12 text-green-500" />
            <p className="text-base font-semibold text-gray-900">Connected!</p>
            <p className="text-sm text-gray-500">Redirecting…</p>
          </div>
        )}
      </div>
    </div>
  )
}
