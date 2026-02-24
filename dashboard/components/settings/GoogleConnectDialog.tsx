'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, CheckCircle, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react'

interface Props {
  workspaceId: string
  onConnected: () => void
  onClose: () => void
}

interface FormData {
  customer_id: string
  developer_token: string
  client_id: string
  client_secret: string
  refresh_token: string
  merchant_id: string
  login_customer_id: string
}

export default function GoogleConnectDialog({ workspaceId, onConnected, onClose }: Props) {
  const [step, setStep] = useState<'form' | 'done'>('form')
  const [loading, setLoading] = useState(false)
  const [showManual, setShowManual] = useState(false)
  const [form, setForm] = useState<FormData>({
    customer_id: '',
    developer_token: '',
    client_id: '',
    client_secret: '',
    refresh_token: '',
    merchant_id: '',
    login_customer_id: '',
  })

  const set = (field: keyof FormData) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(prev => ({ ...prev, [field]: e.target.value }))

  const handleOAuth = () => {
    // Redirect to Google OAuth consent — returns to /settings?ws=X&google_connected=1
    window.location.href = `/api/google/oauth/start?ws=${workspaceId}`
  }

  const handleConnect = async () => {
    if (!form.customer_id.trim()) return toast.error('Customer ID is required')
    if (!form.developer_token.trim()) return toast.error('Developer Token is required')
    if (!form.client_id.trim()) return toast.error('Client ID is required')
    if (!form.client_secret.trim()) return toast.error('Client Secret is required')
    if (!form.refresh_token.trim()) return toast.error('Refresh Token is required')

    setLoading(true)
    try {
      const res = await fetch('/api/settings/google-connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          customer_id: form.customer_id.trim().replace(/-/g, ''),
          developer_token: form.developer_token.trim(),
          client_id: form.client_id.trim(),
          client_secret: form.client_secret.trim(),
          refresh_token: form.refresh_token.trim(),
          merchant_id: form.merchant_id.trim() || undefined,
          login_customer_id: form.login_customer_id.trim() || undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      setStep('done')
      toast.success('Google Ads connected!')
      setTimeout(() => { onConnected(); onClose() }, 1500)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to connect Google Ads')
    } finally {
      setLoading(false)
    }
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
            {/* Primary: OAuth button */}
            <button
              onClick={handleOAuth}
              className="flex w-full items-center justify-center gap-3 rounded-xl border-2 border-blue-200 bg-blue-50 px-4 py-3 text-sm font-semibold text-blue-700 transition hover:bg-blue-100"
            >
              <svg viewBox="0 0 48 48" className="h-5 w-5 shrink-0">
                <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
              Sign in with Google
              <span className="ml-auto rounded-full bg-blue-200 px-2 py-0.5 text-xs font-medium text-blue-800">
                Recommended
              </span>
            </button>
            <p className="text-center text-xs text-gray-400">
              Opens Google sign-in — we auto-discover your Ads account&nbsp;&amp;&nbsp;YouTube channel.
              No copy-pasting.
            </p>

            {/* Divider */}
            <div className="flex items-center gap-3">
              <div className="flex-1 border-t border-gray-200" />
              <span className="text-xs text-gray-400">or</span>
              <div className="flex-1 border-t border-gray-200" />
            </div>

            {/* Collapsible manual form */}
            <button
              onClick={() => setShowManual(v => !v)}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-medium text-gray-500 hover:bg-gray-50"
            >
              Enter credentials manually
              {showManual ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>

            {showManual && (
              <div className="space-y-3 rounded-xl border border-gray-100 bg-gray-50 p-4">
                {/* Instructions */}
                <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-700">
                  <p className="font-semibold">You&apos;ll need:</p>
                  <ul className="mt-1 list-inside list-disc space-y-0.5">
                    <li>
                      <a href="https://ads.google.com/nav/selectaccount" target="_blank" rel="noreferrer" className="underline inline-flex items-center gap-0.5">
                        Google Ads Customer ID <ExternalLink className="h-2.5 w-2.5" />
                      </a>{' '}(digits only, no dashes)
                    </li>
                    <li>Developer Token from Google Ads → Tools → API Center</li>
                    <li>OAuth2 Client ID + Secret from Google Cloud Console</li>
                    <li>Refresh Token (use Google OAuth Playground to generate)</li>
                  </ul>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Customer ID <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.customer_id}
                      onChange={set('customer_id')}
                      placeholder="1234567890"
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Developer Token <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.developer_token}
                      onChange={set('developer_token')}
                      placeholder="ABcd1234..."
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Client ID <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.client_id}
                      onChange={set('client_id')}
                      placeholder="xxxxx.apps.googleusercontent.com"
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Client Secret <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="password"
                      value={form.client_secret}
                      onChange={set('client_secret')}
                      placeholder="GOCSPX-..."
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Refresh Token <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.refresh_token}
                      onChange={set('refresh_token')}
                      placeholder="1//0g..."
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-500">
                      Merchant Center ID <span className="text-gray-400">(optional)</span>
                    </label>
                    <input
                      type="text"
                      value={form.merchant_id}
                      onChange={set('merchant_id')}
                      placeholder="123456789"
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-500">
                      MCC / Login Customer ID <span className="text-gray-400">(optional)</span>
                    </label>
                    <input
                      type="text"
                      value={form.login_customer_id}
                      onChange={set('login_customer_id')}
                      placeholder="Manager account ID"
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>

                <button
                  onClick={handleConnect}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Connect manually
                </button>
              </div>
            )}

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
