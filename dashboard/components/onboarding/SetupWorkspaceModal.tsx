'use client'

import { useState } from 'react'
import { Zap, ArrowRight, X } from 'lucide-react'

interface Props {
  onCreated: (workspaceId: string) => void
  onCancel?: () => void
}

export default function SetupWorkspaceModal({ onCreated, onCancel }: Props) {
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/workspace/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed, workspace_type: 'd2c' }),
      })
      const data = await res.json()
      if (data.workspace_exists) {
        // Workspace already exists for this user — just reload
        onCreated('')
        return
      }
      if (!res.ok) throw new Error(data.detail ?? 'Failed to create workspace')
      onCreated(data.workspace_id)
    } catch (e) {
      setError((e as Error).message)
    }
    setLoading(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/80 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="relative bg-gradient-to-br from-brand-600 to-purple-700 px-6 py-8 text-center">
          {onCancel && (
            <button
              onClick={onCancel}
              className="absolute top-3 right-3 flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/20 mx-auto mb-4">
            <Zap className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">{onCancel ? 'New Workspace' : 'Welcome to Runway Studios'}</h1>
          <p className="text-sm text-white/70 mt-1">{onCancel ? 'Add a new brand to your account' : "Let's set up your workspace in 30 seconds"}</p>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-4">
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              What's your brand or business name?
            </label>
            <input
              type="text"
              autoFocus
              placeholder="e.g. My Brand, My Store, Acme Inc."
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              className="w-full rounded-xl border border-gray-200 px-4 py-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            onClick={handleCreate}
            disabled={loading || !name.trim()}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Creating workspace…' : <>Create Workspace <ArrowRight className="h-4 w-4" /></>}
          </button>

          {!onCancel && (
            <p className="text-center text-xs text-gray-400">
              You'll get 50 free credits to explore all AI features
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
