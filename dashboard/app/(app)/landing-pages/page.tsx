'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Layout, RefreshCw, CheckCircle, AlertTriangle, Loader2,
  Zap, ExternalLink, ChevronDown, ChevronUp, Globe, Clock,
  Target, TrendingUp, Shield, Star, ArrowRight, History,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ── Types ───────────────────────────────────────────────────────────────────────

interface LPSignals {
  title: string; meta_desc: string; h1: string
  cta_count: number; ctas: { text: string; tag: string }[]
  price_visible: boolean; price_text: string
  image_count: number; broken_image_count: number
  has_trust_signals: boolean; has_reviews: boolean; has_guarantee: boolean
  word_count: number
}

interface SiteAudit {
  name: string; url: string; reachable: boolean
  score: number; grade: string
  load_ms_mobile: number; load_ms_desktop: number
  signals: LPSignals; issues: string[]
  recommendations?: { priority: string; title: string; detail: string; impact: string }[]
}

interface ConversionAnalysis {
  winner_index: number; winner_name: string; confidence: string
  conversion_verdict: string; key_insight: string
  site_verdicts: { name: string; verdict: string; biggest_fix: string }[]
}

interface AuditResult {
  our_site: SiteAudit
  competitors: SiteAudit[]
  conversion_analysis: ConversionAnalysis
  summary: {
    our_score: number; our_grade: string; our_load_ms: number
    our_cta_count: number; our_price_visible: boolean
    top_issue: string; recommendation_count: number
  }
}

interface AuditHistoryItem {
  job_id: string; brand_url: string; status: string
  score: number; grade: string; load_ms: number; top_issue: string
  created_at: string; updated_at: string
}

// ── Helpers ─────────────────────────────────────────────────────────────────────

function gradeColor(grade: string) {
  if (grade === 'A') return 'text-green-700 bg-green-100'
  if (grade === 'B') return 'text-blue-700 bg-blue-100'
  if (grade === 'C') return 'text-amber-700 bg-amber-100'
  if (grade === 'D') return 'text-orange-700 bg-orange-100'
  return 'text-red-700 bg-red-100'
}

function scoreBar(score: number) {
  const color = score >= 85 ? 'bg-green-500' : score >= 70 ? 'bg-blue-500' : score >= 55 ? 'bg-amber-500' : score >= 40 ? 'bg-orange-500' : 'bg-red-500'
  return (
    <div className="h-2 w-full rounded-full bg-gray-100 overflow-hidden">
      <div className={cn('h-2 rounded-full transition-all', color)} style={{ width: `${score}%` }} />
    </div>
  )
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  })
}

// ── Site Score Card ─────────────────────────────────────────────────────────────

