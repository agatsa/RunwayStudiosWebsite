'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Search, Globe, Zap, CheckCircle2, Loader2, RefreshCw,
  ChevronRight, ExternalLink, AlertCircle, Target, Megaphone,
  TrendingUp, Star, Code2, ShoppingBag, BookOpen, ArrowRight,
  BadgeCheck, X,
} from 'lucide-react'
// No react-markdown dependency — render recipe as pre-formatted text

interface Candidate {
  url: string
  domain: string
  name: string
  confidence_pct: number
  topic_space: string[]
  is_auto: boolean
  confirmed: boolean
}

interface CompetitorProfile {
  id: string
  name: string
  url: string
  confidence_pct: number
  brand_dna: {
    tagline?: string
    icp?: string
    uvp?: string
    key_messages?: string[]
    positioning?: string
    social_links?: Record<string, string>
  }
  meta_ads: {
    found?: boolean
    ad_count?: number
    summary?: {
      found?: boolean
      ad_count: number
      winning_creatives: Array<{ body: string; title: string; days_running: number; platforms: string[] }>
      top_message_themes: string[]
      platform_mix: Record<string, number>
    }
  }
  pricing_intel: {
    found?: boolean
    tiers?: Array<{ name: string; price: string; billing?: string; key_features?: string[] }>
    has_free_tier?: boolean
    has_trial?: boolean
  }
  review_intel: {
    pain_points?: string[]
    wins?: string[]
    trustpilot?: { found: boolean; rating?: number; review_count?: string }
    g2?: { found: boolean; rating?: number }
  }
  tech_stack: string[]
  content_strategy: {
    found?: boolean
    pillars?: string[]
    cadence?: string
  }
}

interface GrowthRecipe {
  exists: boolean
  competitive_gaps: Array<{ gap: string; opportunity: string; priority: string }>
  ad_angle_opportunities: Array<{ angle: string; headline: string; body: string; why_it_works: string }>
  recipe_text: string
}

type UIState = 'idle' | 'discovering' | 'awaiting_confirmation' | 'analysing' | 'completed'

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-50 border-red-200 text-red-700',
  medium: 'bg-amber-50 border-amber-200 text-amber-700',
  low: 'bg-green-50 border-green-200 text-green-700',
}

