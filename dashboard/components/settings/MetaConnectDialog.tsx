'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, CheckCircle } from 'lucide-react'

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
}

export default function MetaConnectDialog({ workspaceId, onConnected, onClose }: Props) {
  const [step, setStep] = useState<'token' | 'accounts' | 'done'>('token')
  const [token, setToken] = useState('')
  const [userName, setUserName] = useState('')
  const [adAccounts, setAdAccounts] = useState<AdAccount[]>([])
  const [selectedAccount, setSelectedAccount] = useState('')
  const [loading, setLoading] = useState(false)

  const validateToken = async () => {
    if (!token.trim()) return toast.error('Enter your Meta access token')
    setLoading(true)
    try {
      const res = await fetch('/api/settings/meta-connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, access_token: token.trim() }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Validation failed')
      if (data.step === 'select_account') {
        setUserName(data.user_name ?? '')
        setAdAccounts(data.ad_accounts ?? [])
        setSelectedAccount(data.ad_accounts?.[0]?.id ?? '')
        setStep('accounts')
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to validate token')
    } finally {
      setLoading(false)
    }
  }

  const connectAccount = async () => {
    if (!selectedAccount) return toast.error('Select an ad account')
    setLoading(true)
    try {
      const res = await fetch('/api/settings/meta-connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          access_token: token.trim(),
          ad_account_id: selectedAccount,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      setStep('done')
      toast.success('Meta account connected!')
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
            <p className="text-xs text-gray-500">Link your Meta Business account</p>
          </div>
        </div>

        {/* Step 1: Token */}
        {step === 'token' && (
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-700">
              <p className="font-semibold">How to get your access token:</p>
              <ol className="mt-1 list-inside list-decimal space-y-0.5">
                <li>
                  Go to{' '}
                  <a
                    href="https://developers.facebook.com/tools/explorer/"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    Meta Graph API Explorer
                  </a>
                </li>
                <li>Select your App → Generate Access Token</li>
                <li>Grant <strong>ads_management</strong> + <strong>ads_read</strong></li>
                <li>Copy the token and paste below</li>
              </ol>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                Access Token
              </label>
              <textarea
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="EAAUk58rh..."
                rows={3}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={validateToken}
                disabled={loading}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Validate & Fetch Accounts
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Account selection */}
        {step === 'accounts' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              Signed in as <strong>{userName}</strong>. Select an ad account:
            </p>
            <div className="max-h-48 space-y-1.5 overflow-y-auto">
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
                    </p>
                  </div>
                </label>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setStep('token')}
                className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Back
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
