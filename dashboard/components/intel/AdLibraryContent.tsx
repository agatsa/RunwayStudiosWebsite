'use client'

import { useState, useEffect, useRef, MutableRefObject } from 'react'
import {
  Search, Loader2, Zap, ExternalLink, Clock, Globe,
  ChevronDown, ChevronUp, Image as ImageIcon, History,
  AlertCircle, Play,
} from 'lucide-react'
import { useWorkspace } from '@/components/layout/WorkspaceProvider'

// ─── Types ────────────────────────────────────────────────────────────────────

type AdCard = {
  ad_id:      string | number
  page_name:  string
  is_active:  boolean
  is_video:   boolean
  body:       string
  headline:   string
  cta:        string
  link:       string
  platforms:  string[]
  start_date: string | null
  end_date:   string | null
  run_days:   number | null
  media_urls: string[]
  cards:      { title: string; body: string; link: string; img: string }[]
}

type SearchJob = {
  job_id:    string
  status:    'running' | 'completed' | 'failed' | 'timeout'
  query:     string
  country:   string
  ads?:      AdCard[]
  analysis?: string
  ad_count?: number
}

type HistoryItem = {
  job_id:     string
  query:      string
  country:    string
  status:     string
  ad_count:   number
  created_at: string
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function AdCardItem({ ad }: { ad: AdCard }) {
  const [expanded, setExpanded] = useState(false)
  const hasMedia = ad.media_urls.length > 0
  const isVideo  = ad.is_video === true

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden hover:shadow-md transition-shadow">
      {/* Media preview */}
      {hasMedia && !isVideo && (
        <div className="relative bg-gray-100 h-40 overflow-hidden">
          <img
            src={ad.media_urls[0]}
            alt="Ad creative"
            className="w-full h-full object-cover"
            referrerPolicy="no-referrer"
            crossOrigin="anonymous"
            onError={e => {
              const el = e.target as HTMLImageElement
              el.style.display = 'none'
              const parent = el.parentElement
              if (parent) {
                parent.innerHTML = '<div class="flex items-center justify-center h-full text-gray-300"><svg xmlns=\'http://www.w3.org/2000/svg\' class=\'h-8 w-8\' fill=\'none\' viewBox=\'0 0 24 24\' stroke=\'currentColor\'><path stroke-linecap=\'round\' stroke-linejoin=\'round\' stroke-width=\'1\' d=\'M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z\'/></svg></div>'
              }
            }}
          />
        </div>
      )}
      {isVideo && (
        <div className="relative flex items-center justify-center bg-gray-900 h-40">
          {ad.media_urls[0] && (
            <img
              src={ad.media_urls[0]}
              alt="Video thumbnail"
              className="absolute inset-0 w-full h-full object-cover opacity-50"
              referrerPolicy="no-referrer"
              onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
            />
          )}
          <Play className="relative h-8 w-8 text-white opacity-80" />
        </div>
      )}
      {!hasMedia && (
        <div className="flex items-center justify-center bg-gray-50 h-20 border-b border-gray-100">
          <ImageIcon className="h-8 w-8 text-gray-300" />
        </div>
      )}

      {/* Content */}
      <div className="p-3 space-y-2">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-gray-900 leading-tight">{ad.page_name || 'Unknown'}</p>
            {ad.headline && (
              <p className="text-xs text-gray-600 mt-0.5 line-clamp-1">{ad.headline}</p>
            )}
          </div>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
            ad.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
          }`}>
            {ad.is_active ? 'ACTIVE' : 'INACTIVE'}
          </span>
        </div>

        {/* Body copy */}
        {ad.body && (
          <p className={`text-xs text-gray-600 leading-relaxed ${expanded ? '' : 'line-clamp-3'}`}>
            {ad.body}
          </p>
        )}
        {ad.body && ad.body.length > 150 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-[10px] text-indigo-500 hover:text-indigo-700 flex items-center gap-0.5"
          >
            {expanded ? <><ChevronUp className="h-3 w-3" /> Less</> : <><ChevronDown className="h-3 w-3" /> More</>}
          </button>
        )}

        {/* Carousel cards */}
        {ad.cards.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {ad.cards.map((c, i) => (
              <div key={i} className="shrink-0 w-28 rounded-lg border border-gray-100 p-1.5 text-[10px] text-gray-600">
                {c.img && (
                  <img src={c.img} alt="" className="w-full h-12 object-cover rounded mb-1"
                    referrerPolicy="no-referrer"
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                )}
                <p className="font-medium text-gray-800 line-clamp-2">{c.title || c.body}</p>
              </div>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-gray-100">
          <div className="flex items-center gap-2 text-[10px] text-gray-400">
            {ad.run_days !== null && (
              <span className="flex items-center gap-0.5">
                <Clock className="h-2.5 w-2.5" />{ad.run_days}d
              </span>
            )}
            {ad.platforms.slice(0, 2).map(p => (
              <span key={p} className="capitalize">{p.toLowerCase()}</span>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {ad.cta && (
              <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[9px] font-semibold text-indigo-600 uppercase tracking-wide">
                {ad.cta}
              </span>
            )}
            {ad.link && (
              <a href={ad.link} target="_blank" rel="noopener noreferrer"
                className="text-gray-400 hover:text-indigo-600">
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AnalysisPanel({ analysis }: { analysis: string }) {
  return (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="h-4 w-4 text-indigo-600" />
        <p className="text-sm font-semibold text-indigo-900">AI Competitive Intelligence</p>
      </div>
      <div className="prose prose-sm max-w-none text-gray-800 text-xs leading-relaxed whitespace-pre-wrap">
        {analysis}
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

type Props = {
  wsId: string
  onRunningChange?: (running: boolean) => void
  stopRef?: MutableRefObject<(() => void) | null>
}

export default function AdLibraryContent({ wsId, onRunningChange, stopRef }: Props) {
  const { current: workspace } = useWorkspace()
  const [suggestions,    setSuggestions]    = useState<{ label: string; query: string; own: boolean }[]>([])
  const [query,      setQuery]      = useState('')
  const [country,    setCountry]    = useState('IN')
  const [activeOnly, setActiveOnly] = useState(true)
  const [maxItems,   setMaxItems]   = useState(10)
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState('')
  const [job,            setJob]            = useState<SearchJob | null>(null)
  const [history,        setHistory]        = useState<HistoryItem[]>([])
  const [showHist,       setShowHist]       = useState(false)
  const [creditsUsed,    setCreditsUsed]    = useState<number | null>(null)
  const pollRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const mountedRef  = useRef(true)

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setLoading(false)
    onRunningChange?.(false)
  }

  // Expose stop function to parent
  useEffect(() => {
    if (stopRef) stopRef.current = stopPolling
  })

  // Track mount state — component stays mounted (hidden) when switching tabs
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  // Load history on mount
  useEffect(() => {
    if (!wsId) return
    fetch(`/api/intel/ad-library/history?workspace_id=${wsId}`)
      .then(r => r.json())
      .then(d => { if (mountedRef.current) setHistory(d.history || []) })
      .catch(() => {})
  }, [wsId])

  // Load competitor suggestions from brand intel
  useEffect(() => {
    if (!wsId) return
    fetch(`/api/brand-intel/profiles?workspace_id=${wsId}`)
      .then(r => r.json())
      .then(d => {
        if (!mountedRef.current) return
        const chips: { label: string; query: string; own: boolean }[] = []
        const brandName = workspace?.name || ''
        if (brandName) chips.push({ label: brandName, query: brandName, own: true })
        for (const p of (d.profiles || [])) {
          if (p.name) chips.push({ label: p.name, query: p.name, own: false })
        }
        setSuggestions(chips)
        // Pre-fill with first competitor name if query is empty
        if (chips.length > 1 && !query) setQuery(chips[1].query)
      })
      .catch(() => {})
  }, [wsId, workspace?.name])

  const startPoll = (jobId: string, credits?: number) => {
    if (pollRef.current) clearInterval(pollRef.current)
    onRunningChange?.(true)
    pollRef.current = setInterval(async () => {
      if (!mountedRef.current) {
        clearInterval(pollRef.current!)
        pollRef.current = null
        return
      }
      try {
        const r = await fetch(`/api/intel/ad-library/status/${jobId}`)
        const d: SearchJob = await r.json()
        if (!mountedRef.current) return
        setJob(d)
        if (d.status !== 'running') {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setLoading(false)
          onRunningChange?.(false)
          if (d.status === 'completed' && credits) setCreditsUsed(credits)
          // Refresh history
          const hr = await fetch(`/api/intel/ad-library/history?workspace_id=${wsId}`)
          const hd = await hr.json()
          if (mountedRef.current) setHistory(hd.history || [])
        }
      } catch {
        if (!mountedRef.current) return
        clearInterval(pollRef.current!)
        pollRef.current = null
        setLoading(false)
        onRunningChange?.(false)
      }
    }, 4000)
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    setError('')
    setLoading(true)
    setJob(null)
    try {
      const r = await fetch('/api/intel/ad-library/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: wsId,
          query: query.trim(),
          country,
          active_only: activeOnly,
          max_items: maxItems,
        }),
      })
      const d = await r.json()
      if (!r.ok) {
        if (r.status === 402 && d.detail?.error === 'apify_limit_exceeded') {
          setError('Ad Library search is temporarily unavailable due to high demand. Please submit a support ticket at support@runwaystudios.co and we\'ll restore access within 24 hours.')
        } else if (r.status === 402) {
          setError(`Insufficient credits — you need 5 credits for an Ad Library search. ${d.detail?.message || ''}`)
        } else {
          setError(d.detail?.message || d.detail || 'Search failed. Please try again.')
        }
        setLoading(false)
        return
      }
      setCreditsUsed(null)
      setJob({ job_id: d.job_id, status: 'running', query: query.trim(), country })
      startPoll(d.job_id, d.credits_required ?? creditsForSearch)
    } catch {
      setError('Network error. Please try again.')
      setLoading(false)
    }
  }

  const loadHistoryJob = async (item: HistoryItem) => {
    if (item.status !== 'completed') return
    const r = await fetch(`/api/intel/ad-library/status/${item.job_id}`)
    const d: SearchJob = await r.json()
    setJob(d)
    setShowHist(false)
  }

  const creditsForSearch = Math.ceil(maxItems / 10) * 15   // mirrors backend formula

  const COUNTRIES = [
    { code: 'IN', label: 'India' },
    { code: 'US', label: 'United States' },
    { code: 'GB', label: 'United Kingdom' },
    { code: 'SG', label: 'Singapore' },
    { code: 'AE', label: 'UAE' },
    { code: 'AU', label: 'Australia' },
  ]

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Meta Ad Library Search</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Search competitor ads by keyword · Powered by Apify · 5 credits per search
          </p>
        </div>
        <button
          onClick={() => setShowHist(h => !h)}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          <History className="h-3.5 w-3.5" />
          History ({history.length})
        </button>
      </div>

      {/* Search form */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-[11px] text-gray-400 self-center mr-1">Search for:</span>
            {suggestions.map(s => (
              <button
                key={s.query}
                onClick={() => setQuery(s.query)}
                disabled={loading}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors ${
                  s.own
                    ? 'border-brand-300 bg-brand-50 text-brand-700 hover:bg-brand-100'
                    : 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                } ${query === s.query ? 'ring-1 ring-offset-1 ring-indigo-400' : ''}`}
              >
                {s.own ? '★ ' : ''}{s.label}
              </button>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="e.g. ECG machine, blood pressure monitor, diabetes kit..."
              className="w-full rounded-lg border border-gray-300 pl-9 pr-3 py-2 text-sm focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400 outline-none"
              disabled={loading}
            />
          </div>
          <select
            value={country}
            onChange={e => setCountry(e.target.value)}
            className="rounded-lg border border-gray-300 px-2 py-2 text-sm text-gray-700 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400 outline-none"
            disabled={loading}
          >
            {COUNTRIES.map(c => (
              <option key={c.code} value={c.code}>{c.code} — {c.label}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-4 text-xs text-gray-600">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={e => setActiveOnly(e.target.checked)}
              className="rounded"
              disabled={loading}
            />
            Active ads only
          </label>
          <label className="flex items-center gap-1.5 select-none">
            Max results:
            <select
              value={maxItems}
              onChange={e => setMaxItems(Number(e.target.value))}
              className="ml-1 rounded border border-gray-300 px-1 py-0.5 text-xs"
              disabled={loading}
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={30}>30</option>
              <option value={50}>50</option>
            </select>
          </label>
          <span className="ml-auto flex items-center gap-1 text-amber-600 font-medium">
            <Zap className="h-3 w-3" /> {creditsForSearch} credits for {maxItems} ads
          </span>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {loading ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> Searching Ad Library…</>
          ) : (
            <><Search className="h-4 w-4" /> Search Competitor Ads · {creditsForSearch} credits</>
          )}
        </button>
      </div>

      {/* History panel */}
      {showHist && history.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-700 mb-2">Recent Searches</p>
          {history.map(item => (
            <button
              key={item.job_id}
              onClick={() => loadHistoryJob(item)}
              className="w-full flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
            >
              <div>
                <p className="text-sm font-medium text-gray-800">{item.query}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  {item.country} · {item.ad_count} ads · {new Date(item.created_at).toLocaleDateString()}
                </p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                item.status === 'completed' ? 'bg-green-100 text-green-700' :
                item.status === 'running'   ? 'bg-blue-100 text-blue-700' :
                'bg-red-100 text-red-700'
              }`}>
                {item.status}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Results */}
      {job && job.status === 'running' && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-500">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
          <p className="text-sm font-medium">Scraping Meta Ad Library…</p>
          <p className="text-xs text-gray-400">This usually takes 60–120 seconds</p>
        </div>
      )}

      {job && (job.status === 'failed' || job.status === 'timeout') && (
        <div className="flex flex-col items-center justify-center py-12 gap-2 text-red-500">
          <AlertCircle className="h-8 w-8" />
          <p className="text-sm font-medium">
            {job.status === 'timeout' ? 'Search timed out. Please try again.' : 'Search failed. Please try again.'}
          </p>
        </div>
      )}

      {job && job.status === 'completed' && (
        <div className="space-y-5">
          {/* Summary bar */}
          <div className="flex items-center justify-between gap-3 rounded-xl border border-green-200 bg-green-50 px-4 py-3">
            <div className="flex items-center gap-3">
              <Globe className="h-4 w-4 text-green-600 shrink-0" />
              <p className="text-sm font-medium text-green-800">
                Found <strong>{job.ad_count}</strong> ads for &ldquo;{job.query}&rdquo; in {job.country}
              </p>
            </div>
            {creditsUsed != null && (
              <div className="flex items-center gap-1.5 rounded-full bg-amber-100 border border-amber-200 px-3 py-1 text-xs font-semibold text-amber-700">
                <Zap className="h-3 w-3" />
                {creditsUsed} credits used
              </div>
            )}
          </div>

          {/* Claude analysis */}
          {job.analysis && <AnalysisPanel analysis={job.analysis} />}

          {/* Ad grid */}
          {job.ads && job.ads.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 mb-3">
                AD CREATIVES ({job.ads.length})
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {job.ads.map((ad, i) => (
                  <AdCardItem key={ad.ad_id ?? i} ad={ad} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!job && !loading && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
          <Search className="h-10 w-10 text-gray-200" />
          <p className="text-sm">Enter a keyword to search competitor ads across India and beyond</p>
          <p className="text-xs">Try: &ldquo;ECG machine&rdquo;, &ldquo;blood sugar monitor&rdquo;, &ldquo;health device&rdquo;</p>
        </div>
      )}
    </div>
  )
}
