import Link from 'next/link'
import { Send, Clock, TrendingUp, Repeat, BarChart2, ArrowUpRight } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'

interface PageProps { searchParams: { ws?: string } }

interface CampaignSignal {
  name: string
  ctr: number
  clicks: number
  impressions: number
  spend: number
}

interface HourSignal {
  hour: string
  avg_ctr: number
  conversions: number
}

interface SignalsData {
  meta_connected: boolean
  has_meta_data: boolean
  has_timing_data: boolean
  top_campaigns: CampaignSignal[]
  best_hours: HourSignal[]
}

async function getSignals(workspaceId: string): Promise<SignalsData | null> {
  try {
    const r = await fetchFromFastAPI(`/organic-posts/signals?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

const MOCK_BEST_TIMES = [
  { day: 'Sun', times: ['8pm', '9pm'], lift: '+34%' },
  { day: 'Mon', times: ['7am', '12pm'], lift: '+12%' },
  { day: 'Tue', times: ['6pm', '8pm'], lift: '+18%' },
  { day: 'Wed', times: ['7pm', '9pm'], lift: '+22%' },
  { day: 'Thu', times: ['12pm', '6pm'], lift: '+15%' },
  { day: 'Fri', times: ['5pm', '7pm'], lift: '+28%' },
  { day: 'Sat', times: ['10am', '8pm'], lift: '+41%' },
]

export default async function OrganicPostsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const data = workspaceId ? await getSignals(workspaceId) : null
  const metaConnected = data?.meta_connected !== false  // treat null/error as "connected" to avoid false prompts
  const hasMetaData = data?.has_meta_data === true
  const hasTimingData = data?.has_timing_data === true

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-600">
            <Send className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Organic Posts</h1>
            <p className="text-sm text-gray-500">When to post, what to post — and which organic content should become paid ads</p>
          </div>
        </div>
        {!metaConnected && (
          <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700">
            Connect Meta <ArrowUpRight className="h-3 w-3" />
          </Link>
        )}
      </div>

      {/* Content theme performance — real Meta campaign CTR */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700">
            {hasMetaData ? 'Meta Campaign CTR — Content Signals' : 'Content Theme Performance'}
          </h2>
          <p className="text-xs text-gray-400">
            {hasMetaData
              ? 'High-CTR campaigns reveal your most engaging content themes. Boost organic posts that match these themes.'
              : metaConnected
                ? 'No campaign data with sufficient impressions yet — upload a Meta Ads Excel export to see real signals'
                : 'Which post formats drive the most reach and engagement'}
          </p>
        </div>

        {hasMetaData ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                  <th className="px-4 py-3 font-medium">Campaign / Theme</th>
                  <th className="px-4 py-3 font-medium text-right">Impressions</th>
                  <th className="px-4 py-3 font-medium text-right">Clicks</th>
                  <th className="px-4 py-3 font-medium text-right">CTR</th>
                  <th className="px-4 py-3 font-medium">Paid Signal</th>
                </tr>
              </thead>
              <tbody>
                {data!.top_campaigns.map((c, i) => {
                  const signal = c.ctr >= 3 ? 'very-high' : c.ctr >= 1.5 ? 'high' : 'average'
                  return (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-800 max-w-[200px]">
                        <span className="block truncate">{c.name}</span>
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">{c.impressions.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{c.clicks.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right font-semibold text-gray-800">{c.ctr.toFixed(2)}%</td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          signal === 'very-high' ? 'bg-green-100 text-green-700' :
                          signal === 'high' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {signal === 'very-high' ? '🔥 Boost this' : signal === 'high' ? '✓ Strong' : '→ Average'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto opacity-40 select-none">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                <th className="px-4 py-3 font-medium">Theme</th>
                <th className="px-4 py-3 font-medium text-right">Posts</th>
                <th className="px-4 py-3 font-medium text-right">Avg Reach</th>
                <th className="px-4 py-3 font-medium text-right">Eng Rate</th>
                <th className="px-4 py-3 font-medium">Paid Signal</th>
              </tr></thead>
              <tbody>
                {[
                  { theme: 'Product Demo', posts: 12, avgReach: '18,400', engRate: '4.2%', signal: 'high' },
                  { theme: 'Patient Testimonial', posts: 8, avgReach: '31,200', engRate: '6.8%', signal: 'high' },
                  { theme: 'Doctor Endorsement', posts: 4, avgReach: '52,000', engRate: '8.1%', signal: 'very-high' },
                  { theme: 'Product Specs', posts: 9, avgReach: '7,800', engRate: '1.9%', signal: 'low' },
                ].map((t, i) => (
                  <tr key={i} className="border-b border-gray-100">
                    <td className="px-4 py-3 font-medium text-gray-800">{t.theme}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{t.posts}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{t.avgReach}</td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-800">{t.engRate}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        t.signal === 'very-high' ? 'bg-green-100 text-green-700' :
                        t.signal === 'high' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
                      }`}>
                        {t.signal === 'very-high' ? '🔥 Boost this' : t.signal === 'high' ? '✓ Strong' : '→ Average'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Best posting times */}
      <div className={(!hasTimingData && !metaConnected) ? 'relative' : ''}>
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
            <h2 className="text-sm font-semibold text-gray-700">Best Times to Post</h2>
            <p className="text-xs text-gray-400">
              {hasTimingData
                ? 'Based on your Google Ads hour-of-day CTR data'
                : metaConnected
                  ? 'Upload a Google Ads time-of-day report to see peak hour CTR data'
                  : 'Based on your audience\'s online activity — Meta Insights API'}
            </p>
          </div>
          {hasTimingData ? (
            <div className="p-4">
              <div className="flex flex-wrap gap-3">
                {data!.best_hours.map((h, i) => (
                  <div key={i} className="rounded-lg border border-gray-100 bg-sky-50 px-4 py-3 text-center min-w-[90px]">
                    <p className="text-sm font-bold text-sky-700">Hour {h.hour}</p>
                    <p className="text-xs text-gray-500 mt-1">{h.avg_ctr.toFixed(2)}% CTR</p>
                    {h.conversions > 0 && (
                      <p className="text-xs text-green-600 mt-0.5">{h.conversions} conv</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="p-4">
              <div className="grid grid-cols-7 gap-2 opacity-40 select-none">
                {MOCK_BEST_TIMES.map(d => (
                  <div key={d.day} className="text-center">
                    <p className="text-xs font-semibold text-gray-600 mb-2">{d.day}</p>
                    {d.times.map(t => (
                      <div key={t} className="rounded bg-sky-100 px-1.5 py-1 text-[10px] text-sky-700 mb-1">{t}</div>
                    ))}
                    <p className="text-[10px] font-bold text-green-600 mt-1">{d.lift}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        {!hasTimingData && !metaConnected && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70 backdrop-blur-sm rounded-xl">
            <div className="text-center p-6">
              <Clock className="h-8 w-8 text-sky-500 mx-auto mb-3" />
              <p className="text-sm font-semibold text-gray-900">Connect Meta Business Account</p>
              <p className="text-xs text-gray-500 mt-1 max-w-xs">
                See exactly when your audience is online. Or upload a Google Ads time-of-day report for hour-level CTR data.
              </p>
              <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700">
                Connect in Settings <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        )}
      </div>

      {/* Organic paid loop */}
      <div className="rounded-xl border border-sky-200 bg-sky-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <Repeat className="h-5 w-5 text-sky-600" />
          <h3 className="text-sm font-semibold text-gray-900">Organic → Paid Signal Loop</h3>
        </div>
        <p className="text-xs text-gray-600 mb-4">
          High-CTR campaigns are your best candidates for paid boosting. When a campaign outperforms the average, that creative has already proven itself — zero creative risk when you put more budget behind it.
        </p>
        {hasMetaData && data!.top_campaigns.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[
              ['Best Creative Signal', data!.top_campaigns[0].name, `${data!.top_campaigns[0].ctr.toFixed(2)}% CTR`],
              ['Recommended Action', 'Increase daily budget', `Top campaign CTR is ${data!.top_campaigns[0].ctr.toFixed(2)}%`],
              ['Expected Lift', 'More impressions', 'With same CTR and proven creative'],
            ].map(([title, value, sub]) => (
              <div key={title} className="rounded-lg bg-white p-3 text-center">
                <p className="text-xs text-gray-500">{title}</p>
                <p className="text-sm font-bold text-gray-800 mt-1 truncate">{value}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 opacity-50">
            {[
              ['Best Organic Post', 'Doctor endorsement reel', '52K reach · 8.1% eng'],
              ['Recommended Boost Budget', '₹5,000–15,000', 'Projected reach: 2.4L'],
              ['Expected ROAS', '3.8x–5.2x', 'Based on similar creative history'],
            ].map(([title, value, sub]) => (
              <div key={title} className="rounded-lg bg-white p-3 text-center">
                <p className="text-xs text-gray-500">{title}</p>
                <p className="text-sm font-bold text-gray-800 mt-1">{value}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Capability cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-100">
              <TrendingUp className="h-4 w-4 text-sky-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Upload Time Correlation</h3>
          </div>
          <p className="text-xs text-gray-500">YouTube upload time vs views in first 48 hours. Find your optimal upload window — often 2–3 hours before your audience&apos;s peak activity.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-100">
              <BarChart2 className="h-4 w-4 text-purple-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Cross-Platform Timing</h3>
          </div>
          <p className="text-xs text-gray-500">&ldquo;Posts at 8pm Sunday → 23% more Google brand searches on Monday.&rdquo; See how organic social creates downstream search demand you can capture with ads.</p>
        </div>
      </div>
    </div>
  )
}
