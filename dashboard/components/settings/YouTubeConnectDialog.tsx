'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, CheckCircle, ExternalLink } from 'lucide-react'

interface Props {
  workspaceId: string
  onConnected: () => void
  onClose: () => void
}

export default function YouTubeConnectDialog({
  workspaceId,
  onConnected,
  onClose,
}: Props) {
  const [step, setStep] = useState<'form' | 'done'>('form')
  const [loading, setLoading] = useState(false)
  const [channelId, setChannelId] = useState('')

  const handleConnect = async () => {
    const id = channelId.trim()
    if (!id) return toast.error('Channel ID is required')
    if (!id.startsWith('UC')) {
      return toast.error('Channel ID should start with "UC"')
    }

    setLoading(true)
    try {
      const res = await fetch('/api/youtube/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          youtube_channel_id: id,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      setStep('done')
      toast.success('YouTube channel connected!')
      setTimeout(() => {
        onConnected()
        onClose()
      }, 1500)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to connect YouTube')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        {/* Header */}
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-600">
            <svg viewBox="0 0 24 24" className="h-6 w-6 fill-white">
              <path d="M19.59 6.69a4.83 4.83 0 01-3.77-2.75 12.58 12.58 0 00-7.64 0A4.83 4.83 0 014.41 6.69 48.75 48.75 0 004 12a48.75 48.75 0 00.41 5.31 4.83 4.83 0 003.77 2.75 12.58 12.58 0 007.64 0 4.83 4.83 0 003.77-2.75A48.75 48.75 0 0020 12a48.75 48.75 0 00-.41-5.31zM10 15.5v-7l6 3.5-6 3.5z" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Connect YouTube Channel
            </h2>
            <p className="text-xs text-gray-500">
              Uses your existing Google OAuth2 credentials
            </p>
          </div>
        </div>

        {step === 'form' && (
          <div className="space-y-4">
            {/* Instructions */}
            <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
              <p className="font-semibold">How to find your Channel ID:</p>
              <ol className="mt-1 list-inside list-decimal space-y-0.5">
                <li>
                  Go to{' '}
                  <a
                    href="https://studio.youtube.com"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 underline"
                  >
                    YouTube Studio <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                </li>
                <li>Click Customisation → Basic info</li>
                <li>Copy the Channel URL — the ID starts with UC…</li>
              </ol>
            </div>

            {/* Channel ID field */}
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                YouTube Channel ID <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={channelId}
                onChange={e => setChannelId(e.target.value)}
                placeholder="UCxxxxxxxxxxxxxxxxxxxxxxxxxx"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-red-500"
              />
              <p className="mt-1 text-xs text-gray-400">
                Should start with &quot;UC&quot; (24 characters total)
              </p>
            </div>

            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConnect}
                disabled={loading}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Connect Channel
              </button>
            </div>
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
