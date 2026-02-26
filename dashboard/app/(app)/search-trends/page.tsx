import { TrendingUp, Search, MapPin, Lightbulb, AlertTriangle, MinusCircle, ArrowUpRight } from 'lucide-react'
import Link from 'next/link'
import { fetchFromFastAPI } from '@/lib/api'
import { formatINR } from '@/lib/utils'

interface PageProps { searchParams: { ws?: string } }

interface TrendTerm {
  term: string
  volume: number
  spend: number
  ctr: number
  growth_pct: number
  signal: 'breakout' | 'up' | 'stable' | 'down'
  conversions: number
}

interface TrendsData {
  has_data: boolean
  terms: TrendTerm[]
  rising: TrendTerm[]
  wasted: TrendTerm[]
}

interface TrafficSource {
  source_medium: string
  sessions: number
  conversions: number
  revenue: number
}

async function fetchPageData(workspaceId: string) {
  const safe = (p: Promise<Response>) =>
    p.then(r => r.ok ? r.json() : null).catch(() => null)

  const [trends, ga4Status, ga4Traffic, ga4Overview, ga4Landing] = await Promise.all([
    safe(fetchFromFastAPI(`/search-trends?workspace_id=${workspaceId}&days=90`)),
    safe(fetchFromFastAPI(`/ga4/status?workspace_id=${workspaceId}`)),
    safe(fetchFromFastAPI(`/ga4/traffic-sources?workspace_id=${workspaceId}&days=30`)),
    safe(fetchFromFastAPI(`/ga4/overview?workspace_id=${workspaceId}&days=30`)),
    safe(fetchFromFastAPI(`/ga4/landing-pages?workspace_id=${workspaceId}&days=30`)),
  ])

  return { trends, ga4Status, ga4Traffic, ga4Overview, ga4Landing }
}

function SignalBadge({ signal }: { signal: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    breakout: { label: '⚡ Breakout', cls: 'bg-orange-100 text-orange-700' },
    up: { label: '↑ Rising', cls: 'bg-green-100 text-green-700' },
    stable: { label: '→ Stable', cls: 'bg-gray-100 text-gray-600' },
    down: { label: '↓ Declining', cls: 'bg-red-100 text-red-700' },
  }
  const s = map[signal] ?? map.stable
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>
  )
}

