'use client'

import { useState, useEffect } from 'react'
import { X, CheckCircle, Loader2, AlertCircle, Building2 } from 'lucide-react'

interface GoogleAccount {
  customer_id: string
  name: string
  is_manager: boolean
  is_current: boolean
}

interface Props {
  workspaceId: string
  onSuccess: () => void
  onClose: () => void
}

export default function GoogleAccountSelectDialog({ workspaceId, onSuccess, onClose }: Props) {
  const [accounts, setAccounts] = useState<GoogleAccount[]>([])
  const [selected, setSelected] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`/api/google/accessible-customers?ws=${workspaceId}`, {
          cache: 'no-store',
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        setAccounts(data.accounts ?? [])
        const current = (data.accounts ?? []).find((a: GoogleAccount) => a.is_current)
        setSelected(current?.customer_id ?? data.accounts?.[0]?.customer_id ?? '')
      } catch {
        setError('Could not load accounts')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [workspaceId])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const res = await fetch('/api/google/select-customer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, customer_id: selected }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      onSuccess()
      onClose()
    } catch {
      setError('Failed to save selection. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Select Google Ads Account</h2>
            <p className="text-xs text-gray-500 mt-0.5">Choose the account you want to manage</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-2.5">
          {loading ? (
            // Skeleton
            <>
              {[1, 2, 3].map(i => (
                <div key={i} className="h-16 rounded-xl bg-gray-100 animate-pulse" />
              ))}
            </>
          ) : error ? (
            <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          ) : (
            accounts.map(account => {
              const isSelected = selected === account.customer_id
              return (
                <button
                  key={account.customer_id}
                  onClick={() => setSelected(account.customer_id)}
                  className={`w-full rounded-xl border-2 p-4 text-left transition-all ${
                    isSelected
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Radio indicator */}
                    <div
                      className={`mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors ${
                        isSelected ? 'border-blue-500 bg-blue-500' : 'border-gray-300'
                      }`}
                    >
                      {isSelected && (
                        <div className="h-full w-full flex items-center justify-center">
                          <div className="h-1.5 w-1.5 rounded-full bg-white" />
                        </div>
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-sm font-medium text-gray-900 truncate">
                          {account.name === account.customer_id
                            ? `Account ${account.customer_id}`
                            : account.name}
                        </span>
                        {account.is_manager && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
                            <Building2 className="h-2.5 w-2.5" />
                            Manager
                          </span>
                        )}
                        {account.is_current && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                            <CheckCircle className="h-2.5 w-2.5" />
                            Current
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 font-mono text-xs text-gray-400">{account.customer_id}</p>
                    </div>
                  </div>
                </button>
              )
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading || !!error || !selected}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save Selection
          </button>
        </div>
      </div>
    </div>
  )
}
