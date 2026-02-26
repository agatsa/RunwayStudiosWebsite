import Link from 'next/link'
import { MessageSquare, ThumbsUp, ThumbsDown, AlertCircle, Lightbulb, Star, ArrowUpRight, TrendingDown } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'
import { formatINR } from '@/lib/utils'

interface PageProps { searchParams: { ws?: string } }

interface SignalTerm {
  term: string
  spend: number
  clicks: number
  signal: string
  insight: string
  conversions?: number
  conv_rate?: number
}

interface CommentsData {
  has_data: boolean
  pain_terms: SignalTerm[]
  winning_terms: SignalTerm[]
}

async function getInsights(workspaceId: string): Promise<CommentsData | null> {
  try {
    const r = await fetchFromFastAPI(`/comments/insights?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

export default async function CommentsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const data = workspaceId ? await getInsights(workspaceId) : null
  const hasData = data?.has_data === true

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-pink-600">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Comments &amp; Reviews</h1>
            <p className="text-sm text-gray-500">Voice of customer — what search intent reveals about your buyers</p>
          </div>
        </div>
        {hasData ? (
          <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-700">
            {(data!.pain_terms.length + data!.winning_terms.length)} signals found
          </span>
        ) : (
          <span className="rounded-full bg-pink-100 px-3 py-1 text-xs font-semibold text-pink-700">
            Upload search terms to activate
          </span>
        )}
      </div>

      {hasData ? (
        <>
          {/* Winning terms — resonating messages */}
          {data!.winning_terms.length > 0 && (
            <div className="rounded-xl border border-green-200 overflow-hidden">
              <div className="bg-green-50 px-4 py-3 border-b border-green-200">
                <h2 className="text-sm font-semibold text-gray-700">Resonating Messages</h2>
                <p className="text-xs text-gray-400">Search terms that are converting — what your buyers actually want</p>
              </div>
              <div className="divide-y divide-gray-100">
                {data!.winning_terms.slice(0, 10).map((item, i) => (
                  <div key={i} className="px-4 py-3 flex items-start gap-3">
                    <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-green-100">
                      <ThumbsUp className="h-3 w-3 text-green-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-800 truncate">{item.term}</p>
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                          Resonating Message
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">{item.insight}</p>
                      <p className="text-xs text-gray-400 mt-0.5 italic">
                        What this means: Buyers searching &ldquo;{item.term}&rdquo; are converting — use this exact phrase in your ad headlines.
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-sm font-bold text-green-700">{item.conv_rate?.toFixed(1)}% CVR</p>
                      <p className="text-xs text-gray-400">{item.conversions} conv</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Pain terms — customer barriers */}
          {data!.pain_terms.length > 0 && (
            <div className="rounded-xl border border-red-200 overflow-hidden">
              <div className="bg-red-50 px-4 py-3 border-b border-red-200">
                <h2 className="text-sm font-semibold text-gray-700">Customer Barriers</h2>
                <p className="text-xs text-gray-400">High spend with zero conversions — unmet intent or purchase objections</p>
              </div>
              <div className="divide-y divide-gray-100">
                {data!.pain_terms.slice(0, 10).map((item, i) => (
                  <div key={i} className="px-4 py-3 flex items-start gap-3 bg-red-50/30">
                    <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-100">
                      <ThumbsDown className="h-3 w-3 text-red-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-red-800 truncate">{item.term}</p>
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                          Customer Barrier
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">{item.insight}</p>
                      <p className="text-xs text-gray-400 mt-0.5 italic">
                        What this means: This search intent isn&apos;t matching your offer — either add it as a negative keyword or create a dedicated landing page.
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-sm font-bold text-red-700">{formatINR(item.spend)}</p>
                      <p className="text-xs text-gray-400">{item.clicks} clicks</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        /* Mock voice-of-customer feed with overlay */
        <div className="relative">
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-700">Search Signal Feed</h2>
              <span className="text-xs text-gray-400">From Google Ads search terms data</span>
            </div>
            <div className="divide-y divide-gray-100 opacity-40 select-none">
              {[
                { label: 'Resonating Message', term: '"portable ECG device price"', insight: '3 conversions at 4.2% CVR', icon: 'up' },
                { label: 'Customer Barrier', term: '"blood sugar monitor without prick"', insight: '₹1,840 spent, 0 conversions', icon: 'down' },
                { label: 'Resonating Message', term: '"12 lead ECG home india"', insight: '8 conversions at 6.1% CVR', icon: 'up' },
                { label: 'Customer Barrier', term: '"glucose meter app not working"', insight: '₹620 spent, 0 conversions', icon: 'down' },
              ].map((item, i) => (
                <div key={i} className="px-4 py-3 flex items-start gap-3">
                  <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${item.icon === 'up' ? 'bg-green-100' : 'bg-red-100'}`}>
                    {item.icon === 'up' ? <ThumbsUp className="h-3 w-3 text-green-600" /> : <ThumbsDown className="h-3 w-3 text-red-600" />}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-gray-800">{item.term}</p>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${item.icon === 'up' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>{item.label}</span>
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">{item.insight}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="absolute inset-0 flex items-center justify-center bg-white/70 backdrop-blur-sm rounded-xl">
            <div className="text-center p-6">
              <TrendingDown className="h-8 w-8 text-pink-500 mx-auto mb-3" />
              <p className="text-sm font-semibold text-gray-900">No search term data yet</p>
              <p className="text-xs text-gray-500 mt-1 max-w-xs">
                Upload a Google Ads Excel report with a Search Terms tab to see voice-of-customer signals derived from real search intent.
              </p>
              <Link href={workspaceId ? `/google-ads?ws=${workspaceId}` : '/google-ads'}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-pink-600 px-4 py-2 text-sm font-medium text-white hover:bg-pink-700">
                Upload in Google Ads <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Capability cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-pink-100">
              <Star className="h-4 w-4 text-pink-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Product Intelligence</h3>
          </div>
          <p className="text-xs text-gray-500">Extract feature requests and pain points from thousands of reviews across Amazon, Flipkart, Google Maps — automatically sorted by frequency.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-100">
              <AlertCircle className="h-4 w-4 text-orange-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Objection Patterns</h3>
          </div>
          <p className="text-xs text-gray-500">Most common objections in comments fed directly into your ad copy and FAQ pages. &ldquo;Too expensive&rdquo; → write price-justification ad variant.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-100">
              <MessageSquare className="h-4 w-4 text-purple-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">NPS from Comments</h3>
          </div>
          <p className="text-xs text-gray-500">Sentiment scoring across all comment sources. Track brand health week over week — see if a campaign improved or hurt brand perception.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
              <Lightbulb className="h-4 w-4 text-blue-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Improvement Suggestions</h3>
          </div>
          <p className="text-xs text-gray-500">AI-generated product improvement recommendations based on what customers keep asking for. Feed directly to your product team.</p>
        </div>
      </div>
    </div>
  )
}