export default async function SearchTrendsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const { trends, ga4Status, ga4Traffic, ga4Overview, ga4Landing } = workspaceId
    ? await fetchPageData(workspaceId)
    : { trends: null, ga4Status: null, ga4Traffic: null, ga4Overview: null, ga4Landing: null }

  const hasSearchTermData = trends?.has_data === true
  const ga4Connected = !!(ga4Status?.connected && ga4Status?.has_property)

  // GA4 traffic sources breakdown
  const sources: TrafficSource[] = ga4Traffic?.sources ?? []
  const organicSources = sources.filter(s =>
    s.source_medium.includes('organic') || s.source_medium.includes('(none)')
  )
  const paidSources = sources.filter(s =>
    s.source_medium.includes('cpc') || s.source_medium.includes('paid') || s.source_medium.includes('ppc')
  )
  const totalSessions = ga4Overview?.sessions ?? null
  const organicTotal = organicSources.reduce((a, s) => a + s.sessions, 0)
  const paidTotal = paidSources.reduce((a, s) => a + s.sessions, 0)
  const organicConversions = organicSources.reduce((a, s) => a + s.conversions, 0)
  const organicPct = totalSessions && organicTotal ? Math.round(organicTotal / totalSessions * 100) : null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-600">
            <TrendingUp className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Search Trends</h1>
            <p className="text-sm text-gray-500">Organic search performance + keyword growth signals from your ad data</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {ga4Connected && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
              <span className="h-1.5 w-1.5 rounded-full bg-green-500" />GA4 Live
            </span>
          )}
          {hasSearchTermData && (
            <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-700">
              {trends!.terms.length} keywords
            </span>
          )}
        </div>
      </div>

      {/* GA4 Organic Search Overview — shows whenever GA4 is connected */}
      {ga4Connected && sources.length > 0 && (
        <>
          {/* KPI bar */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Organic Sessions', value: organicTotal.toLocaleString('en-IN'), sub: 'last 30 days', color: 'text-emerald-600' },
              { label: 'Paid Sessions', value: paidTotal.toLocaleString('en-IN'), sub: 'last 30 days', color: 'text-blue-600' },
              { label: 'Organic Conv.', value: organicConversions.toLocaleString('en-IN'), sub: 'from organic traffic', color: 'text-green-600' },
              { label: 'Organic Share', value: organicPct != null ? `${organicPct}%` : '—', sub: 'of total sessions', color: 'text-violet-600' },
            ].map(m => (
              <div key={m.label} className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs text-gray-500 mb-1">{m.label}</p>
                <p className={`text-xl font-bold ${m.color}`}>{m.value}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{m.sub}</p>
              </div>
            ))}
          </div>

          {/* Traffic Sources Table */}
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-700">Traffic Sources — Last 30 Days</h2>
              <span className="text-xs text-gray-400">GA4 · top {sources.length} sources</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                    <th className="px-4 py-3 font-medium">Source / Medium</th>
                    <th className="px-4 py-3 font-medium text-right">Sessions</th>
                    <th className="px-4 py-3 font-medium text-right">Conv.</th>
                    <th className="px-4 py-3 font-medium text-right">Conv. Rate</th>
                    <th className="px-4 py-3 font-medium text-right">Revenue</th>
                    <th className="px-4 py-3 font-medium">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.slice(0, 20).map((s, i) => {
                    const isOrganic = s.source_medium.includes('organic') || s.source_medium.includes('(none)')
                    const isPaid = s.source_medium.includes('cpc') || s.source_medium.includes('paid')
                    const cvr = s.sessions > 0 ? (s.conversions / s.sessions * 100) : 0
                    return (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-800 max-w-[200px]">
                          <span className="block truncate">{s.source_medium}</span>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">{s.sessions.toLocaleString('en-IN')}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{s.conversions.toLocaleString('en-IN')}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{cvr.toFixed(1)}%</td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {s.revenue > 0 ? formatINR(s.revenue) : '—'}
                        </td>
                        <td className="px-4 py-3">
                          {isOrganic ? (
                            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">Organic</span>
                          ) : isPaid ? (
                            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">Paid</span>
                          ) : (
                            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">Other</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Google Ads Keyword Data */}
      {hasSearchTermData ? (
        <>
          {/* Rising Terms */}
          {trends!.rising.length > 0 && (
            <div className="rounded-xl border border-gray-200 overflow-hidden">
              <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700">Rising Search Terms</h2>
                <span className="text-xs text-gray-400">Last 30 days vs. prior 30 days · Google Ads data</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                      <th className="px-4 py-3 font-medium">Search Term</th>
                      <th className="px-4 py-3 font-medium text-right">Clicks</th>
                      <th className="px-4 py-3 font-medium text-right">Spend</th>
                      <th className="px-4 py-3 font-medium text-right">CTR</th>
                      <th className="px-4 py-3 font-medium text-right">Growth</th>
                      <th className="px-4 py-3 font-medium">Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(trends!.rising as TrendTerm[]).slice(0, 20).map((t, i) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-800 max-w-[200px]">
                          <span className="block truncate">{t.term}</span>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">{t.volume.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{formatINR(t.spend)}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{t.ctr.toFixed(2)}%</td>
                        <td className="px-4 py-3 text-right font-semibold text-green-600">
                          {t.growth_pct >= 9999 ? 'New' : `+${t.growth_pct.toFixed(0)}%`}
                        </td>
                        <td className="px-4 py-3"><SignalBadge signal={t.signal} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Wasted spend */}
          {trends!.wasted.length > 0 && (
            <div className="rounded-xl border border-red-200 overflow-hidden">
              <div className="bg-red-50 px-4 py-3 border-b border-red-200 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-500" />
                <h2 className="text-sm font-semibold text-gray-700">High Spend / Zero Conversions</h2>
                <span className="ml-auto text-xs text-gray-400">Add as negative keywords</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-red-100 text-left text-xs text-gray-500">
                      <th className="px-4 py-3 font-medium">Search Term</th>
                      <th className="px-4 py-3 font-medium text-right">Spend</th>
                      <th className="px-4 py-3 font-medium text-right">Clicks</th>
                      <th className="px-4 py-3 font-medium text-right">Conv</th>
                      <th className="px-4 py-3 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(trends!.wasted as TrendTerm[]).slice(0, 15).map((t, i) => (
                      <tr key={i} className="border-b border-red-50 bg-red-50/30 hover:bg-red-50">
                        <td className="px-4 py-3 font-medium text-red-800 max-w-[200px]">
                          <span className="block truncate">{t.term}</span>
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-red-700">{formatINR(t.spend)}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{t.volume.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right text-gray-400">0</td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
                            <MinusCircle className="h-3 w-3" /> Negative KW
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* All terms */}
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-700">All Search Terms</h2>
              <span className="text-xs text-gray-400">{trends!.terms.length} terms · 90 days · Google Ads</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                    <th className="px-4 py-3 font-medium">Search Term</th>
                    <th className="px-4 py-3 font-medium text-right">Clicks</th>
                    <th className="px-4 py-3 font-medium text-right">Spend</th>
                    <th className="px-4 py-3 font-medium text-right">Conv</th>
                    <th className="px-4 py-3 font-medium">Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {(trends!.terms as TrendTerm[]).slice(0, 50).map((t, i) => (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-800 max-w-[220px]">
                        <span className="block truncate">{t.term}</span>
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">{t.volume.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{formatINR(t.spend)}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{t.conversions}</td>
                      <td className="px-4 py-3"><SignalBadge signal={t.signal} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        /* No Google Ads keyword data — show landing pages as keyword intent proxy */
        <>
          {/* GA4 Landing Pages as Organic Keyword Intent */}
          {ga4Connected && ga4Landing?.landing_pages?.length > 0 && (
            <div className="rounded-xl border border-gray-200 overflow-hidden">
              <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-gray-700">Top Landing Pages — Organic Keyword Intent</h2>
                  <p className="text-xs text-gray-400 mt-0.5">Pages people land on from search engines reveal what they searched for · GA4 · Last 30 days</p>
                </div>
                <span className="text-xs text-gray-400">{ga4Landing.landing_pages.length} pages</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                      <th className="px-4 py-3 font-medium">Landing Page</th>
                      <th className="px-4 py-3 font-medium text-right">Sessions</th>
                      <th className="px-4 py-3 font-medium text-right">Bounce Rate</th>
                      <th className="px-4 py-3 font-medium text-right">Conversions</th>
                      <th className="px-4 py-3 font-medium text-right">Drop-off</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ga4Landing.landing_pages.slice(0, 25).map((p: { page_path: string; sessions: number; bounce_rate: number; conversions: number; drop_off_pct: number }, i: number) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-800 max-w-[260px]">
                          <span className="block truncate text-xs" title={p.page_path}>{p.page_path}</span>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">{p.sessions.toLocaleString('en-IN')}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{p.bounce_rate}%</td>
                        <td className="px-4 py-3 text-right text-gray-600">{p.conversions}</td>
                        <td className="px-4 py-3 text-right">
                          <span className={`font-semibold text-xs ${p.drop_off_pct >= 70 ? 'text-red-600' : p.drop_off_pct >= 50 ? 'text-amber-600' : 'text-green-600'}`}>
                            {p.drop_off_pct}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Small inline nudge to upload keyword data */}
          <div className="flex items-center gap-3 rounded-xl border border-dashed border-gray-200 px-4 py-3">
            <Search className="h-4 w-4 text-gray-400 shrink-0" />
            <p className="flex-1 text-xs text-gray-500">
              Upload a Google Ads <strong>Search Terms</strong> report to unlock keyword-level growth signals, rising terms and wasted spend alerts.
            </p>
            <Link
              href={workspaceId ? `/google-ads?ws=${workspaceId}` : '/google-ads'}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 shrink-0"
            >
              Upload Report <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
        </>
      )}

      {/* No GA4 CTA */}
      {!ga4Connected && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex items-center gap-4">
          <TrendingUp className="h-5 w-5 text-amber-500 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-gray-900">Connect GA4 for organic search insights</p>
            <p className="text-xs text-gray-600 mt-0.5">See how much traffic comes from Google organic, Bing, direct — and which sources convert best.</p>
          </div>
          <Link
            href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
            className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 shrink-0"
          >
            Connect GA4 <ArrowUpRight className="h-3 w-3" />
          </Link>
        </div>
      )}

      {/* Capability cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-100">
              <TrendingUp className="h-4 w-4 text-orange-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Breakout Keywords ⚡</h3>
          </div>
          <p className="text-xs text-gray-500">
            Terms growing &gt;100% in the last 30 days vs. prior 30 days. Get there before CPCs spike.
            Populated automatically once Google Ads search term reports are uploaded.
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
              <MapPin className="h-4 w-4 text-blue-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Geographic Demand</h3>
          </div>
          <p className="text-xs text-gray-500">
            Upload geo-level Google Ads reports for city-by-city demand signals. Available in the Google Ads reports section.
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-100">
              <AlertTriangle className="h-4 w-4 text-red-500" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Wasted Spend Finder</h3>
          </div>
          <p className="text-xs text-gray-500">
            Automatically flags search terms with high spend and zero conversions.
            Turns them into negative keyword recommendations to stop bleeding budget.
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-yellow-100">
              <Lightbulb className="h-4 w-4 text-yellow-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Content Opportunities</h3>
          </div>
          <p className="text-xs text-gray-500">
            Search terms with high clicks but low CTR are YouTube video opportunities.
            Create content for those exact queries to capture organic traffic for free.
          </p>
        </div>
      </div>
    </div>
  )
}