export default function BrandIntelPanel({ workspaceId }: { workspaceId: string }) {
  const [uiState, setUiState]         = useState<UIState>('idle')
  const [jobId, setJobId]             = useState<string | null>(null)
  const [brandUrl, setBrandUrl]       = useState('')
  const [logEntries, setLogEntries]   = useState<Array<{ type: string; msg: string; ts?: string }>>([])
  const [candidates, setCandidates]   = useState<Candidate[]>([])
  const [ownTopics, setOwnTopics]     = useState<string[]>([])
  const [checkedDomains, setCheckedDomains] = useState<string[]>([])
  const [manualUrls, setManualUrls]   = useState(['', '', ''])
  const [profiles, setProfiles]       = useState<CompetitorProfile[]>([])
  const [recipe, setRecipe]           = useState<GrowthRecipe | null>(null)
  const [activeTab, setActiveTab]     = useState<'overview' | 'ads' | 'pricing' | 'reviews' | 'recipe'>('overview')
  const [confirming, setConfirming]   = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const fetchDiscoveryStatus = useCallback(async (jid: string) => {
    try {
      const r = await fetch(`/api/brand-intel/discovery-status?workspace_id=${workspaceId}&job_id=${jid}`)
      const d = await r.json()
      if (!d.exists) return
      setLogEntries(d.discovery_log || [])
      setCandidates(d.candidates || [])
      setOwnTopics(d.own_topic_space || [])
      if (d.discovery_status === 'awaiting_confirmation') {
        setUiState('awaiting_confirmation')
        stopPoll()
        // Pre-check all auto candidates
        const doms = (d.candidates || []).filter((c: Candidate) => c.is_auto).map((c: Candidate) => c.domain)
        setCheckedDomains(doms)
      } else if (d.discovery_status === 'analysing') {
        setUiState('analysing')
      } else if (d.status === 'completed') {
        setUiState('completed')
        stopPoll()
        fetchProfiles(jid)
        fetchRecipe()
      }
    } catch { /* ignore */ }
  }, [workspaceId])

  const fetchProfiles = async (jid: string) => {
    try {
      const r = await fetch(`/api/brand-intel/profiles?workspace_id=${workspaceId}&job_id=${jid}`)
      const d = await r.json()
      setProfiles(d.profiles || [])
    } catch { /* ignore */ }
  }

  const fetchRecipe = async () => {
    try {
      const r = await fetch(`/api/brand-intel/growth-recipe?workspace_id=${workspaceId}`)
      const d = await r.json()
      if (d.exists) setRecipe(d)
    } catch { /* ignore */ }
  }

  // On mount, check if there's an existing job
  useEffect(() => {
    const init = async () => {
      try {
        const r = await fetch(`/api/brand-intel/status?workspace_id=${workspaceId}`)
        const d = await r.json()
        if (!d.exists) return
        setJobId(d.job_id)
        if (d.status === 'completed') {
          setUiState('completed')
          fetchProfiles(d.job_id)
          fetchRecipe()
        } else if (d.discovery_status === 'awaiting_confirmation') {
          fetchDiscoveryStatus(d.job_id)
        } else if (d.status === 'discovering' || d.status === 'analysing' || d.discovery_status === 'analysing') {
          setUiState(d.discovery_status === 'analysing' ? 'analysing' : 'discovering')
          startPolling(d.job_id)
        }
      } catch { /* ignore */ }
    }
    init()
  }, [workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const startPolling = (jid: string) => {
    stopPoll()
    pollRef.current = setInterval(() => fetchDiscoveryStatus(jid), 2000)
  }

  // Analysis phase polling
  useEffect(() => {
    if (uiState !== 'analysing' || !jobId) return
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`/api/brand-intel/discovery-status?workspace_id=${workspaceId}&job_id=${jobId}`)
        const d = await r.json()
        setLogEntries(d.discovery_log || [])
        if (d.status === 'completed') {
          setUiState('completed')
          clearInterval(poll)
          fetchProfiles(jobId)
          fetchRecipe()
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(poll)
  }, [uiState, jobId, workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logEntries])

  const handleStart = async () => {
    if (!brandUrl.trim() && uiState === 'idle') return
    setUiState('discovering')
    setLogEntries([])
    setCandidates([])
    try {
      const r = await fetch('/api/brand-intel/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, brand_url: brandUrl.trim() }),
      })
      const d = await r.json()
      if (d.job_id) {
        setJobId(d.job_id)
        startPolling(d.job_id)
      }
    } catch {
      setUiState('idle')
    }
  }

  const handleReDiscover = async () => {
    setUiState('discovering')
    setLogEntries([])
    setCandidates([])
    setProfiles([])
    setRecipe(null)
    try {
      const r = await fetch('/api/brand-intel/re-discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, brand_url: brandUrl.trim() }),
      })
      const d = await r.json()
      if (d.job_id) {
        setJobId(d.job_id)
        startPolling(d.job_id)
      }
    } catch {
      setUiState('completed')
    }
  }

  const handleConfirm = async () => {
    if (!jobId) return
    setConfirming(true)
    try {
      const r = await fetch('/api/brand-intel/confirm-discovery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id:      workspaceId,
          job_id:            jobId,
          confirmed_domains: checkedDomains,
          manual_urls:       manualUrls.filter(u => u.trim()),
        }),
      })
      if (r.ok) {
        setUiState('analysing')
        setLogEntries([])
      }
    } catch { /* ignore */ }
    setConfirming(false)
  }

  const toggleDomain = (domain: string) => {
    setCheckedDomains(prev =>
      prev.includes(domain) ? prev.filter(d => d !== domain) : [...prev, domain]
    )
  }

  const updateManual = (i: number, val: string) => {
    setManualUrls(prev => { const n = [...prev]; n[i] = val; return n })
  }

  // ── Render ────────────────────────────────────────────────────────────────

  // Idle state
  if (uiState === 'idle') {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600">
          <Search className="h-8 w-8 text-white" />
        </div>
        <h3 className="text-lg font-bold text-gray-900 mb-2">Start Brand & Competitor Intelligence</h3>
        <p className="text-sm text-gray-500 max-w-md mx-auto mb-6">
          ARIA will scrape competitor websites, pull their active Meta ads, analyse pricing, reviews,
          and generate a personalised growth recipe — all automatically.
        </p>
        <div className="max-w-sm mx-auto mb-4">
          <div className="relative">
            <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="url"
              value={brandUrl}
              onChange={e => setBrandUrl(e.target.value)}
              placeholder="https://yourbrand.com"
              className="w-full rounded-xl border border-gray-200 pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
            />
          </div>
          <p className="mt-1.5 text-xs text-gray-400">Your website URL — ARIA will auto-discover competitors</p>
        </div>
        <button
          onClick={handleStart}
          disabled={!brandUrl.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors disabled:opacity-40"
        >
          <Zap className="h-4 w-4" />
          Start Discovery
        </button>

        {/* Layer preview */}
        <div className="mt-8 grid grid-cols-3 gap-3 text-left max-w-lg mx-auto">
          {[
            { icon: Globe, label: 'Brand DNA', desc: 'Tagline, ICP, UVP, positioning' },
            { icon: Megaphone, label: 'Meta Ads', desc: 'All active ads from Ad Library' },
            { icon: TrendingUp, label: 'SERP Presence', desc: 'Search rankings & visibility' },
            { icon: ShoppingBag, label: 'Pricing Intel', desc: 'Tiers, price points, trials' },
            { icon: Star, label: 'Review Intel', desc: 'Pain points & wins from customers' },
            { icon: Code2, label: 'Tech Stack', desc: 'Tools & platforms they use' },
          ].map(({ icon: Icon, label, desc }) => (
            <div key={label} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className="h-3.5 w-3.5 text-indigo-500" />
                <span className="text-xs font-semibold text-gray-700">{label}</span>
              </div>
              <p className="text-[11px] text-gray-500">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Discovering state — live terminal log
  if (uiState === 'discovering') {
    return (
      <div className="rounded-2xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-900 px-4 py-3 flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="h-3 w-3 rounded-full bg-red-500/70" />
            <div className="h-3 w-3 rounded-full bg-yellow-500/70" />
            <div className="h-3 w-3 rounded-full bg-green-500/70" />
          </div>
          <span className="text-xs text-gray-400 font-mono ml-2">ARIA Brand Discovery — scanning competitors…</span>
          <Loader2 className="h-3.5 w-3.5 text-green-400 animate-spin ml-auto" />
        </div>

        {/* Own topic pills */}
        {ownTopics.length > 0 && (
          <div className="bg-gray-800 border-b border-gray-700 px-4 py-2">
            <p className="text-[10px] text-gray-400 mb-1.5 font-mono">YOUR BRAND SIGNALS</p>
            <div className="flex flex-wrap gap-1.5">
              {ownTopics.slice(0, 10).map(k => (
                <span key={k} className="rounded-full bg-indigo-900/60 border border-indigo-700/40 px-2 py-0.5 text-[11px] text-indigo-300 font-mono">
                  {k}
                </span>
              ))}
            </div>
          </div>
        )}

        <div ref={logRef} className="bg-gray-900 h-64 overflow-y-auto p-4 font-mono text-xs space-y-1">
          {logEntries.map((e, i) => (
            <div key={i} className={
              e.type === 'candidate' ? 'text-green-400' :
              e.type === 'search'    ? 'text-yellow-400' :
              e.type === 'done'      ? 'text-blue-400 font-bold' :
              e.type === 'error'     ? 'text-red-400' :
              'text-gray-300'
            }>
              <span className="text-gray-600 mr-2 select-none">›</span>{e.msg}
            </div>
          ))}
          {logEntries.length === 0 && (
            <div className="text-gray-500">Initialising…</div>
          )}
        </div>
      </div>
    )
  }

  // Awaiting confirmation — candidate cards
  if (uiState === 'awaiting_confirmation') {
    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-900">Review competitor candidates</p>
            <p className="text-xs text-amber-700 mt-0.5">
              ARIA found {candidates.length} potential competitors. Select which to analyse deeply,
              or add your own.
            </p>
          </div>
        </div>

        {/* Own topic pills */}
        {ownTopics.length > 0 && (
          <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3">
            <p className="text-xs font-semibold text-indigo-700 mb-2">Your brand signals</p>
            <div className="flex flex-wrap gap-1.5">
              {ownTopics.slice(0, 10).map(k => (
                <span key={k} className="rounded-full bg-indigo-100 border border-indigo-200 px-2 py-0.5 text-xs text-indigo-700">
                  {k}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Candidate cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {candidates.map(c => (
            <button
              key={c.domain}
              onClick={() => toggleDomain(c.domain)}
              className={`relative flex flex-col items-start gap-2 rounded-2xl border p-4 text-left transition-all ${
                checkedDomains.includes(c.domain)
                  ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-300'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              {checkedDomains.includes(c.domain) && (
                <BadgeCheck className="absolute top-3 right-3 h-4 w-4 text-indigo-500" />
              )}
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100 text-xs font-bold text-gray-600">
                  {c.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900">{c.name}</p>
                  <p className="text-xs text-gray-400">{c.domain}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  c.confidence_pct >= 70 ? 'bg-green-100 text-green-700' :
                  c.confidence_pct >= 50 ? 'bg-yellow-100 text-yellow-700' :
                  'bg-gray-100 text-gray-600'
                }`}>
                  {c.confidence_pct}% match
                </span>
                {!c.is_auto && (
                  <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">manual</span>
                )}
              </div>
              {c.topic_space.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {c.topic_space.slice(0, 4).map(k => (
                    <span key={k} className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{k}</span>
                  ))}
                </div>
              )}
            </button>
          ))}
        </div>

        {/* Manual URLs */}
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Add competitors manually (optional)</p>
          <div className="space-y-2">
            {manualUrls.map((u, i) => (
              <input
                key={i}
                type="url"
                value={u}
                onChange={e => updateManual(i, e.target.value)}
                placeholder={`Competitor URL ${i + 1}`}
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            ))}
          </div>
        </div>

        <button
          onClick={handleConfirm}
          disabled={confirming || checkedDomains.length === 0}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {confirming ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
          Confirm {checkedDomains.length} competitor{checkedDomains.length !== 1 ? 's' : ''} & Start Deep Analysis
        </button>
      </div>
    )
  }

  // Analysing state
  if (uiState === 'analysing') {
    return (
      <div className="rounded-2xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-900 px-4 py-3 flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="h-3 w-3 rounded-full bg-red-500/70" />
            <div className="h-3 w-3 rounded-full bg-yellow-500/70" />
            <div className="h-3 w-3 rounded-full bg-green-500/70" />
          </div>
          <span className="text-xs text-gray-400 font-mono ml-2">ARIA Deep Analysis — 9-layer intelligence…</span>
          <Loader2 className="h-3.5 w-3.5 text-green-400 animate-spin ml-auto" />
        </div>
        <div ref={logRef} className="bg-gray-900 h-72 overflow-y-auto p-4 font-mono text-xs space-y-1">
          {logEntries.map((e, i) => (
            <div key={i} className={
              e.type === 'done_competitor' ? 'text-green-400' :
              e.type === 'phase'           ? 'text-cyan-300 font-semibold' :
              e.type === 'layer'           ? 'text-gray-300' :
              e.type === 'done'            ? 'text-blue-400 font-bold' :
              'text-gray-500'
            }>
              <span className="text-gray-600 mr-2 select-none">›</span>{e.msg}
            </div>
          ))}
          {logEntries.length === 0 && <div className="text-gray-500">Starting analysis…</div>}
        </div>
      </div>
    )
  }

  // Completed — full intel dashboard
  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-green-500" />
          <span className="text-sm font-semibold text-gray-900">
            {profiles.length} competitor{profiles.length !== 1 ? 's' : ''} analysed
          </span>
        </div>
        <button
          onClick={handleReDiscover}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Re-discover
        </button>
      </div>

      {/* Competitor cards */}
      {profiles.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {profiles.map(p => (
            <div key={p.id} className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-sm font-bold text-white">
                    {p.name.charAt(0)}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{p.name}</p>
                    <a href={p.url} target="_blank" rel="noreferrer"
                       className="text-xs text-indigo-500 hover:underline flex items-center gap-0.5">
                      {p.url.replace(/https?:\/\/(www\.)?/, '').split('/')[0]}
                      <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  p.confidence_pct >= 70 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {p.confidence_pct}%
                </span>
              </div>

              {p.brand_dna.positioning && (
                <p className="text-xs text-gray-600 mb-2 italic">&ldquo;{p.brand_dna.positioning}&rdquo;</p>
              )}

              {/* Meta ads badge */}
              {(p.meta_ads?.summary?.ad_count || 0) > 0 && (
                <div className="mb-2 flex items-center gap-1.5 rounded-lg bg-blue-50 px-2.5 py-1.5">
                  <Megaphone className="h-3.5 w-3.5 text-blue-500" />
                  <span className="text-xs font-medium text-blue-700">
                    {p.meta_ads.summary!.ad_count} active Meta ads
                  </span>
                  {p.meta_ads.summary!.top_message_themes.slice(0, 2).map(t => (
                    <span key={t} className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-600">{t}</span>
                  ))}
                </div>
              )}

              {/* Review rating */}
              {(p.review_intel?.trustpilot?.rating || p.review_intel?.g2?.rating) && (
                <div className="mb-2 flex items-center gap-1.5">
                  <Star className="h-3.5 w-3.5 text-yellow-400" />
                  <span className="text-xs text-gray-600">
                    {p.review_intel.trustpilot?.rating ?? p.review_intel.g2?.rating}/5
                  </span>
                </div>
              )}

              {/* Tech stack pills */}
              {p.tech_stack.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {p.tech_stack.slice(0, 4).map(t => (
                    <span key={t} className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">{t}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tabs for detailed intel */}
      {profiles.length > 0 && (
        <div className="rounded-2xl border border-gray-200 overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-gray-100 bg-gray-50 overflow-x-auto">
            {[
              { id: 'overview' as const, label: 'Overview' },
              { id: 'ads'      as const, label: 'Meta Ads' },
              { id: 'pricing'  as const, label: 'Pricing' },
              { id: 'reviews'  as const, label: 'Reviews' },
              { id: 'recipe'   as const, label: 'Growth Recipe' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`shrink-0 px-4 py-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'border-b-2 border-indigo-500 text-indigo-600 bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="p-5">
            {/* Overview tab */}
            {activeTab === 'overview' && (
              <div className="space-y-4">
                {profiles.map(p => (
                  <div key={p.id} className="rounded-xl border border-gray-100 p-4">
                    <h4 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                      {p.name}
                      <a href={p.url} target="_blank" rel="noreferrer">
                        <ExternalLink className="h-3.5 w-3.5 text-gray-400" />
                      </a>
                    </h4>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-[11px] font-semibold text-gray-400 uppercase mb-1">Tagline</p>
                        <p className="text-xs text-gray-700">{p.brand_dna.tagline || '—'}</p>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold text-gray-400 uppercase mb-1">ICP</p>
                        <p className="text-xs text-gray-700">{p.brand_dna.icp || '—'}</p>
                      </div>
                      <div className="col-span-2">
                        <p className="text-[11px] font-semibold text-gray-400 uppercase mb-1">Unique Value Prop</p>
                        <p className="text-xs text-gray-700">{p.brand_dna.uvp || '—'}</p>
                      </div>
                      {p.content_strategy.pillars && p.content_strategy.pillars.length > 0 && (
                        <div className="col-span-2">
                          <p className="text-[11px] font-semibold text-gray-400 uppercase mb-1">Content Pillars</p>
                          <div className="flex flex-wrap gap-1.5">
                            {p.content_strategy.pillars.map(pi => (
                              <span key={pi} className="rounded-full bg-purple-50 border border-purple-100 px-2 py-0.5 text-[11px] text-purple-700">
                                {pi}
                              </span>
                            ))}
                          </div>
                          {p.content_strategy.cadence && (
                            <p className="text-xs text-gray-500 mt-1">Posts {p.content_strategy.cadence}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Meta Ads tab */}
            {activeTab === 'ads' && (
              <div className="space-y-4">
                {profiles.map(p => {
                  const adSummary = p.meta_ads?.summary
                  if (!adSummary?.found) {
                    return (
                      <div key={p.id} className="rounded-xl border border-gray-100 p-4">
                        <h4 className="font-semibold text-gray-700 mb-2">{p.name}</h4>
                        <p className="text-sm text-gray-400">No active Meta ads found in Ad Library.</p>
                      </div>
                    )
                  }
                  return (
                    <div key={p.id} className="rounded-xl border border-gray-100 p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="font-semibold text-gray-900">{p.name}</h4>
                        <span className="text-xs font-medium text-blue-600 bg-blue-50 rounded-full px-2.5 py-0.5">
                          {adSummary.ad_count} active ads
                        </span>
                      </div>
                      <div className="mb-3 flex flex-wrap gap-1.5">
                        {adSummary.top_message_themes.map(t => (
                          <span key={t} className="rounded-full bg-blue-100 border border-blue-200 px-2 py-0.5 text-xs text-blue-700">{t}</span>
                        ))}
                      </div>
                      <p className="text-[11px] font-semibold text-gray-400 uppercase mb-2">Winning Creatives (longest running)</p>
                      <div className="space-y-2">
                        {adSummary.winning_creatives.map((wc, i) => (
                          <div key={i} className="rounded-lg border border-green-100 bg-green-50 p-3">
                            {wc.title && <p className="text-xs font-semibold text-gray-800 mb-0.5">{wc.title}</p>}
                            <p className="text-xs text-gray-600">{wc.body}</p>
                            <div className="mt-1.5 flex items-center gap-2">
                              <span className="text-[10px] font-medium text-green-700 bg-green-100 rounded px-1.5 py-0.5">
                                {wc.days_running}d running
                              </span>
                              {wc.platforms.map(pl => (
                                <span key={pl} className="text-[10px] text-gray-500">{pl}</span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Pricing tab */}
            {activeTab === 'pricing' && (
              <div className="space-y-4">
                {profiles.map(p => (
                  <div key={p.id} className="rounded-xl border border-gray-100 p-4">
                    <h4 className="font-semibold text-gray-900 mb-3">{p.name}</h4>
                    {p.pricing_intel.found && p.pricing_intel.tiers && p.pricing_intel.tiers.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {p.pricing_intel.tiers.map((t, i) => (
                          <div key={i} className="rounded-xl border border-gray-200 p-3 bg-gray-50">
                            <p className="text-sm font-bold text-gray-900">{t.name}</p>
                            <p className="text-lg font-extrabold text-indigo-600 mt-1">
                              {t.price === '0' ? 'Free' : t.price}
                              {t.billing && t.price !== '0' && <span className="text-xs font-normal text-gray-500">/{t.billing}</span>}
                            </p>
                            {t.key_features && (
                              <ul className="mt-2 space-y-0.5">
                                {t.key_features.slice(0, 3).map((f, fi) => (
                                  <li key={fi} className="text-[11px] text-gray-600 flex gap-1">
                                    <span className="text-green-500">✓</span>{f}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400">Pricing page not found or not parseable.</p>
                    )}
                    <div className="flex gap-3 mt-2">
                      {p.pricing_intel.has_free_tier && (
                        <span className="text-xs text-green-700 bg-green-50 rounded-full px-2 py-0.5 border border-green-100">
                          Has free tier
                        </span>
                      )}
                      {p.pricing_intel.has_trial && (
                        <span className="text-xs text-blue-700 bg-blue-50 rounded-full px-2 py-0.5 border border-blue-100">
                          Free trial
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Reviews tab */}
            {activeTab === 'reviews' && (
              <div className="space-y-4">
                {profiles.map(p => (
                  <div key={p.id} className="rounded-xl border border-gray-100 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="font-semibold text-gray-900">{p.name}</h4>
                      <div className="flex gap-2">
                        {p.review_intel?.trustpilot?.rating && (
                          <span className="text-xs text-gray-600 flex items-center gap-1">
                            <Star className="h-3 w-3 text-yellow-400" />
                            {p.review_intel.trustpilot.rating} Trustpilot
                          </span>
                        )}
                        {p.review_intel?.g2?.rating && (
                          <span className="text-xs text-gray-600 flex items-center gap-1">
                            <Star className="h-3 w-3 text-yellow-400" />
                            {p.review_intel.g2.rating} G2
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-[11px] font-semibold text-red-600 uppercase mb-2">Customer Pain Points</p>
                        <ul className="space-y-1">
                          {(p.review_intel?.pain_points || []).map((pt, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                              <X className="h-3 w-3 text-red-400 shrink-0 mt-0.5" />{pt}
                            </li>
                          ))}
                          {!(p.review_intel?.pain_points?.length) && <li className="text-xs text-gray-400">None found</li>}
                        </ul>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold text-green-600 uppercase mb-2">What Customers Love</p>
                        <ul className="space-y-1">
                          {(p.review_intel?.wins || []).map((w, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                              <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0 mt-0.5" />{w}
                            </li>
                          ))}
                          {!(p.review_intel?.wins?.length) && <li className="text-xs text-gray-400">None found</li>}
                        </ul>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Growth Recipe tab */}
            {activeTab === 'recipe' && recipe && recipe.exists && (
              <div className="space-y-5">
                {/* Competitive gaps */}
                {recipe.competitive_gaps.length > 0 && (
                  <div>
                    <h4 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                      <Target className="h-4 w-4 text-red-500" /> Competitive Gaps
                    </h4>
                    <div className="space-y-2">
                      {recipe.competitive_gaps.map((g, i) => (
                        <div key={i} className={`rounded-xl border px-4 py-3 ${PRIORITY_COLORS[g.priority] || PRIORITY_COLORS.medium}`}>
                          <div className="flex items-start gap-2">
                            <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${PRIORITY_COLORS[g.priority]}`}>
                              {g.priority}
                            </span>
                            <div>
                              <p className="text-xs font-semibold">{g.gap}</p>
                              <p className="text-xs mt-0.5 opacity-80">→ {g.opportunity}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Ad angles */}
                {recipe.ad_angle_opportunities.length > 0 && (
                  <div>
                    <h4 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                      <Megaphone className="h-4 w-4 text-blue-500" /> Winning Ad Angles to Test
                    </h4>
                    <div className="space-y-3">
                      {recipe.ad_angle_opportunities.map((a, i) => (
                        <div key={i} className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="text-xs font-bold text-blue-800 uppercase">{a.angle}</span>
                          </div>
                          <p className="text-sm font-semibold text-gray-900 mb-1">&ldquo;{a.headline}&rdquo;</p>
                          <p className="text-xs text-gray-600 italic mb-2">{a.body}</p>
                          <p className="text-xs text-blue-700">
                            <span className="font-semibold">Why it works:</span> {a.why_it_works}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Full narrative */}
                {recipe.recipe_text && (
                  <div>
                    <h4 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                      <BookOpen className="h-4 w-4 text-purple-500" /> Full Strategy
                    </h4>
                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 font-mono text-xs text-gray-700 whitespace-pre-wrap leading-relaxed overflow-x-auto">
                      {recipe.recipe_text}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'recipe' && !recipe?.exists && (
              <div className="py-8 text-center text-gray-400">
                <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
                <p className="text-sm">Growth recipe is generating…</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
