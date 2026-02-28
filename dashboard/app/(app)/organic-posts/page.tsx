import Link from 'next/link'
import { Send, Clock, TrendingUp, Repeat, ArrowUpRight, Youtube, Info, Zap } from 'lucide-react'
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
  source?: string
}

interface YouTubeHour {
  hour: number
  video_count: number
  avg_views: number
  avg_likes: number
}

interface SignalsData {
  meta_connected: boolean
  has_meta_data: boolean
  has_timing_data: boolean
  has_youtube_times: boolean
  top_campaigns: CampaignSignal[]
  best_hours: HourSignal[]
  youtube_upload_times: YouTubeHour[]
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

function fmtHour(h: string | number): string {
  const n = typeof h === 'string' ? parseInt(h) : h
  if (isNaN(n)) return String(h)
  const period = n >= 12 ? 'PM' : 'AM'
  const display = n === 0 ? 12 : n > 12 ? n - 12 : n
  return `${display}${period}`
}

function fmtViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function SectionHeading({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="bg-gray-50 px-5 py-4 border-b border-gray-200 flex items-center gap-3">
      <div className="shrink-0 text-gray-500">{icon}</div>
      <div>
        <h2 className="text-base font-bold text-gray-900">{title}</h2>
        {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  )
}

export default async function OrganicPostsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const data = workspaceId ? await getSignals(workspaceId) : null
  const metaConnected = data?.meta_connected === true
  const hasMetaData = data?.has_meta_data === true
  const hasTimingData = data?.has_timing_data === true
  const hasYoutubeTimes = data?.has_youtube_times === true

  const bestHour = data?.best_hours?.[0]
  const bestYtHour = data?.youtube_upload_times?.[0]

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-600">
            <Send className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Organic Posts</h1>
            <p className="text-sm text-gray-500">When to post, what to post — and which organic content should become paid ads</p>
          </div>
        </div>
        {!metaConnected && (
          <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-700">
            Connect Meta <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        )}
      </div>

      {/* Concept explainer */}
      <div className="rounded-xl border border-sky-200 bg-sky-50 p-5">
        <div className="flex items-start gap-3">
          <Repeat className="h-6 w-6 text-sky-600 mt-0.5 shrink-0" />
          <div className="space-y-2">
            <p className="text-base font-bold text-sky-900">Your best organic content should become paid ads.</p>
            <p className="text-sm text-sky-800 leading-relaxed">
              Every paid ad campaign is a <strong>content experiment</strong>. When a campaign gets a high CTR,
              it means the hook, the angle, or the message resonates with your audience — even before they click.
              That creative signal is gold. Replicate it in your organic posts (Reels, Stories, YouTube Shorts),
              and when an organic post performs well, put paid budget behind it. Zero creative risk — it&apos;s already proven.
            </p>
            <div className="flex flex-wrap gap-4 pt-1">
              <div className="text-sm text-sky-700">
                <span className="inline-block rounded bg-green-100 text-green-700 px-2 py-0.5 font-semibold mr-1.5">≥3% CTR</span>
                Exceptional — scale budget immediately
              </div>
              <div className="text-sm text-sky-700">
                <span className="inline-block rounded bg-blue-100 text-blue-700 px-2 py-0.5 font-semibold mr-1.5">≥1.5% CTR</span>
                Strong — replicate the angle in organic
              </div>
              <div className="text-sm text-sky-700">
                <span className="inline-block rounded bg-gray-100 text-gray-600 px-2 py-0.5 font-semibold mr-1.5">&lt;1.5% CTR</span>
                Average — test a different creative approach
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── 1. Campaign CTR — Paid Signal ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <SectionHeading
          icon={<TrendingUp className="h-5 w-5" />}
          title="Organic → Paid Signal Loop"
          subtitle={hasMetaData
            ? 'Last 90 days · Sorted by CTR · Industry avg ~0.9–1.2%'
            : metaConnected
              ? 'No campaigns with 100+ impressions in the last 90 days'
              : 'Connect Meta to see real campaign CTR signals'}
        />

        {hasMetaData ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                  <th className="px-5 py-3 font-semibold">Campaign / Theme</th>
                  <th className="px-5 py-3 font-semibold text-right">Impressions</th>
                  <th className="px-5 py-3 font-semibold text-right">Clicks</th>
                  <th className="px-5 py-3 font-semibold text-right">CTR</th>
                  <th className="px-5 py-3 font-semibold">
                    <span className="flex items-center gap-1">
                      Paid Signal
                      <span title="CTR ≥3% = Boost this. CTR ≥1.5% = Strong. CTR <1.5% = Average. Meta industry avg is ~0.9–1.2%.">
                        <Info className="h-3.5 w-3.5 text-gray-400" />
                      </span>
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data!.top_campaigns.map((c, i) => {
                  const signal = c.ctr >= 3 ? 'very-high' : c.ctr >= 1.5 ? 'high' : 'average'
                  return (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-5 py-3 font-medium text-gray-800 max-w-[240px]">
                        <span className="block truncate">{c.name}</span>
                      </td>
                      <td className="px-5 py-3 text-right text-gray-600">{c.impressions.toLocaleString('en-IN')}</td>
                      <td className="px-5 py-3 text-right text-gray-600">{c.clicks.toLocaleString('en-IN')}</td>
                      <td className="px-5 py-3 text-right font-bold text-gray-800">{c.ctr.toFixed(2)}%</td>
                      <td className="px-5 py-3">
                        <span className={`rounded-full px-3 py-0.5 text-xs font-semibold ${
                          signal === 'very-high' ? 'bg-green-100 text-green-700' :
                          signal === 'high' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {signal === 'very-high' ? 'Boost this' : signal === 'high' ? 'Strong — replicate' : 'Average'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 py-10 text-center">
            <TrendingUp className="h-8 w-8 text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No campaign data yet.</p>
            <p className="text-xs text-gray-400 mt-1">
              {metaConnected
                ? 'Run campaigns with 100+ impressions to see CTR signals.'
                : <>Connect Meta in <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'} className="underline text-sky-600">Settings</Link> to see content signals.</>}
            </p>
          </div>
        )}
      </div>

      {/* ── 2. Best Times to Post ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <SectionHeading
          icon={<Clock className="h-5 w-5" />}
          title="Best Times to Post"
          subtitle={hasTimingData
            ? `Hours when your Meta ads get the highest CTR — audience is most receptive then · Source: ${data!.best_hours[0]?.source === 'meta' ? 'Meta Ads hourly breakdown' : 'Google Ads time-of-day report'}`
            : 'Hours when your audience is most receptive, based on Meta ad performance'}
        />
        {hasTimingData ? (
          <div className="p-5">
            <div className="flex flex-wrap gap-3">
              {data!.best_hours.map((h, i) => (
                <div key={i} className={`rounded-xl border px-5 py-4 text-center min-w-[110px] ${
                  i === 0 ? 'border-sky-300 bg-sky-50' : 'border-gray-100 bg-gray-50'
                }`}>
                  <p className={`text-lg font-bold ${i === 0 ? 'text-sky-700' : 'text-gray-700'}`}>
                    {fmtHour(h.hour)}
                  </p>
                  <p className="text-sm text-gray-500 mt-0.5">{h.avg_ctr.toFixed(2)}% CTR</p>
                  {h.conversions > 0 && (
                    <p className="text-xs text-green-600 mt-0.5">{h.conversions} conv</p>
                  )}
                  {i === 0 && <p className="text-xs text-sky-600 mt-1 font-semibold">Peak</p>}
                </div>
              ))}
            </div>
            <p className="text-sm text-gray-500 mt-4">
              Post your organic content 1–2 hours before your peak ad hour to warm up the audience before paid spend kicks in.
            </p>
          </div>
        ) : (
          <div className="px-5 py-10 text-center">
            <Clock className="h-8 w-8 text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No hourly data yet.</p>
            <p className="text-sm text-gray-400 mt-1 max-w-xs mx-auto">
              {metaConnected
                ? 'Run Meta campaigns with 50+ impressions to see hourly CTR breakdown.'
                : 'Connect Meta or upload a Google Ads Time of Day report to see peak hours.'}
            </p>
          </div>
        )}
      </div>

      {/* ── 3. YouTube Upload Time Correlation ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <SectionHeading
          icon={<Youtube className="h-5 w-5 text-red-500" />}
          title="Upload Time Correlation"
          subtitle={hasYoutubeTimes
            ? 'Which upload hours your YouTube videos averaged the most views — IST'
            : 'Upload hour vs. avg views in your channel history'}
        />
        {hasYoutubeTimes ? (
          <div className="p-5">
            <div className="flex flex-wrap gap-3 mb-4">
              {data!.youtube_upload_times.map((yt, i) => (
                <div key={i} className={`rounded-xl border px-4 py-4 text-center min-w-[100px] ${
                  i === 0 ? 'border-red-200 bg-red-50' : 'border-gray-100 bg-gray-50'
                }`}>
                  <p className={`text-lg font-bold ${i === 0 ? 'text-red-600' : 'text-gray-700'}`}>
                    {fmtHour(yt.hour)}
                  </p>
                  <p className="text-sm text-gray-600 mt-0.5">{fmtViews(yt.avg_views)} avg views</p>
                  <p className="text-xs text-gray-400">{yt.video_count} video{yt.video_count !== 1 ? 's' : ''}</p>
                  {i === 0 && <p className="text-xs text-red-600 mt-1 font-semibold">Best slot</p>}
                </div>
              ))}
            </div>
            <p className="text-sm text-gray-500">
              Upload YouTube Shorts and long-form videos at your best slot to maximise early watch time — the algorithm rewards it.
            </p>
          </div>
        ) : (
          <div className="px-5 py-10 text-center">
            <Youtube className="h-8 w-8 text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No YouTube data yet.</p>
            <p className="text-sm text-gray-400 mt-1">
              Connect your YouTube channel in{' '}
              <Link href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'} className="underline text-sky-600">Settings</Link>
              {' '}to see which upload times get the most views.
            </p>
          </div>
        )}
      </div>

      {/* ── 4. Cross-Platform Timing ── */}
      <div className="rounded-xl border border-purple-200 overflow-hidden">
        <SectionHeading
          icon={<Zap className="h-5 w-5 text-purple-600" />}
          title="Cross-Platform Timing"
          subtitle="Coordinating your Meta ads + YouTube uploads for maximum reach"
        />
        <div className="p-5">
          {(hasTimingData || hasYoutubeTimes) ? (
            <div className="space-y-4">
              {/* Visual timeline */}
              <div className="flex items-center gap-3 flex-wrap">
                {hasYoutubeTimes && bestYtHour && (
                  <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
                    <Youtube className="h-5 w-5 text-red-500 shrink-0" />
                    <div>
                      <p className="text-xs text-gray-500 font-medium">Upload to YouTube</p>
                      <p className="text-lg font-bold text-red-700">{fmtHour(bestYtHour.hour)}</p>
                      <p className="text-xs text-gray-400">{fmtViews(bestYtHour.avg_views)} avg views</p>
                    </div>
                  </div>
                )}
                {hasYoutubeTimes && hasTimingData && (
                  <div className="text-xl font-bold text-gray-300 px-1">→</div>
                )}
                {hasTimingData && bestHour && (
                  <div className="flex items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
                    <Send className="h-5 w-5 text-sky-500 shrink-0" />
                    <div>
                      <p className="text-xs text-gray-500 font-medium">Activate Meta Ad</p>
                      <p className="text-lg font-bold text-sky-700">{fmtHour(bestHour.hour)}</p>
                      <p className="text-xs text-gray-400">{bestHour.avg_ctr.toFixed(2)}% CTR hour</p>
                    </div>
                  </div>
                )}
              </div>
              <div className="rounded-lg bg-purple-50 border border-purple-100 px-4 py-3">
                <p className="text-sm text-purple-900 leading-relaxed">
                  {hasYoutubeTimes && hasTimingData && bestYtHour && bestHour ? (
                    <>
                      <strong>Strategy:</strong> Upload to YouTube at <strong>{fmtHour(bestYtHour.hour)}</strong> to build organic reach first.
                      Then activate your Meta ad at <strong>{fmtHour(bestHour.hour)}</strong> — YouTube organic warms up the audience
                      before your paid spend converts them. Both channels reinforce each other.
                    </>
                  ) : hasTimingData && bestHour ? (
                    <>
                      <strong>Meta peak hour:</strong> <strong>{fmtHour(bestHour.hour)}</strong> — schedule your posts 1–2 hours before this.
                      Connect your YouTube channel to unlock cross-platform timing recommendations.
                    </>
                  ) : hasYoutubeTimes && bestYtHour ? (
                    <>
                      <strong>Best YouTube upload slot:</strong> <strong>{fmtHour(bestYtHour.hour)}</strong>.
                      Connect Meta to see when your paid ads peak and combine both for maximum effect.
                    </>
                  ) : null}
                </p>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center">
              <Zap className="h-8 w-8 text-gray-200 mx-auto mb-3" />
              <p className="text-sm text-gray-500">No timing data yet.</p>
              <p className="text-sm text-gray-400 mt-1 max-w-sm mx-auto">
                Connect Meta and run campaigns, or connect YouTube to see coordinated posting recommendations.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── 5. Action Plan ── */}
      <div className="rounded-xl border border-sky-200 bg-sky-50 overflow-hidden">
        <div className="px-5 py-4 border-b border-sky-200 flex items-center gap-3">
          <Repeat className="h-5 w-5 text-sky-600" />
          <h2 className="text-base font-bold text-gray-900">Action Plan — Organic → Paid Loop</h2>
        </div>
        <div className="p-5">
          {hasMetaData && data!.top_campaigns.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 mb-4">
                {[
                  {
                    title: 'Best Performing Creative',
                    value: data!.top_campaigns[0].name,
                    sub: `${data!.top_campaigns[0].ctr.toFixed(2)}% CTR · ${data!.top_campaigns[0].impressions.toLocaleString('en-IN')} impressions`,
                  },
                  {
                    title: 'Recommended Next Action',
                    value: data!.top_campaigns[0].ctr >= 1.5 ? 'Create organic version' : 'Test new creative angle',
                    sub: data!.top_campaigns[0].ctr >= 1.5
                      ? 'Turn the winning ad hook into a Reel or YouTube Short'
                      : "This CTR is below average — the hook isn't landing",
                  },
                  {
                    title: 'Best Posting Time',
                    value: hasTimingData ? `Post at ${fmtHour(data!.best_hours[0].hour)}` : 'Connect timing data',
                    sub: hasTimingData
                      ? `Peak CTR hour for your audience`
                      : 'Run more Meta campaigns to find your peak hour',
                  },
                ].map(({ title, value, sub }) => (
                  <div key={title} className="rounded-lg bg-white p-4">
                    <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide">{title}</p>
                    <p className="text-sm font-bold text-gray-800 mt-1.5 truncate">{value}</p>
                    <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{sub}</p>
                  </div>
                ))}
              </div>
              <div className="rounded-lg bg-white border border-sky-100 px-4 py-3">
                <p className="text-sm text-gray-700 leading-relaxed">
                  <strong>Step 1:</strong> Take the hook from &ldquo;{data!.top_campaigns[0].name}&rdquo; and recreate it as an organic Reel or YouTube Short.
                  {' '}<strong>Step 2:</strong> Post it{hasTimingData ? ` at ${fmtHour(data!.best_hours[0].hour)}` : ' at your peak time'}.
                  {' '}<strong>Step 3:</strong> If it gets engagement within 48 hours, boost it as a Meta ad — the algorithm already knows it works.
                </p>
              </div>
            </>
          ) : (
            <p className="text-sm text-sky-700/70">
              Connect Meta and run campaigns to see your organic → paid action plan here.
            </p>
          )}
        </div>
      </div>

    </div>
  )
}
