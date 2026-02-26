'use client'

import { useState } from 'react'
import { formatINR, formatNumber, formatPercent } from '@/lib/utils'
import type { GoogleAdsKeyword, GoogleAdsSearchTerm } from '@/app/(app)/google-ads/page'

interface Props {
  keywords: GoogleAdsKeyword[]
  searchTerms: GoogleAdsSearchTerm[]
  wastedTotal: number
}

function QsBadge({ qs }: { qs: number | null }) {
  if (qs === null) return <span className="text-gray-400">—</span>
  const color =
    qs >= 7 ? 'text-green-700 bg-green-100'
    : qs >= 4 ? 'text-yellow-700 bg-yellow-100'
    : 'text-red-700 bg-red-100'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold ${color}`}>
      {qs}/10
    </span>
  )
}

function MatchBadge({ match }: { match: string }) {
  const label = match === 'EXACT' ? 'Exact' : match === 'PHRASE' ? 'Phrase' : 'Broad'
  const color =
    match === 'EXACT' ? 'bg-blue-100 text-blue-700'
    : match === 'PHRASE' ? 'bg-purple-100 text-purple-700'
    : 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
      {label}
    </span>
  )
}

type Tab = 'wasted' | 'qs' | 'negatives'

export default function GoogleAdsKeywords({ keywords, searchTerms, wastedTotal }: Props) {
  const [tab, setTab] = useState<Tab>('wasted')

  const wastedKeywords = keywords.filter(kw => kw.is_wasted).sort((a, b) => b.spend - a.spend)
  const negativeCandidates = searchTerms.filter(st => st.is_negative_candidate).sort((a, b) => b.spend - a.spend)
  const qsKeywords = keywords.filter(kw => kw.quality_score !== null).sort((a, b) => (a.quality_score ?? 10) - (b.quality_score ?? 10))

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'wasted', label: 'Wasted Spend', count: wastedKeywords.length },
    { key: 'qs', label: 'QS Audit', count: qsKeywords.length },
    { key: 'negatives', label: 'Negative Candidates', count: negativeCandidates.length },
  ]

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold text-gray-900">Keyword Analysis</h2>

      <div className="rounded-xl border border-gray-200 overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-gray-200 bg-gray-50">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-5 py-2.5 text-sm font-medium transition-colors ${
                tab === t.key
                  ? 'border-b-2 border-blue-600 bg-white text-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
              {t.count > 0 && (
                <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-xs ${
                  tab === t.key ? 'bg-blue-100 text-blue-700' : 'bg-gray-200 text-gray-600'
                }`}>
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Wasted Spend */}
        {tab === 'wasted' && (
          <div className="p-4">
            {wastedKeywords.length === 0 ? (
              <p className="py-8 text-center text-sm text-gray-400">No wasted spend keywords found. Great work!</p>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-xs text-gray-500">
                    Keywords with spend &gt; ₹200 and 0 conversions
                  </p>
                  <span className="rounded-lg bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">
                    Total wasted: {formatINR(wastedTotal)}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-200 text-left text-gray-500">
                        <th className="pb-2 pr-3 font-medium">Keyword</th>
                        <th className="pb-2 pr-3 font-medium">Match</th>
                        <th className="pb-2 pr-3 font-medium">Campaign</th>
                        <th className="pb-2 pr-3 font-medium text-right">Spend</th>
                        <th className="pb-2 pr-3 font-medium text-right">Clicks</th>
                        <th className="pb-2 font-medium text-right">Conv</th>
                      </tr>
                    </thead>
                    <tbody>
                      {wastedKeywords.map((kw, i) => (
                        <tr key={i} className="border-b border-red-100 bg-red-50">
                          <td className="py-2 pr-3 font-medium text-red-800 max-w-[160px]">
                            <span className="block truncate">{kw.keyword}</span>
                            {kw.ad_group_name && (
                              <span className="block truncate text-red-400">{kw.ad_group_name}</span>
                            )}
                          </td>
                          <td className="py-2 pr-3"><MatchBadge match={kw.match_type} /></td>
                          <td className="py-2 pr-3 text-gray-500 max-w-[140px]">
                            <span className="block truncate">{kw.campaign_name}</span>
                          </td>
                          <td className="py-2 pr-3 text-right font-semibold text-red-700">{formatINR(kw.spend)}</td>
                          <td className="py-2 pr-3 text-right text-gray-700">{formatNumber(kw.clicks)}</td>
                          <td className="py-2 text-right text-gray-700">0</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}

        {/* QS Audit */}
        {tab === 'qs' && (
          <div className="p-4">
            {qsKeywords.length === 0 ? (
              <p className="py-8 text-center text-sm text-gray-400">No Quality Score data found in this upload.</p>
            ) : (
              <>
                <p className="mb-3 text-xs text-gray-500">
                  Keywords sorted by Quality Score (lowest first). QS ≤ 3 in{' '}
                  <span className="rounded bg-red-100 px-1 text-red-700">red</span> — fix urgently.
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-200 text-left text-gray-500">
                        <th className="pb-2 pr-3 font-medium">Keyword</th>
                        <th className="pb-2 pr-3 font-medium">QS</th>
                        <th className="pb-2 pr-3 font-medium">Match</th>
                        <th className="pb-2 pr-3 font-medium">Campaign</th>
                        <th className="pb-2 pr-3 font-medium text-right">Spend</th>
                        <th className="pb-2 pr-3 font-medium text-right">CPC</th>
                        <th className="pb-2 font-medium text-right">Conv</th>
                      </tr>
                    </thead>
                    <tbody>
                      {qsKeywords.map((kw, i) => {
                        const isLowQs = (kw.quality_score ?? 10) <= 3
                        return (
                          <tr
                            key={i}
                            className={`border-b ${isLowQs ? 'border-red-100 bg-red-50' : 'border-gray-100 hover:bg-gray-50'}`}
                          >
                            <td className="py-2 pr-3 max-w-[160px]">
                              <span className={`block truncate font-medium ${isLowQs ? 'text-red-800' : 'text-gray-800'}`}>
                                {kw.keyword}
                              </span>
                              {isLowQs && (
                                <span className="text-red-500 text-[10px] font-semibold">Fix urgently</span>
                              )}
                            </td>
                            <td className="py-2 pr-3"><QsBadge qs={kw.quality_score} /></td>
                            <td className="py-2 pr-3"><MatchBadge match={kw.match_type} /></td>
                            <td className="py-2 pr-3 text-gray-500 max-w-[130px]">
                              <span className="block truncate">{kw.campaign_name}</span>
                            </td>
                            <td className={`py-2 pr-3 text-right font-medium ${isLowQs ? 'text-red-700' : 'text-gray-900'}`}>
                              {formatINR(kw.spend)}
                            </td>
                            <td className="py-2 pr-3 text-right text-gray-700">{formatINR(kw.cpc)}</td>
                            <td className="py-2 text-right text-gray-700">{formatNumber(kw.conversions)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}

        {/* Negative Candidates */}
        {tab === 'negatives' && (
          <div className="p-4">
            {negativeCandidates.length === 0 ? (
              <p className="py-8 text-center text-sm text-gray-400">No negative keyword candidates found.</p>
            ) : (
              <>
                <p className="mb-3 text-xs text-gray-500">
                  Search terms with spend &gt; ₹100 and 0 conversions — add these as negative keywords to stop wasted spend.
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-200 text-left text-gray-500">
                        <th className="pb-2 pr-3 font-medium">Search Term</th>
                        <th className="pb-2 pr-3 font-medium">Triggered By</th>
                        <th className="pb-2 pr-3 font-medium text-right">Wasted Spend</th>
                        <th className="pb-2 font-medium text-right">Conv</th>
                      </tr>
                    </thead>
                    <tbody>
                      {negativeCandidates.map((st, i) => (
                        <tr key={i} className="border-b border-orange-100 bg-orange-50/60">
                          <td className="py-2 pr-3 font-medium text-gray-900 max-w-[180px]">
                            <span className="block truncate">{st.search_term}</span>
                          </td>
                          <td className="py-2 pr-3 text-gray-500 max-w-[140px]">
                            {st.keyword ? (
                              <span className="block truncate">
                                {st.keyword}
                                {st.match_type && (
                                  <span className="ml-1 text-gray-400">[{st.match_type.toLowerCase()}]</span>
                                )}
                              </span>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                          <td className="py-2 pr-3 text-right font-semibold text-orange-700">
                            {formatINR(st.spend)}
                          </td>
                          <td className="py-2 text-right text-gray-700">0</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
