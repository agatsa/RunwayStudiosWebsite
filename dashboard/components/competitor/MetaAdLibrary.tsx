'use client'

import { useEffect, useState } from 'react'
import { Megaphone, RefreshCw, ExternalLink, Trophy, Clock } from 'lucide-react'

interface Ad {
  ad_id: string
  ad_copy: string | null
  headline: string | null
  snapshot_url: string | null
  media_type: string | null
  platforms: string[]
  delivery_start_date: string | null
  running_days: number | null
  is_proven_winner: boolean
}

interface CompetitorPage {
  page_name: string
  ad_count: number
  proven_winners: number
  ads: Ad[]
}

interface LibraryData {
  has_data: boolean
  last_synced: string | null
  competitors: CompetitorPage[]
}

const MEDIA_LABELS: Record<string, string> = {
  IMAGE:    'Image',
  VIDEO:    'Video',
  CAROUSEL: 'Carousel',
}

const MEDIA_COLORS: Record<string, string> = {
  IMAGE:    'bg-blue-100 text-blue-700',
  VIDEO:    'bg-red-100 text-red-700',
  CAROUSEL: 'bg-purple-100 text-purple-700',
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3_600_000)
  if (h < 1) return 'just now'
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

function AdCard({ ad }: { ad: Ad }) {
  const mediaKey = (ad.media_type ?? '').toUpperCase()
  const mediaLabel = MEDIA_LABELS[mediaKey] ?? ad.media_type ?? 'Ad'
  const mediaColor = MEDIA_COLORS[mediaKey] ?? 'bg-gray-100 text-gray-600'

  return (
    <div className={`relative rounded-lg border p-3 text-xs ${
      ad.is_proven_winner
        ? 'border-amber-200 bg-amber-50/50'
        : 'border-gray-100 bg-white'
    }`}>
      {ad.is_proven_winner && (
        <div className="absolute -top-2 right-3 flex items-center gap-1 rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-bold text-white">
          <Trophy className="h-2.5 w-2.5" />
          Proven Winner
        </div>
      )}

      {/* badges row */}
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${mediaColor}`}>
          {mediaLabel}
        </span>
        {ad.platforms.slice(0, 2).map(p => (
          <span key={p} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500 capitalize">
            {p}
          </span>
        ))}
        {ad.running_days !== null && (
          <span className={`ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
            ad.is_proven_winner ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'
          }`}>
            <Clock className="h-2.5 w-2.5" />
            {ad.running_days}d running
          </span>
        )}
      </div>

      {/* headline */}
      {ad.headline && (
        <p className="font-semibold text-gray-800 mb-1 line-clamp-1">{ad.headline}</p>
      )}

      {/* copy */}
      {ad.ad_copy ? (
        <p className="text-gray-600 line-clamp-3 leading-relaxed">{ad.ad_copy}</p>
      ) : (
        <p className="text-gray-300 italic">No copy text available</p>
      )}

      {/* snapshot link */}
      {ad.snapshot_url && (
        <a
          href={ad.snapshot_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-[10px] text-blue-600 hover:underline"
        >
          View ad <ExternalLink className="h-2.5 w-2.5" />
        </a>
      )}
    </div>
  )
}

export default function MetaAdLibrary({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<LibraryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const load = async () => {
    try {
      const r = await fetch(`/api/meta/ad-library/ads?workspace_id=${workspaceId}`)
      if (r.ok) setData(await r.json())
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [workspaceId])

  const handleSync = async () => {
    setSyncing(true)
    setSyncMsg(null)
    try {
      const r = await fetch('/api/meta/ad-library/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      const d = await r.json()
      if (d.status === 'no_meta_token' || d.status === 'no_platform_token') {
        setSyncMsg('⚠️ Ad Library token not configured — contact Runway Studios support.')
      } else if (d.status === 'no_competitors') {
        setSyncMsg('⚠️ No competitors found — add brand names in Settings → Meta Ad Library Competitors, or run YouTube Competitor Discovery.')
      } else if (d.status === 'ok') {
        const total = (d.synced as {ads_found?: number}[]).reduce((s, c) => s + (c.ads_found ?? 0), 0)
        if (d.api_warning) {
          setSyncMsg(`⚠️ Meta API error: ${d.api_warning}. Your Meta developer account may need identity verification at developers.facebook.com → Tools → Ad Library API.`)
        } else if (total === 0) {
          setSyncMsg('Sync complete — 0 ads found. The competitors may not be running active ads, or the brand names may not match their Facebook page names exactly.')
        } else {
          setSyncMsg(null)
          await load()
        }
      } else {
        setSyncMsg('Sync complete.')
        await load()
      }
    } catch {
      setSyncMsg('Sync failed — try again.')
    }
    setSyncing(false)
  }

  const totalAds = data?.competitors.reduce((s, c) => s + c.ad_count, 0) ?? 0
  const totalWinners = data?.competitors.reduce((s, c) => s + c.proven_winners, 0) ?? 0

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
          <Megaphone className="h-4 w-4 text-blue-600" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900">Meta Ad Library Monitor</h3>
          <p className="text-xs text-gray-400">
            {data?.last_synced
              ? `Last synced ${timeAgo(data.last_synced)} · ${totalAds} ads · ${totalWinners} proven winners (90+ days)`
              : 'Competitor ads running on Facebook & Instagram'}
          </p>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${syncing ? 'animate-spin' : ''}`} />
          {syncing ? 'Syncing…' : 'Sync now'}
        </button>
      </div>

      {/* Sync message */}
      {syncMsg && (
        <div className="px-4 py-2 bg-blue-50 border-b border-blue-100 text-xs text-blue-700">
          {syncMsg}
        </div>
      )}

      {/* Body */}
      <div className="p-4">
        {loading ? (
          <div className="space-y-3">
            {[1, 2].map(i => (
              <div key={i} className="h-24 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : !data?.has_data ? (
          <div className="py-10 text-center">
            <Megaphone className="h-8 w-8 text-blue-300 mx-auto mb-3" />
            <p className="text-sm font-semibold text-gray-900">No competitor ads synced yet</p>
            <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
              Click <strong>Sync now</strong> to fetch active ads from your competitors on Facebook &amp; Instagram.
              We use the brand names from your YouTube Competitor Discovery.
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {data.competitors.map(comp => {
              const isOpen = expanded[comp.page_name] ?? true
              const shown = isOpen ? comp.ads : comp.ads.slice(0, 3)

              return (
                <div key={comp.page_name}>
                  {/* Competitor header */}
                  <div className="flex items-center gap-2 mb-2">
                    <div className="h-6 w-6 rounded-full bg-blue-100 flex items-center justify-center text-[10px] font-bold text-blue-700">
                      {comp.page_name.charAt(0).toUpperCase()}
                    </div>
                    <span className="text-sm font-semibold text-gray-800">{comp.page_name}</span>
                    <span className="text-xs text-gray-400">{comp.ad_count} active ads</span>
                    {comp.proven_winners > 0 && (
                      <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        <Trophy className="h-2.5 w-2.5" />
                        {comp.proven_winners} proven winner{comp.proven_winners > 1 ? 's' : ''}
                      </span>
                    )}
                    <button
                      onClick={() => setExpanded(p => ({ ...p, [comp.page_name]: !isOpen }))}
                      className="ml-auto text-xs text-gray-400 hover:text-gray-600"
                    >
                      {isOpen ? 'Collapse' : `Show all ${comp.ad_count}`}
                    </button>
                  </div>

                  {/* Ad grid */}
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {shown.map(ad => <AdCard key={ad.ad_id} ad={ad} />)}
                  </div>

                  {!isOpen && comp.ad_count > 3 && (
                    <button
                      onClick={() => setExpanded(p => ({ ...p, [comp.page_name]: true }))}
                      className="mt-2 text-xs text-blue-600 hover:underline"
                    >
                      + {comp.ad_count - 3} more ads
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
