'use client'

import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { CheckCircle, Loader2, ExternalLink, Zap } from 'lucide-react'

type WorkspaceType = 'd2c' | 'creator' | 'agency' | 'saas'
type Platform = 'youtube' | 'meta' | 'google'

export const PLATFORM_ORDER: Record<WorkspaceType, Platform[]> = {
  creator: ['youtube', 'meta', 'google'],
  d2c:     ['meta', 'google', 'youtube'],
  agency:  ['meta', 'google', 'youtube'],
  saas:    ['google', 'meta', 'youtube'],
}

interface Props {
  workspaceId: string
  bizType: WorkspaceType
  startStep?: number
  onDone: () => void
}

export default function ConnectAccountsStepper({ workspaceId, bizType, startStep = 0, onDone }: Props) {
  const platforms = PLATFORM_ORDER[bizType]
  const [stepIdx, setStepIdx] = useState(startStep)
  const [ytChannelId, setYtChannelId] = useState('')
  const [ytLoading, setYtLoading] = useState(false)
  const [ytDone, setYtDone] = useState(false)

  // If startStep is already past the end, finish immediately
  useEffect(() => {
    if (startStep >= platforms.length) {
      onDone()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (stepIdx >= platforms.length) return null

  const platform = platforms[stepIdx]

  const advance = () => {
    const next = stepIdx + 1
    if (next >= platforms.length) {
      onDone()
    } else {
      setStepIdx(next)
      setYtDone(false)
      setYtChannelId('')
    }
  }

  const connectYouTube = async () => {
    const id = ytChannelId.trim()
    if (!id) return toast.error('Channel ID is required')
    if (!id.startsWith('UC')) return toast.error('Channel ID should start with "UC"')
    setYtLoading(true)
    try {
      const res = await fetch('/api/youtube/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, youtube_channel_id: id }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      setYtDone(true)
      toast.success('YouTube channel connected!')
      setTimeout(advance, 1400)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to connect YouTube')
    } finally {
      setYtLoading(false)
    }
  }

  const connectMeta = () => {
    sessionStorage.setItem('runway_connect_stepper', JSON.stringify({
      wsId: workspaceId,
      bizType,
      nextStepIdx: stepIdx + 1,
    }))
    window.location.href = `/api/meta/oauth/start?ws=${workspaceId}`
  }

  const connectGoogle = () => {
    sessionStorage.setItem('runway_connect_stepper', JSON.stringify({
      wsId: workspaceId,
      bizType,
      nextStepIdx: stepIdx + 1,
    }))
    window.location.href = `/api/google/oauth/start?ws=${workspaceId}`
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden">

        {/* Progress bar segments */}
        <div className="flex gap-1 p-4 pb-0">
          {platforms.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-all duration-500 ${
                i < stepIdx ? 'bg-green-500' : i === stepIdx ? 'bg-blue-600' : 'bg-gray-200'
              }`}
            />
          ))}
        </div>

        <div className="p-6">
          <p className="text-xs font-medium text-gray-400 mb-1">
            Account {stepIdx + 1} of {platforms.length}
          </p>

          {/* ── YouTube step ── */}
          {platform === 'youtube' && (
            <>
              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-600 shrink-0">
                  <svg viewBox="0 0 24 24" className="h-6 w-6 fill-white">
                    <path d="M19.59 6.69a4.83 4.83 0 01-3.77-2.75 12.58 12.58 0 00-7.64 0A4.83 4.83 0 014.41 6.69 48.75 48.75 0 004 12a48.75 48.75 0 00.41 5.31 4.83 4.83 0 003.77 2.75 12.58 12.58 0 007.64 0 4.83 4.83 0 003.77-2.75A48.75 48.75 0 0020 12a48.75 48.75 0 00-.41-5.31zM10 15.5v-7l6 3.5-6 3.5z" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-base font-bold text-gray-900">Connect YouTube Channel</h2>
                  <p className="text-xs text-gray-500">Video analytics, competitor intel & growth plans</p>
                </div>
              </div>

              {ytDone ? (
                <div className="flex flex-col items-center gap-2 py-6">
                  <CheckCircle className="h-12 w-12 text-green-500" />
                  <p className="font-semibold text-gray-900">YouTube Connected!</p>
                  <p className="text-sm text-gray-400">Moving to next step…</p>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
                    <p className="font-semibold mb-1">How to find your Channel ID:</p>
                    <ol className="list-inside list-decimal space-y-0.5">
                      <li>Go to <a href="https://studio.youtube.com" target="_blank" rel="noreferrer" className="underline">YouTube Studio</a></li>
                      <li>Customisation → Basic info</li>
                      <li>Copy the Channel ID (starts with UC…)</li>
                    </ol>
                  </div>
                  <input
                    type="text"
                    value={ytChannelId}
                    onChange={e => setYtChannelId(e.target.value)}
                    placeholder="UCxxxxxxxxxxxxxxxxxxxxxxxxxx"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-red-400"
                  />
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={advance}
                      className="flex-1 rounded-lg border border-gray-200 px-4 py-2.5 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
                    >
                      Skip for now
                    </button>
                    <button
                      onClick={connectYouTube}
                      disabled={ytLoading || !ytChannelId.trim()}
                      className="flex flex-[2] items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                    >
                      {ytLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                      Connect Channel
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── Meta step ── */}
          {platform === 'meta' && (
            <>
              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600 shrink-0">
                  <span className="text-xl font-bold text-white">f</span>
                </div>
                <div>
                  <h2 className="text-base font-bold text-gray-900">Connect Meta Ads</h2>
                  <p className="text-xs text-gray-500">Facebook & Instagram campaign analytics</p>
                </div>
              </div>
              <div className="space-y-3">
                <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
                  <p className="font-semibold mb-1 text-xs">What we'll access (read-only):</p>
                  <ul className="space-y-0.5 text-xs text-blue-700 list-disc list-inside">
                    <li>Campaign performance — impressions, clicks, spend, ROAS</li>
                    <li>Ad set and audience breakdowns</li>
                    <li>Conversion and purchase metrics</li>
                  </ul>
                </div>
                <p className="text-xs text-gray-400">We never create, modify, or delete your ads.</p>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={advance}
                    className="flex-1 rounded-lg border border-gray-200 px-4 py-2.5 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
                  >
                    Skip for now
                  </button>
                  <button
                    onClick={connectMeta}
                    className="flex flex-[2] items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Connect with Facebook
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ── Google step ── */}
          {platform === 'google' && (
            <>
              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-gray-200 bg-white shrink-0">
                  <svg viewBox="0 0 24 24" className="h-5 w-5">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                </div>
                <div>
                  <h2 className="text-base font-bold text-gray-900">Connect Google</h2>
                  <p className="text-xs text-gray-500">Google Ads · YouTube Analytics · GA4</p>
                </div>
              </div>
              <div className="space-y-3">
                <div className="rounded-lg bg-green-50 p-3 text-sm text-green-800">
                  <p className="font-semibold mb-1 text-xs">One click connects all of:</p>
                  <ul className="space-y-0.5 text-xs text-green-700 list-disc list-inside">
                    <li>Google Ads — campaigns, keywords, auction insights</li>
                    <li>YouTube Analytics — watch time, CTR, revenue</li>
                    <li>Google Analytics 4 — traffic, conversions, landing pages</li>
                  </ul>
                </div>
                <p className="text-xs text-gray-400">Read-only access via Google OAuth2. Revoke any time from Google Account settings.</p>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={advance}
                    className="flex-1 rounded-lg border border-gray-200 px-4 py-2.5 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
                  >
                    Skip for now
                  </button>
                  <button
                    onClick={connectGoogle}
                    className="flex flex-[2] items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <svg viewBox="0 0 24 24" className="h-4 w-4">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Continue with Google
                  </button>
                </div>
              </div>
            </>
          )}

          {/* All done hint */}
          <div className="mt-4 flex items-center justify-center gap-1.5 text-xs text-gray-400">
            <Zap className="h-3 w-3 text-amber-400" />
            <span>You can always connect more accounts in <strong>Settings → Platform Connections</strong></span>
          </div>
        </div>
      </div>
    </div>
  )
}