function SiteScoreCard({ site, isOurs }: { site: SiteAudit; isOurs: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const sig = site.signals || {}

  return (
    <div className={cn('rounded-xl border bg-white overflow-hidden', isOurs && 'border-indigo-200 ring-1 ring-indigo-100')}>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-sm font-bold text-gray-900 truncate">{site.name}</span>
              {isOurs && <span className="rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5 text-[10px] font-bold">YOUR SITE</span>}
            </div>
            <a href={site.url} target="_blank" rel="noopener noreferrer"
              className="text-xs text-gray-400 hover:text-indigo-600 flex items-center gap-1">
              {site.url.replace(/^https?:\/\//, '').slice(0, 40)}
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          </div>
          <div className={cn('flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl text-lg font-black', gradeColor(site.grade))}>
            {site.grade}
            <span className="text-[9px] font-semibold">{site.score}/100</span>
          </div>
        </div>

        {scoreBar(site.score)}

        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-lg bg-gray-50 px-2 py-1.5 text-center">
            <p className="font-semibold text-gray-900">{site.load_ms_mobile ? `${(site.load_ms_mobile / 1000).toFixed(1)}s` : '—'}</p>
            <p className="text-gray-500">Mobile load</p>
          </div>
          <div className="rounded-lg bg-gray-50 px-2 py-1.5 text-center">
            <p className="font-semibold text-gray-900">{sig.cta_count ?? 0}</p>
            <p className="text-gray-500">CTAs</p>
          </div>
          <div className={cn('rounded-lg px-2 py-1.5 text-center', sig.price_visible ? 'bg-green-50' : 'bg-red-50')}>
            <p className={cn('font-semibold', sig.price_visible ? 'text-green-700' : 'text-red-600')}>{sig.price_visible ? '✓' : '✗'}</p>
            <p className={cn('text-[10px]', sig.price_visible ? 'text-green-600' : 'text-red-500')}>Price shown</p>
          </div>
        </div>

        <div className="mt-2 flex gap-2">
          {[
            { ok: sig.has_reviews, label: 'Reviews' },
            { ok: sig.has_guarantee, label: 'Guarantee' },
            { ok: sig.has_trust_signals, label: 'Trust' },
          ].map(({ ok, label }) => (
            <span key={label} className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium',
              ok ? 'bg-green-50 text-green-700' : 'bg-gray-50 text-gray-400')}>
              {ok ? '✓' : '✗'} {label}
            </span>
          ))}
        </div>

        {site.issues.length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-red-600 mb-1">Issues</p>
            <ul className="space-y-0.5">
              {site.issues.slice(0, expanded ? 99 : 2).map((issue, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600">
                  <AlertTriangle className="h-3 w-3 text-amber-500 shrink-0 mt-0.5" />
                  {issue}
                </li>
              ))}
            </ul>
            {site.issues.length > 2 && (
              <button onClick={() => setExpanded(v => !v)}
                className="mt-1 text-xs text-indigo-600 flex items-center gap-1">
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {expanded ? 'Show less' : `+${site.issues.length - 2} more`}
              </button>
            )}
          </div>
        )}
      </div>

      {isOurs && site.recommendations && site.recommendations.length > 0 && (
        <div className="border-t border-gray-100 bg-indigo-50 p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 mb-2">
            AI Recommendations
          </p>
          <div className="space-y-2">
            {site.recommendations.map((rec, i) => (
              <div key={i} className="rounded-lg bg-white border border-indigo-100 p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className={cn('rounded px-1.5 py-0.5 text-[9px] font-bold',
                    rec.priority === 'HIGH' ? 'bg-red-100 text-red-700' :
                    rec.priority === 'MEDIUM' ? 'bg-amber-100 text-amber-700' :
                    'bg-gray-100 text-gray-500')}>
                    {rec.priority}
                  </span>
                  <span className="text-xs font-semibold text-gray-800">{rec.title}</span>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">{rec.detail}</p>
                {rec.impact && (
                  <p className="mt-1 text-[10px] font-medium text-green-700">↑ {rec.impact}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main LP Audit Page ──────────────────────────────────────────────────────────

export default function LandingPagesPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''

  const [brandUrl, setBrandUrl] = useState('')
  const [competitorUrls, setCompetitorUrls] = useState(['', '', ''])
  const [jobId, setJobId] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)
  const [result, setResult] = useState<AuditResult | null>(null)
  const [history, setHistory] = useState<AuditHistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  // Load latest audit + history on mount
  useEffect(() => {
    if (!wsId) return
    fetch(`/api/lp-audit/latest?workspace_id=${wsId}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.audit?.result?.our_site) {
          setResult(d.audit.result)
          setBrandUrl(d.audit.brand_url || '')
        }
      }).catch(() => {})

    fetch(`/api/lp-audit/history?workspace_id=${wsId}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(d => setHistory(d?.audits ?? []))
      .catch(() => {})
  }, [wsId])

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const pollForResult = useCallback((jid: string) => {
    stopPolling()
    setPolling(true)
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/lp-audit/status?job_id=${jid}`, { cache: 'no-store' })
        const d = await r.json()
        if (d.status === 'completed' && d.result) {
          stopPolling()
          setPolling(false)
          setResult(d.result)
          setLoading(false)
          // Refresh history
          fetch(`/api/lp-audit/history?workspace_id=${wsId}`, { cache: 'no-store' })
            .then(r => r.ok ? r.json() : null)
            .then(d => setHistory(d?.audits ?? [])).catch(() => {})
        } else if (d.status === 'failed') {
          stopPolling()
          setPolling(false)
          setLoading(false)
          setError('Audit failed — check the URL and try again')
        }
      } catch { /* ignore */ }
    }, 4000)
  }, [wsId])

  useEffect(() => () => stopPolling(), [])

  const handleStartAudit = async () => {
    if (!brandUrl.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api/lp-audit/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: wsId,
          brand_url: brandUrl.trim(),
          competitor_urls: competitorUrls.filter(u => u.trim()),
        }),
      })
      const d = await res.json()
      if (d.job_id) {
        setJobId(d.job_id)
        pollForResult(d.job_id)
      } else {
        setError('Failed to start audit')
        setLoading(false)
      }
    } catch {
      setError('Network error — try again')
      setLoading(false)
    }
  }

  const loadHistoricAudit = async (jid: string) => {
    setShowHistory(false)
    try {
      const r = await fetch(`/api/lp-audit/status?job_id=${jid}`, { cache: 'no-store' })
      const d = await r.json()
      if (d.result?.our_site) setResult(d.result)
    } catch { /* ignore */ }
  }

  const isRunning = loading || polling

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Layout className="h-5 w-5 text-indigo-500" />
            <h1 className="text-xl font-bold text-gray-900">Landing Page Auditor</h1>
          </div>
          <p className="text-sm text-gray-500">
            Score your landing page against competitors — CTA quality, load time, price visibility, conversion readiness
          </p>
        </div>
        <div className="flex items-center gap-2">
          {history.length > 0 && (
            <div className="relative">
              <button
                onClick={() => setShowHistory(v => !v)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
              >
                <History className="h-3.5 w-3.5" />
                Past Audits ({history.length})
                <ChevronDown className={cn('h-3 w-3 transition-transform', showHistory && 'rotate-180')} />
              </button>
              {showHistory && (
                <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-xl border border-gray-200 bg-white shadow-xl overflow-hidden">
                  <div className="px-3 py-2 border-b border-gray-100">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400">Audit History</p>
                  </div>
                  <div className="max-h-64 overflow-y-auto divide-y divide-gray-50">
                    {history.map(h => (
                      <button key={h.job_id} onClick={() => loadHistoricAudit(h.job_id)}
                        className="w-full text-left px-3 py-2.5 hover:bg-gray-50 transition-colors">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-xs font-semibold text-gray-800">{formatDate(h.created_at)}</span>
                          {h.grade && (
                            <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold', gradeColor(h.grade))}>
                              {h.grade} {h.score}/100
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-gray-500 truncate">{h.brand_url}</p>
                        {h.top_issue && <p className="text-[10px] text-red-500 truncate">{h.top_issue}</p>}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Input Form */}
      <div className="rounded-xl border bg-white p-5 space-y-4">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
            Your landing page URL *
          </label>
          <input
            type="url"
            value={brandUrl}
            onChange={e => setBrandUrl(e.target.value)}
            placeholder="https://yourbrand.com/product-page"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            disabled={isRunning}
          />
        </div>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
            Competitor URLs to compare against <span className="font-normal text-gray-400">(optional — ARIA auto-discovers from Brand Intel)</span>
          </label>
          <div className="space-y-2">
            {competitorUrls.map((url, i) => (
              <input
                key={i}
                type="url"
                value={url}
                onChange={e => {
                  const u = [...competitorUrls]; u[i] = e.target.value; setCompetitorUrls(u)
                }}
                placeholder={`https://competitor${i + 1}.com/page`}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                disabled={isRunning}
              />
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-400">
            ARIA checks load speed, CTA placement, price visibility, trust signals, and competitor comparison.
          </p>
          <button
            onClick={handleStartAudit}
            disabled={isRunning || !brandUrl.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60 transition-colors"
          >
            {isRunning
              ? <><Loader2 className="h-4 w-4 animate-spin" /> Auditing…</>
              : <><Zap className="h-4 w-4" /> Run Audit</>}
          </button>
        </div>
      </div>

      {/* Progress */}
      {isRunning && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5">
          <div className="flex items-center gap-3 mb-3">
            <Loader2 className="h-5 w-5 text-indigo-600 animate-spin" />
            <div>
              <p className="text-sm font-semibold text-indigo-900">ARIA is auditing your landing page…</p>
              <p className="text-xs text-indigo-600">Checking load speed, CTAs, pricing, trust signals, competitor pages — takes 20–40 seconds</p>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs text-indigo-700">
            {['Fetching page content', 'Analysing CTAs & pricing', 'Auditing competitors', 'ARIA recommendations'].map((s, i) => (
              <div key={i} className="flex items-center gap-1.5 rounded-lg bg-indigo-100 px-2.5 py-1.5">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: `${i * 0.3}s` }} />
                {s}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-center gap-2 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {/* Results */}
      {result && !isRunning && (
        <div className="space-y-6">

          {/* Summary bar */}
          <div className="rounded-xl border bg-white p-4">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-4">
                <div className={cn('flex h-16 w-16 flex-col items-center justify-center rounded-xl text-2xl font-black', gradeColor(result.summary.our_grade))}>
                  {result.summary.our_grade}
                  <span className="text-[10px] font-semibold">{result.summary.our_score}/100</span>
                </div>
                <div>
                  <p className="text-base font-bold text-gray-900">Your Landing Page Score</p>
                  <p className="text-sm text-gray-500">
                    Load: {result.summary.our_load_ms ? `${(result.summary.our_load_ms / 1000).toFixed(1)}s` : '—'} ·
                    CTAs: {result.summary.our_cta_count} ·
                    Price: {result.summary.our_price_visible ? '✓ Visible' : '✗ Hidden'}
                  </p>
                  {result.summary.top_issue && (
                    <p className="text-xs text-red-600 mt-0.5 flex items-center gap-1">
                      <AlertTriangle className="h-3 w-3" /> {result.summary.top_issue}
                    </p>
                  )}
                </div>
              </div>

              {/* Conversion winner */}
              {result.conversion_analysis?.winner_name && (
                <div className="rounded-xl border border-green-200 bg-green-50 px-4 py-3 max-w-xs">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-green-700 mb-1">
                    Conversion Winner ({result.conversion_analysis.confidence} confidence)
                  </p>
                  <p className="text-sm font-bold text-green-800">{result.conversion_analysis.winner_name}</p>
                  <p className="text-xs text-green-700 mt-0.5">{result.conversion_analysis.conversion_verdict}</p>
                </div>
              )}
            </div>

            {/* Key insight */}
            {result.conversion_analysis?.key_insight && (
              <div className="mt-4 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
                <p className="text-[10px] font-bold uppercase tracking-wide text-amber-700 mb-1">Key Insight</p>
                <p className="text-sm text-amber-900">{result.conversion_analysis.key_insight}</p>
              </div>
            )}
          </div>

          {/* Site cards grid */}
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">
              Page-by-Page Breakdown
            </p>
            <div className={cn('grid gap-4', result.competitors.length > 0 ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3' : 'grid-cols-1 md:grid-cols-2')}>
              <SiteScoreCard site={result.our_site} isOurs={true} />
              {result.competitors.map((comp, i) => (
                <SiteScoreCard key={i} site={comp} isOurs={false} />
              ))}
            </div>
          </div>

          {/* Competitor verdicts */}
          {result.conversion_analysis?.site_verdicts && result.conversion_analysis.site_verdicts.length > 1 && (
            <div className="rounded-xl border bg-white p-5">
              <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">
                ARIA Verdict — All Sites
              </p>
              <div className="space-y-2">
                {result.conversion_analysis.site_verdicts.map((v, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-lg bg-gray-50 px-4 py-3">
                    <span className="text-xs font-bold text-gray-600 min-w-[90px]">{v.name}</span>
                    <div className="flex-1 text-xs text-gray-600">{v.verdict}</div>
                    {v.biggest_fix && (
                      <div className="text-xs text-red-600 flex items-center gap-1 shrink-0">
                        <ArrowRight className="h-3 w-3" /> {v.biggest_fix}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="text-center">
            <button
              onClick={handleStartAudit}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              <RefreshCw className="h-4 w-4" /> Re-run audit
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!result && !isRunning && !error && (
        <div className="rounded-xl border bg-white p-12 text-center">
          <Layout className="h-12 w-12 text-gray-200 mx-auto mb-4" />
          <h3 className="text-base font-semibold text-gray-700 mb-2">Audit your landing page</h3>
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Enter your landing page URL above. ARIA will score it on 6 conversion signals, compare it against competitors,
            and give ARIA-powered recommendations to improve conversion rate from paid ads.
          </p>
          <div className="mt-6 grid grid-cols-3 gap-3 max-w-lg mx-auto text-xs text-left">
            {[
              { icon: Clock, label: 'Load Speed', desc: 'Target <3s for paid traffic' },
              { icon: Target, label: 'CTA Quality', desc: 'Count, placement, clarity' },
              { icon: TrendingUp, label: 'Price Visibility', desc: 'Is pricing above the fold?' },
              { icon: Star, label: 'Social Proof', desc: 'Reviews, ratings, UGC' },
              { icon: Shield, label: 'Trust Signals', desc: 'Guarantees, certifications' },
              { icon: Globe, label: 'Competitor Benchmark', desc: 'Side-by-side vs rivals' },
            ].map(({ icon: Icon, label, desc }) => (
              <div key={label} className="rounded-lg bg-gray-50 p-3">
                <Icon className="h-4 w-4 text-indigo-500 mb-1" />
                <p className="font-semibold text-gray-700">{label}</p>
                <p className="text-gray-400">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
