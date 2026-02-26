import Link from 'next/link'
import { BarChart2, Users, ShoppingCart, DollarSign, Globe, Monitor, Smartphone, Tablet, TrendingUp, TrendingDown, ArrowUpRight } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'

interface PageProps { searchParams: { ws?: string } }

function KpiCard({
  label, value, change, icon: Icon, color,
}: {
  label: string
  value: string
  change?: number | null
  icon: React.ElementType
  color: string
}) {
  const up = change != null && change >= 0
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between mb-2">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${color}`}>
          <Icon className="h-4 w-4 text-white" />
        </div>
        {change != null && (
          <span className={`flex items-center gap-0.5 text-xs font-semibold ${up ? 'text-green-600' : 'text-red-600'}`}>
            {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {Math.abs(change)}%
          </span>
        )}
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

function fmt(n: number | undefined | null): string {
  if (n == null) return '—'
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toLocaleString('en-IN')
}

function fmtDuration(s: number | undefined | null): string {
  if (!s) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m ${sec}s`
}

const DEVICE_ICONS: Record<string, React.ElementType> = {
  desktop: Monitor,
  mobile:  Smartphone,
  tablet:  Tablet,
}

export default async function AnalyticsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  // Fetch GA4 status
  let status: { connected: boolean; property_id?: string; has_property?: boolean } = { connected: false }
  if (workspaceId) {
    try {
      const r = await fetchFromFastAPI(`/ga4/status?workspace_id=${workspaceId}`)
      if (r.ok) status = await r.json()
    } catch { /* no GA4 */ }
  }

  const notConnected = !status.connected || !status.has_property
  // Google is connected but the token predates the analytics.readonly scope addition
  const needsReauth = status.connected && !status.has_property
  const oauthHref = workspaceId
    ? `/api/google/oauth/start?ws=${workspaceId}`
    : '/api/google/oauth/start'

  if (notConnected) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-orange-600">
            <BarChart2 className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Analytics</h1>
            <p className="text-sm text-gray-500">Real-time GA4 data — sessions, conversions, drop-off, geo.</p>
          </div>
        </div>

        <div className="rounded-xl border border-orange-200 bg-orange-50 p-8 text-center">
          <BarChart2 className="h-10 w-10 text-orange-400 mx-auto mb-3" />
          <h2 className="text-base font-semibold text-gray-900 mb-1">
            {needsReauth ? 'Re-authorise Google for GA4 Access' : 'Connect Google Analytics 4'}
          </h2>
          <p className="text-sm text-gray-500 mb-4 max-w-md mx-auto">
            {needsReauth
              ? 'Your Google account is connected but was authorised before GA4 access was added. Click below to re-authorise — it takes 10 seconds and your Google Ads data stays intact.'
              : 'Connect your Google account to pull sessions, conversions, revenue, landing page drop-off, and more.'}
          </p>
          {needsReauth ? (
            <Link
              href={oauthHref}
              className="inline-flex items-center gap-1.5 rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700"
            >
              Re-authorise Google (adds GA4 scope) <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          ) : (
            <Link
              href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
              className="inline-flex items-center gap-1.5 rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700"
            >
              Connect in Settings <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </div>
      </div>
    )
  }

  // Fetch all GA4 data in parallel
  const days = 30
  const [overviewRes, sourcesRes, devicesRes, landingRes, geoRes] = await Promise.allSettled([
    fetchFromFastAPI(`/ga4/overview?workspace_id=${workspaceId}&days=${days}`),
    fetchFromFastAPI(`/ga4/traffic-sources?workspace_id=${workspaceId}&days=${days}`),
    fetchFromFastAPI(`/ga4/devices?workspace_id=${workspaceId}&days=${days}`),
    fetchFromFastAPI(`/ga4/landing-pages?workspace_id=${workspaceId}&days=${days}`),
    fetchFromFastAPI(`/ga4/geo?workspace_id=${workspaceId}&days=${days}`),
  ])

  const overview = overviewRes.status === 'fulfilled' && overviewRes.value.ok
    ? await overviewRes.value.json() : null
  const sources  = sourcesRes.status === 'fulfilled' && sourcesRes.value.ok
    ? (await sourcesRes.value.json()).sources ?? [] : []
  const devices  = devicesRes.status === 'fulfilled' && devicesRes.value.ok
    ? (await devicesRes.value.json()).devices ?? [] : []
  const landing  = landingRes.status === 'fulfilled' && landingRes.value.ok
    ? (await landingRes.value.json()).landing_pages ?? [] : []
  const geo      = geoRes.status === 'fulfilled' && geoRes.value.ok
    ? (await geoRes.value.json()).geo ?? [] : []

  const cur = overview?.current ?? {}
  const pct = overview?.pct_changes ?? {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-orange-600">
            <BarChart2 className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Analytics</h1>
            <p className="text-sm text-gray-500">
              GA4 · Last {days} days
              {status.property_id && <span className="ml-1 text-gray-400">· Property {status.property_id}</span>}
            </p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
          <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
          Connected
        </span>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard label="Sessions"    value={fmt(cur.sessions)}    change={pct.sessions}    icon={BarChart2}    color="bg-blue-500" />
        <KpiCard label="Users"       value={fmt(cur.users)}       change={pct.users}       icon={Users}        color="bg-indigo-500" />
        <KpiCard label="Conversions" value={fmt(cur.conversions)} change={pct.conversions} icon={ShoppingCart} color="bg-green-500" />
        <KpiCard label="Revenue"     value={`₹${fmt(cur.revenue)}`} change={pct.revenue}  icon={DollarSign}   color="bg-orange-500" />
      </div>

      {/* Secondary metrics row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{cur.bounce_rate != null ? `${cur.bounce_rate}%` : '—'}</p>
          <p className="text-xs text-gray-500 mt-0.5">Bounce Rate</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{fmtDuration(cur.avg_session_duration)}</p>
          <p className="text-xs text-gray-500 mt-0.5">Avg. Session</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{fmt(cur.new_users)}</p>
          <p className="text-xs text-gray-500 mt-0.5">New Users</p>
        </div>
      </div>

      {/* Traffic Sources + Devices */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Traffic Sources */}
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="border-b border-gray-100 bg-gray-50 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-700">Traffic Sources</h2>
          </div>
          {sources.length === 0 ? (
            <p className="p-4 text-sm text-gray-400">No data</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50 text-left text-xs text-gray-400">
                  <th className="px-4 py-2 font-medium">Source / Medium</th>
                  <th className="px-4 py-2 text-right font-medium">Sessions</th>
                  <th className="px-4 py-2 text-right font-medium">Conv.</th>
                  <th className="px-4 py-2 text-right font-medium">Revenue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sources.slice(0, 8).map((s: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-700 font-medium">{s.source_medium}</td>
                    <td className="px-4 py-2 text-right text-gray-600">{fmt(s.sessions)}</td>
                    <td className="px-4 py-2 text-right text-gray-600">{fmt(s.conversions)}</td>
                    <td className="px-4 py-2 text-right text-gray-600">₹{fmt(s.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Devices */}
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="border-b border-gray-100 bg-gray-50 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-700">Device Breakdown</h2>
          </div>
          {devices.length === 0 ? (
            <p className="p-4 text-sm text-gray-400">No data</p>
          ) : (
            <div className="p-4 space-y-3">
              {devices.map((d: any, i: number) => {
                const Icon = DEVICE_ICONS[d.device?.toLowerCase()] ?? Monitor
                return (
                  <div key={i} className="flex items-center gap-3">
                    <Icon className="h-4 w-4 shrink-0 text-gray-400" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1 text-xs">
                        <span className="font-medium text-gray-700 capitalize">{d.device}</span>
                        <span className="text-gray-500">{fmt(d.sessions)} sessions · {d.pct_of_total}%</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-gray-100">
                        <div
                          className="h-2 rounded-full bg-blue-400 transition-all"
                          style={{ width: `${d.pct_of_total}%` }}
                        />
                      </div>
                    </div>
                    <span className="text-xs font-medium text-gray-600 w-8 text-right">{fmt(d.conversions)}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Landing Pages with drop-off */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-100 bg-gray-50 px-4 py-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Top Landing Pages — Drop-off</h2>
          <Link
            href={workspaceId ? `/landing-pages?ws=${workspaceId}` : '/landing-pages'}
            className="text-xs text-blue-600 hover:underline"
          >
            Full report →
          </Link>
        </div>
        {landing.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">No landing page data</p>
        ) : (
          <div className="divide-y divide-gray-50">
            {landing.slice(0, 8).map((p: any, i: number) => (
              <div key={i} className="px-4 py-3">
                <div className="flex items-center justify-between mb-1 text-xs">
                  <span className="font-medium text-gray-800 truncate max-w-[55%]" title={p.page_path}>{p.page_path}</span>
                  <span className="flex items-center gap-3 text-gray-500 shrink-0">
                    <span>{fmt(p.sessions)} sessions</span>
                    <span className={`font-semibold ${p.drop_off_pct >= 70 ? 'text-red-600' : p.drop_off_pct >= 50 ? 'text-amber-600' : 'text-green-600'}`}>
                      {p.drop_off_pct}% drop-off
                    </span>
                  </span>
                </div>
                <div className="h-2 w-full rounded-full bg-gray-100">
                  <div
                    className={`h-2 rounded-full transition-all ${p.drop_off_pct >= 70 ? 'bg-red-400' : p.drop_off_pct >= 50 ? 'bg-amber-400' : 'bg-green-400'}`}
                    style={{ width: `${p.drop_off_pct}%` }}
                  />
                </div>
                <div className="flex items-center gap-4 mt-1 text-[10px] text-gray-400">
                  <span>Bounce: {p.bounce_rate}%</span>
                  <span>Avg time: {fmtDuration(p.avg_engagement_time)}</span>
                  <span>Conv: {fmt(p.conversions)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Geo */}
      {geo.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="border-b border-gray-100 bg-gray-50 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
              <Globe className="h-3.5 w-3.5" /> Geographic Breakdown
            </h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-50 text-left text-xs text-gray-400">
                <th className="px-4 py-2 font-medium">Country</th>
                <th className="px-4 py-2 font-medium">City</th>
                <th className="px-4 py-2 text-right font-medium">Sessions</th>
                <th className="px-4 py-2 text-right font-medium">Conv.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {geo.slice(0, 15).map((g: any, i: number) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-700">{g.country}</td>
                  <td className="px-4 py-2 text-gray-500">{g.city}</td>
                  <td className="px-4 py-2 text-right text-gray-600">{fmt(g.sessions)}</td>
                  <td className="px-4 py-2 text-right font-medium text-gray-700">{g.conversions > 0 ? fmt(g.conversions) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
