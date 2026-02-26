'use client'

import { useState } from 'react'
import { X, Loader2, CheckCircle } from 'lucide-react'

interface Props {
  videoId: string
  videoTitle: string
  thumbnailUrl?: string
  workspaceId: string
  onClose: () => void
}

const PLATFORMS = ['meta', 'google', 'youtube'] as const

export default function PromoteAsAdModal({ videoId, videoTitle, thumbnailUrl, workspaceId, onClose }: Props) {
  const [platform, setPlatform] = useState<string>('meta')
  const [budgetDaily, setBudgetDaily] = useState(500)
  const [durationDays, setDurationDays] = useState(14)
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  async function handleSubmit() {
    setLoading(true)
    try {
      const res = await fetch('/api/actions/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          platform,
          entity_id: videoId,
          entity_name: videoTitle,
          entity_level: 'video',
          action_type: 'promote_as_ad',
          description: note || `Promote YouTube video as ${platform} ad`,
          suggested_value: {
            budget_daily: budgetDaily,
            duration_days: durationDays,
            video_id: videoId,
          },
          triggered_by: 'dashboard_user',
        }),
      })
      if (!res.ok) throw new Error('Failed')
      setDone(true)
      setTimeout(onClose, 1800)
    } catch {
      alert('Failed to create action. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} />

      {/* Modal */}
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 p-5">
          <h2 className="text-base font-semibold text-gray-900">Promote as Ad</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Video preview */}
          <div className="flex items-center gap-3 rounded-xl bg-gray-50 p-3">
            {thumbnailUrl ? (
              <img src={thumbnailUrl} alt="" className="h-14 w-24 shrink-0 rounded-lg object-cover" />
            ) : (
              <div className="h-14 w-24 shrink-0 rounded-lg bg-gray-200" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-800 line-clamp-2">{videoTitle}</p>
              <p className="text-xs text-gray-400 mt-0.5">YouTube · {videoId}</p>
            </div>
          </div>

          {done ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <CheckCircle className="h-10 w-10 text-green-500" />
              <p className="text-sm font-semibold text-gray-900">Added to Approvals!</p>
              <p className="text-xs text-gray-500">Your team will review and activate the promotion.</p>
            </div>
          ) : (
            <>
              {/* Platform */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-2">Platform</label>
                <div className="flex gap-2">
                  {PLATFORMS.map(p => (
                    <button
                      key={p}
                      onClick={() => setPlatform(p)}
                      className={`flex-1 rounded-lg border py-2 text-xs font-medium transition-colors ${
                        platform === p
                          ? 'border-blue-500 bg-blue-50 text-blue-700'
                          : 'border-gray-200 text-gray-500 hover:border-gray-300'
                      }`}
                    >
                      {p.charAt(0).toUpperCase() + p.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Budget */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Daily Budget: ₹{budgetDaily.toLocaleString()}
                </label>
                <input
                  type="range"
                  min={100}
                  max={10000}
                  step={100}
                  value={budgetDaily}
                  onChange={e => setBudgetDaily(Number(e.target.value))}
                  className="w-full accent-blue-600"
                />
                <div className="flex justify-between text-[10px] text-gray-400">
                  <span>₹100</span><span>₹10k</span>
                </div>
              </div>

              {/* Duration */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Duration: {durationDays} days
                </label>
                <input
                  type="range"
                  min={3}
                  max={60}
                  step={1}
                  value={durationDays}
                  onChange={e => setDurationDays(Number(e.target.value))}
                  className="w-full accent-blue-600"
                />
                <div className="flex justify-between text-[10px] text-gray-400">
                  <span>3d</span><span>60d</span>
                </div>
              </div>

              {/* Note */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Note (optional)</label>
                <input
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  placeholder="e.g. Target cardiac patients, use retargeting audience"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>

              <div className="flex items-center justify-between text-xs text-gray-500 bg-blue-50 rounded-lg px-3 py-2">
                <span>Total estimated budget:</span>
                <span className="font-bold text-blue-700">₹{(budgetDaily * durationDays).toLocaleString()}</span>
              </div>

              <button
                onClick={handleSubmit}
                disabled={loading}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Add to Approvals
              </button>
            </>
          )}
        </div>
      </div>
    </>
  )
}
