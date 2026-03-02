'use client'

import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Loader2, CheckCircle, ExternalLink } from 'lucide-react'

interface AdAccount {
  id: string
  name: string
  account_status: number
  currency: string
}

interface Props {
  workspaceId: string
  onConnected: () => void
  onClose: () => void
  /** If set, we already have an OAuth session — skip straight to account picker */
  sessionId?: string
}

export default function MetaConnectDialog({ workspaceId, onConnected, onClose, sessionId }: Props) {
  const [step, setStep] = useState<'connect' | 'accounts' | 'done'>(sessionId ? 'accounts' : 'connect')
  const [userName, setUserName] = useState('')
  const [adAccounts, setAdAccounts] = useState<AdAccount[]>([])
  const [selectedAccount, setSelectedAccount] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeSession, setActiveSession] = useState(sessionId ?? '')

  // When opened in session mode — load ad accounts from the pending session
  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    fetch(`/api/meta/oauth/session?session_id=${sessionId}`)
      .then(r => r.json())
      .then(data => {
        setUserName(data.user_name ?? '')
        setAdAccounts(data.ad_accounts ?? [])
        setSelectedAccount(data.ad_accounts?.[0]?.id ?? '')
        setActiveSession(sessionId)
      })
      .catch(() => toast.error('Failed to load Facebook account data'))
      .finally(() => setLoading(false))
  }, [sessionId])

  const startOAuth = () => {
    // Redirect the full page to the OAuth start route
    window.location.href = `/api/meta/oauth/start?ws=${workspaceId}`
  }

  const connectAccount = async () => {
    if (!selectedAccount) return toast.error('Select an ad account')
    setLoading(true)
    try {
      const res = await fetch('/api/meta/oauth/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: activeSession, ad_account_id: selectedAccount }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      setStep('done')
      toast.success('Meta Ads connected!')
      setTimeout(() => { onConnected(); onClose() }, 1500)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to connect account')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        {/* Header */}
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600">
            <span className="text-lg font-bold text-white">f</span>
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">Connect Meta Ads</h2>
            <p className="text-xs text-gray-500">Sign in with Facebook to link your ad account</p>
          </div>
        </div>

        {/* Step 1: Connect via Facebook OAuth */}
        {step === 'connect' && (
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
              <p className="font-semibold mb-1">What happens when you connect:</p>
              <ul className="space-y-1 text-xs text-blue-700 list-disc list-inside">
                <li>Log in with your Facebook account</li>
                <li>Grant access to your Meta Ads Manager</li>
                <li>Select which ad account to link</li>
                <li>We&apos;ll pull campaign data automatically</li>
              </ul>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs text-gray-500">
              We request <strong>ads_management</strong> + <strong>ads_read</strong> permissions only.
              You can revoke access from your Facebook settings at any time.
            </div>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={startOAuth}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Connect with Facebook
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Account selection (after OAuth with multiple accounts) */}
        {step === 'accounts' && (
          <div className="space-y-4">
            {loading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              </div>
            ) : (
              <>
                <p className="text-sm text-gray-600">
                  Signed in as <strong>{userName}</strong>. Select an ad account to link:
                </p>
                <div className="max-h-52 space-y-1.5 overflow-y-auto">
                  {adAccounts.map(acc => (
                    <label
                      key={acc.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                        selectedAccount === acc.id
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="account"
                        value={acc.id}
                        checked={selectedAccount === acc.id}
                        onChange={e => setSelectedAccount(e.target.value)}
                        className="accent-blue-600"
                      />
                      <div>
                        <p className="text-sm font-medium text-gray-900">{acc.name}</p>
                        <p className="text-xs text-gray-400">
                          {acc.id} · {acc.currency}
                          {acc.account_status !== 1 && (
                            <span className="ml-1 text-amber-500">(inactive)</span>
                          )}
                        </p>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={onClose}
                    className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={connectAccount}
                    disabled={loading || !selectedAccount}
                    className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Connect Account
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Step 3: Done */}
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
