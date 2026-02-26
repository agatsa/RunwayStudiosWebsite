'use server'
import Link from 'next/link'
import {
  Layers, Users, Eye, Search, ShoppingCart, CreditCard,
  RefreshCw, ArrowUpRight, ArrowDown, TrendingUp,
} from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'

interface PageProps { searchParams: { ws?: string } }

function fmt(n: number | null | undefined, prefix = '') {
  if (n == null || isNaN(n)) return '—'
  if (n >= 1_000_000) return `${prefix}${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function fmtInr(n: number | null | undefined) {
  if (n == null || isNaN(n)) return '—'
  if (n >= 100_000) return `₹${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(0)}K`
  return `₹${n.toFixed(0)}`
}

async function fetchPageData(workspaceId: string) {
  const safe = (p: Promise<Response>) =>
    p.then(r => r.ok ? r.json() : null).catch(() => null)

  const [kpi, ga4Status, ga4Overview, ga4Traffic, youtube, connections] = await Promise.all([
    safe(fetchFromFastAPI(`/kpi/summary?workspace_id=${workspaceId}&days=30`)),
    safe(fetchFromFastAPI(`/ga4/status?workspace_id=${workspaceId}`)),
    safe(fetchFromFastAPI(`/ga4/overview?workspace_id=${workspaceId}&days=30`)),
    safe(fetchFromFastAPI(`/ga4/traffic-sources?workspace_id=${workspaceId}&days=30`)),
    safe(fetchFromFastAPI(`/youtube/channel-stats?workspace_id=${workspaceId}`)),
    safe(fetchFromFastAPI(`/settings/connections?workspace_id=${workspaceId}`)),
  ])

  return { kpi, ga4Status, ga4Overview, ga4Traffic, youtube, connections }
}

export default async function AwarenessFunnelPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const data = workspaceId
    ? await fetchPageData(workspaceId)
    : { kpi: null, ga4Status: null, ga4Overview: null, ga4Traffic: null, youtube: null, connections: null }

  const { kpi, ga4Status, ga4Overview, ga4Traffic, youtube, connections } = data

  // Connection status
  const ga4Connected = !!(ga4Status?.connected && ga4Status?.has_property)
  const ytConnected = !!(youtube?.channel?.channel_id)
  const metaConnected = !!(connections?.connections?.find((c: any) => c.platform === 'meta' && c.has_token))
  const googleConnected = !!(connections?.connections?.find((c: any) => c.platform === 'google' && c.has_token))
  const anyConnected = ga4Connected || ytConnected || metaConnected || googleConnected

  // Paid channel metrics (Meta + Google KPI upload data)
  const totalImpressions = kpi?.summary?.impressions ?? kpi?.impressions ?? null
  const totalClicks = kpi?.summary?.clicks ?? kpi?.clicks ?? null
  const totalSpend = kpi?.summary?.spend ?? kpi?.total_spend ?? null
  const totalConversions = kpi?.summary?.conversions ?? kpi?.total_conversions ?? null
  const totalRevenue = kpi?.summary?.revenue ?? kpi?.total_revenue ?? null
  const blendedCac = kpi?.blended_cac ?? (totalSpend && totalConversions && totalConversions > 0 ? totalSpend / totalConversions : null)
  const blendedRoas = kpi?.blended_roas ?? (totalRevenue && totalSpend && totalSpend > 0 ? totalRevenue / totalSpend : null)
  const metaSpend = kpi?.summary?.platform_breakdown?.meta?.spend ?? null
  const googleSpend = kpi?.summary?.platform_breakdown?.google?.spend ?? null

  // GA4 metrics
  const sessions = ga4Overview?.sessions ?? null
  const users = ga4Overview?.users ?? null
  const ga4Conv = ga4Overview?.conversions ?? null
  const ga4Revenue = ga4Overview?.revenue ?? null
  const bounceRate = ga4Overview?.bounce_rate ?? null

  // Traffic sources from GA4
  const sources: { source_medium: string; sessions: number; conversions: number; revenue: number }[] =
    ga4Traffic?.sources ?? []
  const organicSessions = sources
    .filter(s => s.source_medium.includes('organic') || s.source_medium.includes('(none)'))
    .reduce((a, s) => a + s.sessions, 0) || null
  const paidSessions = sources
    .filter(s => s.source_medium.includes('cpc') || s.source_medium.includes('paid') || s.source_medium.includes('ppc'))
    .reduce((a, s) => a + s.sessions, 0) || null
  const directSessions = sources
    .filter(s => s.source_medium.includes('direct'))
    .reduce((a, s) => a + s.sessions, 0) || null

  // YouTube — response shape: { channel: { view_count, subscriber_count }, daily: [...] }
  const ytSubscribers = youtube?.channel?.subscriber_count ?? null
  const ytViews30d = (youtube?.daily as any[] | null)?.reduce((s: number, d: any) => s + (d.views ?? 0), 0) ?? null
  const ytViews = ytViews30d || youtube?.channel?.view_count || null

  // Conversion rate
  const cvr = sessions && ga4Conv ? ((ga4Conv / sessions) * 100) : null
  const ctr = totalImpressions && totalClicks ? ((totalClicks / totalImpressions) * 100) : null

  // Funnel stages with real data
  const funnelStages = [
    {
      num: 1,
      label: 'UNAWARE',
      desc: "Doesn't know the problem exists",
      icon: Eye,
      color: 'bg-slate-50 border-slate-200 text-slate-700',
      barColor: 'bg-slate-400',
      channels: [
        { name: 'YouTube Organic', connected: ytConnected },
        { name: 'Meta Reach Ads', connected: metaConnected },
        { name: 'PR / Influencers', connected: false },
      ],
      metrics: [
        { label: 'YT Views (30d)', value: fmt(ytViews) },
        { label: 'Paid Impressions', value: fmt(totalImpressions) },
        { label: 'YT Subscribers', value: fmt(ytSubscribers) },
      ],
      primaryValue: totalImpressions ?? ytViews,
      primaryLabel: totalImpressions ? 'Impressions' : 'YT Views',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
    {
      num: 2,
      label: 'PROBLEM AWARE',
      desc: 'Knows they have a problem, not the solution',
      icon: Search,
      color: 'bg-blue-50 border-blue-200 text-blue-700',
      barColor: 'bg-blue-400',
      channels: [
        { name: 'YouTube Educational', connected: ytConnected },
        { name: 'SEO / Blog', connected: ga4Connected },
        { name: 'Meta Awareness', connected: metaConnected },
      ],
      metrics: [
        { label: 'Organic Sessions', value: fmt(organicSessions) },
        { label: 'Total Clicks (paid)', value: fmt(totalClicks) },
        { label: 'Bounce Rate', value: bounceRate ? `${bounceRate.toFixed(0)}%` : '—' },
      ],
      primaryValue: (organicSessions ?? 0) + (totalClicks ?? 0) || null,
      primaryLabel: 'Organic + Clicks',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
    {
      num: 3,
      label: 'SOLUTION AWARE',
      desc: 'Knows solutions exist, not your brand',
      icon: Search,
      color: 'bg-indigo-50 border-indigo-200 text-indigo-700',
      barColor: 'bg-indigo-400',
      channels: [
        { name: 'Google Search (generic)', connected: googleConnected },
        { name: 'YouTube Ads', connected: ytConnected && googleConnected },
        { name: 'Meta Retargeting', connected: metaConnected },
      ],
      metrics: [
        { label: 'Paid Sessions', value: fmt(paidSessions) },
        { label: 'Total Sessions', value: fmt(sessions) },
        { label: 'CTR', value: ctr ? `${ctr.toFixed(1)}%` : '—' },
      ],
      primaryValue: sessions,
      primaryLabel: 'Total Sessions',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
    {
      num: 4,
      label: 'PRODUCT AWARE',
      desc: "Knows your product, hasn't bought",
      icon: ShoppingCart,
      color: 'bg-purple-50 border-purple-200 text-purple-700',
      barColor: 'bg-purple-400',
      channels: [
        { name: 'Google Brand Search', connected: googleConnected },
        { name: 'YouTube Remarketing', connected: ytConnected },
        { name: 'Meta Dynamic Ads', connected: metaConnected },
      ],
      metrics: [
        { label: 'Direct Sessions', value: fmt(directSessions) },
        { label: 'Google Spend', value: fmtInr(googleSpend) },
        { label: 'Meta Spend', value: fmtInr(metaSpend) },
      ],
      primaryValue: directSessions,
      primaryLabel: 'Direct Sessions',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
    {
      num: 5,
      label: 'MOST AWARE',
      desc: 'Ready to buy — needs the right offer',
      icon: CreditCard,
      color: 'bg-green-50 border-green-200 text-green-700',
      barColor: 'bg-green-500',
      channels: [
        { name: 'Brand + Intent Search', connected: googleConnected },
        { name: 'Cart Abandon / WhatsApp', connected: false },
        { name: 'GA4 Conversion Tracking', connected: ga4Connected },
      ],
      metrics: [
        { label: 'Conversions', value: fmt(ga4Conv ?? totalConversions) },
        { label: 'Conv. Rate', value: cvr ? `${cvr.toFixed(1)}%` : '—' },
        { label: 'CPA', value: fmtInr(blendedCac) },
      ],
      primaryValue: ga4Conv ?? totalConversions,
      primaryLabel: 'Conversions',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
    {
      num: 6,
      label: 'LOYAL CUSTOMER',
      desc: 'Post-purchase — maximise LTV',
      icon: RefreshCw,
      color: 'bg-orange-50 border-orange-200 text-orange-700',
      barColor: 'bg-orange-400',
      channels: [
        { name: 'Email / WhatsApp', connected: false },
        { name: 'YouTube (usage content)', connected: ytConnected },
        { name: 'Repeat Purchase Tracking', connected: ga4Connected },
      ],
      metrics: [
        { label: 'Revenue (30d)', value: fmtInr(ga4Revenue ?? totalRevenue) },
        { label: 'Blended ROAS', value: blendedRoas ? `${blendedRoas.toFixed(2)}x` : '—' },
        { label: 'Total Spend', value: fmtInr(totalSpend) },
      ],
      primaryValue: ga4Revenue ?? totalRevenue,
      primaryLabel: 'Revenue',
      maxValue: totalImpressions ?? ytViews ?? 1,
    },
  ]

  // Compute funnel drop-off rows
  const funnelFlow = [
    { label: 'Ad Impressions', value: totalImpressions, color: 'bg-slate-400' },
    { label: 'Ad Clicks', value: totalClicks, color: 'bg-blue-400' },
    { label: 'Site Sessions (GA4)', value: sessions, color: 'bg-indigo-400' },
    { label: 'Conversions', value: ga4Conv ?? totalConversions, color: 'bg-green-500' },
  ].filter(r => r.value != null && r.value > 0)

  const maxFunnelVal = funnelFlow[0]?.value ?? 1

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-600">
            <Layers className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Awareness Funnel</h1>
            <p className="text-sm text-gray-500">Where in the buyer journey is each channel performing — and where is the leak?</p>
          </div>
        </div>
        <Link
          href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700"
        >
          Manage Channels <ArrowUpRight className="h-3 w-3" />
        </Link>
      </div>

      {/* Channel Connection Status */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { name: 'Meta Ads', connected: metaConnected, color: 'blue' },
          { name: 'Google Ads', connected: googleConnected, color: 'green' },
          { name: 'YouTube', connected: ytConnected, color: 'red' },
          { name: 'Google Analytics 4', connected: ga4Connected, color: 'orange' },
        ].map(ch => (
          <div
            key={ch.name}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-xs font-medium ${
              ch.connected
                ? 'border-green-200 bg-green-50 text-green-700'
                : 'border-gray-200 bg-gray-50 text-gray-400'
            }`}
          >
            <span className={`h-2 w-2 rounded-full shrink-0 ${ch.connected ? 'bg-green-500' : 'bg-gray-300'}`} />
            {ch.name}
          </div>
        ))}
      </div>

      {/* Real Conversion Funnel — only show if any data */}
      {funnelFlow.length >= 2 && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
            <p className="text-sm font-semibold text-gray-700">Live Conversion Funnel — Last 30 Days</p>
            <p className="text-xs text-gray-400">From ad impression to purchase · real data from connected channels</p>
          </div>
          <div className="p-5 space-y-3">
            {funnelFlow.map((row, i) => {
              const pct = Math.max(1, Math.round((row.value! / maxFunnelVal) * 100))
              const dropPct = i > 0 && funnelFlow[i - 1].value
                ? Math.round((1 - row.value! / funnelFlow[i - 1].value!) * 100)
                : null
              return (
                <div key={row.label}>
                  {dropPct !== null && dropPct > 0 && (
                    <div className="flex items-center gap-1 text-[10px] text-red-500 mb-1 pl-1">
                      <ArrowDown className="h-3 w-3" />
                      {dropPct}% drop-off at this stage
                    </div>
                  )}
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">{row.label}</span>
                    <span className="font-bold text-gray-900">{fmt(row.value)}</span>
                  </div>
                  <div className="h-6 w-full rounded bg-gray-100">
                    <div className={`h-6 rounded ${row.color}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 6-Stage Buyer Journey */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
          <p className="text-sm font-semibold text-gray-700">6-Stage Buyer Journey</p>
          <p className="text-xs text-gray-400">Each stage mapped to your connected channels and real metrics</p>
        </div>
        <div className="p-4 space-y-3">
          {funnelStages.map(stage => {
            const hasData = stage.primaryValue != null && stage.primaryValue > 0
            const barPct = stage.maxValue && stage.primaryValue
              ? Math.max(2, Math.round((stage.primaryValue / stage.maxValue) * 100))
              : 0
            const connectedCount = stage.channels.filter(c => c.connected).length

            return (
              <div key={stage.num} className={`rounded-xl border p-4 ${stage.color}`}>
                <div className="flex items-start gap-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/70 text-sm font-bold">
                    {stage.num}
                  </div>
                  <div className="flex-1 min-w-0">
                    {/* Stage header */}
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-xs font-bold uppercase tracking-wide">{stage.label}</p>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] opacity-70">{connectedCount}/{stage.channels.length} channels connected</span>
                        {hasData && (
                          <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-bold">
                            {fmt(stage.primaryValue)} {stage.primaryLabel}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-xs mb-2 opacity-80">{stage.desc}</p>

                    {/* Bar */}
                    {hasData ? (
                      <div className="h-2 w-full rounded-full bg-white/50 mb-3">
                        <div className={`h-2 rounded-full ${stage.barColor}`} style={{ width: `${barPct}%` }} />
                      </div>
                    ) : (
                      <div className="h-2 w-full rounded-full bg-white/30 mb-3" />
                    )}

                    {/* Channels + Metrics grid */}
                    <div className="grid grid-cols-2 gap-3 text-[10px]">
                      <div>
                        <p className="font-semibold mb-1 opacity-70">Channels</p>
                        {stage.channels.map(c => (
                          <p key={c.name} className={`flex items-center gap-1 ${c.connected ? 'opacity-100 font-medium' : 'opacity-50'}`}>
                            <span className={`inline-block h-1.5 w-1.5 rounded-full ${c.connected ? stage.barColor : 'bg-gray-300'}`} />
                            {c.name}
                          </p>
                        ))}
                      </div>
                      <div>
                        <p className="font-semibold mb-1 opacity-70">Live Metrics</p>
                        {stage.metrics.map(m => (
                          <p key={m.label} className="flex items-center justify-between gap-1">
                            <span className="opacity-70">{m.label}</span>
                            <span className={`font-bold ${m.value === '—' ? 'text-gray-300' : ''}`}>{m.value}</span>
                          </p>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Blended North Star Metrics */}
      <div className="rounded-xl border border-violet-200 bg-violet-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="h-5 w-5 text-violet-600" />
          <p className="text-sm font-bold text-gray-900">North Star Metrics — Last 30 Days</p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Blended CAC', value: fmtInr(blendedCac), sub: 'cost per acquisition', color: 'text-violet-600' },
            { label: 'Blended ROAS', value: blendedRoas ? `${blendedRoas.toFixed(2)}x` : '—', sub: 'return on ad spend', color: 'text-green-600' },
            { label: 'Total Conversions', value: fmt(ga4Conv ?? totalConversions), sub: 'purchases / leads', color: 'text-blue-600' },
            { label: 'Total Revenue', value: fmtInr(ga4Revenue ?? totalRevenue), sub: 'tracked revenue', color: 'text-emerald-600' },
          ].map(m => (
            <div key={m.label} className="rounded-lg bg-white p-3 text-center">
              <p className="text-[10px] text-gray-500 mb-1">{m.label}</p>
              <p className={`text-lg font-bold ${m.value === '—' ? 'text-gray-300' : m.color}`}>{m.value}</p>
              <p className="text-[9px] text-gray-400 mt-0.5">{m.sub}</p>
            </div>
          ))}
        </div>
        {!anyConnected && (
          <p className="mt-3 text-center text-xs text-gray-400">
            Connect Meta, Google Ads, YouTube and GA4 to populate all metrics →{' '}
            <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'} className="text-violet-600 underline">
              Settings
            </Link>
          </p>
        )}
        {anyConnected && !blendedCac && (
          <p className="mt-3 text-center text-xs text-gray-400">
            Upload campaign data (Excel) or connect live API to see CAC / ROAS →{' '}
            <Link href={workspaceId ? `/campaigns?ws=${workspaceId}` : '/campaigns'} className="text-violet-600 underline">
              Meta Ads
            </Link>
          </p>
        )}
      </div>
    </div>
  )
}
