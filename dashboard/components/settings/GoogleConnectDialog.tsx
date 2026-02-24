'use client'

import { useState } from 'react'
import { CheckCircle } from 'lucide-react'

interface Props {
  workspaceId: string
  onConnected: () => void
  onClose: () => void
  oauthConfigured?: boolean
}

export default function GoogleConnectDialog({
  workspaceId,
  onConnected: _onConnected,
  onClose,
  oauthConfigured = false,
}: Props) {
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
            {oauthConfigured ? (
              /* ── OAuth is set up — show the Connect button ── */
              <>
                <div className="rounded-xl bg-gray-50 p-4 text-xs text-gray-600 space-y-1.5">
                  <p className="font-semibold text-gray-800 mb-2">What gets connected automatically:</p>
                  <div className="flex items-center gap-2"><span className="text-green-500">✓</span> Google Ads campaigns &amp; spend</div>
                  <div className="flex items-center gap-2"><span className="text-green-500">✓</span> YouTube channel &amp; analytics</div>
                  <div className="flex items-center gap-2"><span className="text-green-500">✓</span> Merchant Center product feed</div>
                </div>

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
              </>
            ) : (
              /* ── OAuth not yet set up — Coming Soon ── */
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                    Coming Soon
                  </span>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">
                  <span className="font-semibold">Google Ads &amp; YouTube Analytics</span> — Our team
                  will reach out to connect your account within 24 hours. In the meantime, your YouTube
                  channel can be connected below.
                </p>
                <a
                  href={`https://wa.me/918826283840?text=${encodeURIComponent("Hi, I'd like to connect my Google Ads account to Runway Studios dashboard")}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-green-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-green-600 active:scale-[0.99]"
                >
                  <svg viewBox="0 0 24 24" className="h-5 w-5 fill-white shrink-0">
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                  </svg>
                  Chat with us on WhatsApp
                </a>
              </div>
            )}

            <button
              onClick={onClose}
              className="w-full rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              {oauthConfigured ? 'Cancel' : 'Close'}
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
