import Link from 'next/link'
import { Layout, AlertTriangle, Zap, MousePointer, ArrowDown, ArrowUpRight } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'

interface PageProps { searchParams: { ws?: string } }

interface LandingPage {
  page_path: string
  sessions: number
  bounce_rate: number
  avg_engagement_time: number
  conversions: number
  drop_off_pct: number
}

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m ${sec}s`
}

const MOCK_FUNNEL = [
  { label: 'Ad Clicks', count: 1000, pct: 100, drop: null, color: 'bg-blue-500' },
  { label: 'Landed (not bounced)', count: 720, pct: 72, drop: '28% bounced immediately — ad-to-page mismatch?', color: 'bg-blue-400' },
  { label: 'Scrolled 50%+', count: 480, pct: 48, drop: '33% left without scrolling — above-fold weak or slow?', color: 'bg-indigo-400' },
  { label: 'Clicked CTA / Buy Now', count: 310, pct: 31, drop: "35% saw page but didn't click — CTA placement or pricing?", color: 'bg-purple-400' },
  { label: 'Reached Checkout', count: 190, pct: 19, drop: '39% dropped at cart — trust signals missing?', color: 'bg-orange-400' },
  { label: 'Completed Purchase', count: 85, pct: 8.5, drop: '55% dropped at checkout — payment friction / no EMI?', color: 'bg-green-500' },
]

export default async function LandingPagesPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  let landingPages: LandingPage[] = []
  let ga4Connected = false
  let ga4NeedsReauth = false

  if (workspaceId) {
    try {
      const statusRes = await fetchFromFastAPI(`/ga4/status?workspace_id=${workspaceId}`)
      if (statusRes.ok) {
        const status = await statusRes.json()
        ga4Connected = !!(status.connected && status.has_property)
        ga4NeedsReauth = !!(status.connected && !status.has_property)
      }
    } catch { /* ignore */ }

    if (ga4Connected) {
      try {
        const r = await fetchFromFastAPI(`/ga4/landing-pages?workspace_id=${workspaceId}&days=30`)
        if (r.ok) {
          const data = await r.json()
          landingPages = data.landing_pages ?? []
        }
      } catch { /* ignore */ }
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-600">
            <Layout className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Landing Page Intelligence</h1>
            <p className="text-sm text-gray-500">Where does your paid traffic leak? Every drop-off is recoverable revenue.</p>
          </div>
        </div>
        {!ga4Connected && (
          ga4NeedsReauth ? (
            <Link href={workspaceId ? `/api/google/oauth/start?ws=${workspaceId}` : '/api/google/oauth/start'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-orange-300 bg-orange-50 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-100">
              Re-authorise Google for GA4 <ArrowUpRight className="h-3 w-3" />
            </Link>
          ) : (
            <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              Connect GA4 <ArrowUpRight className="h-3 w-3" />
            </Link>
          )
        )}
        {ga4Connected && (
          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
            <span className="h-1.5 w-1.5 rounded-full bg-green-500" />GA4 Connected
          </span>
        )}
      </div>

      {/* Revenue calculator */}
      <div className="rounded-xl border border-orange-200 bg-orange-50 p-4 flex items-center gap-4">
        <AlertTriangle className="h-5 w-5 text-orange-500 shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-gray-900">₹ Lost to Page Performance</p>
          <p className="text-xs text-gray-600 mt-0.5">If your page loads in 4.2s and competitor loads in 1.8s — you're losing ~25% of conversions to pure technical debt. Every 100ms improvement = +1% conversion rate (Google research).</p>
        </div>
        <div className="text-right shrink-0 opacity-50">
          <p className="text-2xl font-bold text-orange-700">₹—</p>
          <p className="text-xs text-gray-500">monthly est. loss</p>
        </div>
      </div>

      {/* Real GA4 landing pages */}
      {ga4Connected && landingPages.length > 0 ? (
        <div>
          <h2 className="mb-3 text-base font-semibold text-gray-900">
            Conversion Funnel Drop-off — Real GA4 Data
          </h2>
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 text-xs text-gray-500">
              Last 30 days · Top landing pages by sessions
            </div>
            <div className="divide-y divide-gray-50">
              {landingPages.map((p, i) => (
                <div key={i} className="px-4 py-4">
                  <div className="flex items-center justify-between mb-2 text-xs">
                    <span className="font-semibold text-gray-800 truncate max-w-[55%]" title={p.page_path}>
                      {p.page_path}
                    </span>
                    <span className="flex items-center gap-4 text-gray-500 shrink-0">
                      <span>{p.sessions.toLocaleString()} sessions</span>
                      <span className={`font-bold ${p.drop_off_pct >= 70 ? 'text-red-600' : p.drop_off_pct >= 50 ? 'text-amber-600' : 'text-green-600'}`}>
                        {p.drop_off_pct}% drop-off
                      </span>
                    </span>
                  </div>
                  <div className="h-5 w-full rounded bg-gray-100 overflow-hidden">
                    <div
                      className={`h-5 rounded transition-all ${p.drop_off_pct >= 70 ? 'bg-red-400' : p.drop_off_pct >= 50 ? 'bg-amber-400' : 'bg-green-400'}`}
                      style={{ width: `${Math.min(p.drop_off_pct, 100)}%` }}
                    />
                  </div>
                  {p.drop_off_pct >= 50 && (
                    <div className="mt-1.5 flex items-center gap-1 text-[10px] text-red-500">
                      <ArrowDown className="h-3 w-3" />
                      High drop-off — bounce rate {p.bounce_rate}% · avg time {fmtDuration(p.avg_engagement_time)} · {p.conversions} conversions
                    </div>
                  )}
                  <div className="flex items-center gap-4 mt-1 text-[10px] text-gray-400">
                    <span>Bounce: {p.bounce_rate}%</span>
                    <span>Avg time on page: {fmtDuration(p.avg_engagement_time)}</span>
                    <span>Conversions: {p.conversions}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* Mock funnel fallback */
        <div>
          <h2 className="mb-3 text-base font-semibold text-gray-900">Conversion Funnel Drop-off Map</h2>
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 text-xs text-gray-500">
              {ga4Connected ? 'No landing page data yet · Traffic may still be building' : 'Connect GA4 to see your real funnel · Preview shown below'}
            </div>
            <div className={`p-5 space-y-3 ${!ga4Connected ? 'opacity-50' : ''}`}>
              {MOCK_FUNNEL.map((step, i) => (
                <div key={i}>
                  <div className="flex items-center justify-between mb-1 text-xs">
                    <span className="font-medium text-gray-700">{step.label}</span>
                    <span className="font-bold text-gray-900">{step.count.toLocaleString()} ({step.pct}%)</span>
                  </div>
                  <div className="h-5 w-full rounded bg-gray-100">
                    <div className={`h-5 rounded ${step.color} transition-all`} style={{ width: `${step.pct}%` }} />
                  </div>
                  {step.drop && (
                    <div className="mt-1 flex items-center gap-1 text-[10px] text-red-500">
                      <ArrowDown className="h-3 w-3" />{step.drop}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 3 capability cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="h-4 w-4 text-yellow-500" />
            <h3 className="text-sm font-semibold text-gray-900">Page Speed Scores</h3>
          </div>
          <p className="text-xs text-gray-500">Core Web Vitals via Google PageSpeed API. LCP, CLS, FID scores with specific improvement recommendations per URL.</p>
          <div className="mt-3 space-y-1.5 opacity-40">
            {[['LCP', '4.2s', 'red'], ['CLS', '0.08', 'green'], ['FID', '120ms', 'yellow']].map(([k,v,c]) => (
              <div key={k} className="flex justify-between text-xs rounded bg-gray-50 px-2 py-1">
                <span className="text-gray-600">{k}</span>
                <span className={`font-bold ${c === 'red' ? 'text-red-600' : c === 'green' ? 'text-green-600' : 'text-yellow-600'}`}>{v}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <MousePointer className="h-4 w-4 text-blue-500" />
            <h3 className="text-sm font-semibold text-gray-900">Scroll Heatmap</h3>
          </div>
          <p className="text-xs text-gray-500">Where do visitors stop scrolling? Identifies the "fold" where most users abandon — so you know exactly where to put your CTA.</p>
          <div className="mt-3 opacity-40">
            {[['0–25%', '100%', 'blue'], ['25–50%', '67%', 'indigo'], ['50–75%', '41%', 'purple'], ['75–100%', '18%', 'gray']].map(([r,p,c]) => (
              <div key={r} className="flex items-center gap-2 mb-1 text-xs">
                <span className="w-16 text-gray-500">{r}</span>
                <div className="flex-1 h-3 rounded bg-gray-100">
                  <div className={`h-3 rounded bg-${c}-300`} style={{ width: p }} />
                </div>
                <span className="w-8 text-right text-gray-600">{p}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Layout className="h-4 w-4 text-green-500" />
            <h3 className="text-sm font-semibold text-gray-900">A/B Test Planner</h3>
          </div>
          <p className="text-xs text-gray-500">Log A/B tests with hypothesis, variant descriptions, and track statistical significance automatically.</p>
          <div className="mt-3 opacity-40 space-y-1.5">
            {[
              { test: 'CTA above fold', status: 'Running', lift: '+12%' },
              { test: 'Price with EMI', status: 'Concluded', lift: '+34%' },
            ].map(t => (
              <div key={t.test} className="rounded bg-gray-50 px-2 py-1.5 text-xs flex justify-between">
                <span className="text-gray-700">{t.test}</span>
                <span className="font-semibold text-green-600">{t.lift}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
