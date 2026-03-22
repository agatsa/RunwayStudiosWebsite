'use client'

// Re-export the existing landing pages page content
// The landing-pages page is already a full client component — we render it here
// by forwarding wsId as the workspace search param context

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Layout, RefreshCw, CheckCircle, AlertTriangle, Loader2,
  ExternalLink, ChevronDown, ChevronUp, Globe, Clock,
  Target, TrendingUp, Shield, Star, ArrowRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

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

interface AuditReport {
  workspace_id: string; audited_at: string; cached: boolean
  sites: SiteAudit[]
}

const GRADE_COLOR: Record<string, string> = {
  A: 'bg-green-100  text-green-700',
  B: 'bg-teal-100   text-teal-700',
  C: 'bg-yellow-100 text-yellow-700',
  D: 'bg-orange-100 text-orange-700',
  F: 'bg-red-100    text-red-700',
}

function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const color = grade === 'A' ? '#22c55e' : grade === 'B' ? '#14b8a6' : grade === 'C' ? '#eab308' : grade === 'D' ? '#f97316' : '#ef4444'
  const r = 28, cx = 32, cy = 32
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" className="shrink-0">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#f3f4f6" strokeWidth="6" />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="6"
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
        transform="rotate(-90 32 32)" />
      <text x="50%" y="50%" dominantBaseline="middle" textAnchor="middle"
        fontSize="14" fontWeight="bold" fill={color}>
        {score}
      </text>
    </svg>
  )
}

export default function LandingPageContent({ wsId }: { wsId: string }) {
  const [report, setReport] = useState<AuditReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedSite, setExpandedSite] = useState<string | null>(null)

  const fetchReport = useCallback(async (force = false) => {
    setLoading(true)
    setError(null)
    try {
      if (force) {
        // Trigger new audit, then poll latest
        const startRes = await fetch('/api/lp-audit/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: wsId }),
        })
        if (!startRes.ok) throw new Error(`Start failed: ${startRes.status}`)
        // Wait a moment for the audit to complete (it runs synchronously)
        await new Promise(r => setTimeout(r, 1000))
      }
      const r = await fetch(`/api/lp-audit/latest?workspace_id=${wsId}`)
      if (!r.ok) throw new Error(`${r.status}`)
      setReport(await r.json())
    } catch (e) {
      setError(`Failed to load audit. ${e}`)
    } finally {
      setLoading(false)
    }
  }, [wsId])

  useEffect(() => { fetchReport() }, [fetchReport])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        <p className="text-sm text-gray-500">ARIA is auditing your landing pages...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-100 bg-red-50 p-6 text-center">
        <p className="text-sm text-red-600">{error}</p>
        <button onClick={() => fetchReport()} className="mt-3 text-xs font-medium text-red-600 hover:underline">
          Try again
        </button>
      </div>
    )
  }

  if (!report) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 py-12 px-6 text-center">
        <Layout className="h-8 w-8 text-gray-300" />
        <div>
          <p className="text-sm font-medium text-gray-700">No LP audit yet</p>
          <p className="mt-1 text-xs text-gray-500">Run an audit to see your landing page score and improvement recommendations.</p>
        </div>
        <button
          onClick={() => fetchReport(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          <RefreshCw className="h-4 w-4" />
          Run LP Audit (5 credits)
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Landing Page Audit</h2>
          <p className="text-xs text-gray-400">
            {report.cached ? '⚡ Cached' : '✨ Fresh'} ·{' '}
            {new Date(report.audited_at).toLocaleDateString('en-IN')}
          </p>
        </div>
        <button
          onClick={() => fetchReport(true)}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Re-audit (5 credits)
        </button>
      </div>

      <div className="space-y-3">
        {report.sites.map(site => {
          const expanded = expandedSite === site.url
          return (
            <div key={site.url} className="rounded-xl border border-gray-200 bg-white overflow-hidden">
              {/* Header */}
              <button
                onClick={() => setExpandedSite(expanded ? null : site.url)}
                className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
              >
                <ScoreRing score={site.score} grade={site.grade} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-gray-900 truncate">{site.name}</p>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${GRADE_COLOR[site.grade] ?? 'bg-gray-100 text-gray-600'}`}>
                      Grade {site.grade}
                    </span>
                    {!site.reachable && (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-600">Unreachable</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 truncate mt-0.5">{site.url}</p>
                  <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-500">
                    <span>📱 {site.load_ms_mobile}ms</span>
                    <span>🖥️ {site.load_ms_desktop}ms</span>
                    <span>{site.issues.length} issues</span>
                  </div>
                </div>
                {expanded ? <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" /> : <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />}
              </button>

              {/* Expanded detail */}
              {expanded && (
                <div className="border-t border-gray-100 px-5 py-4 space-y-4">
                  {/* Issues */}
                  {site.issues.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Issues Found</p>
                      <ul className="space-y-1">
                        {site.issues.map((issue, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                            <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 mt-0.5 shrink-0" />
                            {issue}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommendations */}
                  {site.recommendations && site.recommendations.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">ARIA Recommendations</p>
                      <div className="space-y-2">
                        {site.recommendations.map((rec, i) => (
                          <div key={i} className="flex gap-3 rounded-lg border border-gray-100 p-3">
                            <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase shrink-0 mt-0.5 ${
                              rec.priority === 'high' ? 'bg-red-100 text-red-600' :
                              rec.priority === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                              'bg-gray-100 text-gray-600'
                            }`}>
                              {rec.priority}
                            </span>
                            <div>
                              <p className="text-xs font-semibold text-gray-900">{rec.title}</p>
                              <p className="text-xs text-gray-500 mt-0.5">{rec.detail}</p>
                              {rec.impact && (
                                <p className="text-[11px] text-green-600 mt-1">Impact: {rec.impact}</p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
