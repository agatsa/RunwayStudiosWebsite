'use client'

import { useState } from 'react'
import { TrendingUp, TrendingDown, Minus, ShoppingBag, Megaphone, Monitor } from 'lucide-react'

function fmtINR(n: number) {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)}Cr`
  if (n >= 1_00_000)    return `₹${(n / 1_00_000).toFixed(2)}L`
  if (n >= 1_000)       return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n.toFixed(0)}`
}

function acosColor(acos: number) {
  if (acos === 0)  return 'text-gray-400'
  if (acos <= 20)  return 'text-green-600'
  if (acos <= 35)  return 'text-yellow-600'
  return 'text-red-600'
}

function roasIcon(roas: number) {
  if (roas >= 4)   return <TrendingUp className="h-3 w-3 text-green-500" />
  if (roas >= 2)   return <Minus className="h-3 w-3 text-yellow-500" />
  return <TrendingDown className="h-3 w-3 text-red-500" />
}

function adTypeIcon(adType: string) {
  const t = adType.toLowerCase()
  if (t.includes('brand'))   return <Megaphone className="h-3 w-3 text-red-500" />
  if (t.includes('display')) return <Monitor className="h-3 w-3 text-pink-500" />
  return <ShoppingBag className="h-3 w-3 text-orange-500" />
}

function statusBadge(status: string) {
  const s = (status || '').toUpperCase()
  if (s === 'ENABLED' || s === 'ACTIVE')
    return <span className="rounded-full bg-green-100 px-2 py-0.5 text-[9px] font-bold text-green-700">Active</span>
  if (s === 'PAUSED')
    return <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[9px] font-bold text-yellow-700">Paused</span>
  return <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[9px] font-bold text-gray-500">{status}</span>
}

export interface AmazonCampaign {
  id: string
  name: string
  ad_type: string
  campaign_status: string
  spend: number
  impressions: number
  clicks: number
  orders: number
  sales: number
  roas: number
  acos: number
  ctr: number
  cpc: number
}

interface Props {
  campaigns: AmazonCampaign[]
}

type SortKey = 'spend' | 'sales' | 'roas' | 'acos' | 'orders'

export default function AmazonCampaignTable({ campaigns }: Props) {
  const [sort, setSort] = useState<SortKey>('spend')
  const [filter, setFilter] = useState<string>('all')

  const adTypes = Array.from(new Set(campaigns.map(c => c.ad_type)))

  const sorted = [...campaigns]
    .filter(c => filter === 'all' || c.ad_type === filter)
    .sort((a, b) => b[sort] - a[sort])

  if (!campaigns.length) return (
    <div className="flex flex-col items-center justify-center py-14 text-gray-400">
      <ShoppingBag className="h-10 w-10 mb-3 opacity-30" />
      <p className="text-sm font-medium">No Amazon Ads data yet</p>
      <p className="text-xs mt-1">Upload a Sponsored Products or Sponsored Brands report above</p>
    </div>
  )

  const SortBtn = ({ k, label }: { k: SortKey, label: string }) => (
    <button
      onClick={() => setSort(k)}
      className={`text-[10px] font-semibold px-2 py-1 rounded ${sort === k ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
    >
      {label}
    </button>
  )

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setFilter('all')}
            className={`text-xs px-3 py-1 rounded-full font-medium ${filter === 'all' ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-600'}`}
          >All</button>
          {adTypes.map(t => (
            <button key={t} onClick={() => setFilter(t)}
              className={`text-xs px-3 py-1 rounded-full font-medium flex items-center gap-1 ${filter === t ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-600'}`}>
              {adTypeIcon(t)}{t}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <SortBtn k="spend" label="Spend" />
          <SortBtn k="sales" label="Sales" />
          <SortBtn k="roas" label="ROAS" />
          <SortBtn k="acos" label="ACoS" />
          <SortBtn k="orders" label="Orders" />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-gray-100">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              <th className="text-left px-4 py-2.5 font-semibold text-gray-500">Campaign</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">Spend</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">Sales</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">ROAS</th>
              <th className="text-right px-3 py-2.5 font-semibold text-orange-600">ACoS</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">Orders</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">Clicks</th>
              <th className="text-right px-3 py-2.5 font-semibold text-gray-500">CTR</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c, i) => (
              <tr key={c.id} className={`border-b border-gray-50 hover:bg-orange-50/30 transition-colors ${i % 2 === 1 ? 'bg-gray-50/50' : ''}`}>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {adTypeIcon(c.ad_type)}
                    <div>
                      <p className="font-medium text-gray-900 max-w-[200px] truncate">{c.name}</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        {statusBadge(c.campaign_status)}
                        <span className="text-[9px] text-gray-400">{c.ad_type}</span>
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-3 text-right font-mono font-bold text-gray-800">{fmtINR(c.spend)}</td>
                <td className="px-3 py-3 text-right font-mono font-bold text-green-700">{fmtINR(c.sales)}</td>
                <td className="px-3 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {roasIcon(c.roas)}
                    <span className="font-bold text-gray-800">{c.roas > 0 ? `${c.roas.toFixed(2)}x` : '—'}</span>
                  </div>
                </td>
                <td className={`px-3 py-3 text-right font-bold ${acosColor(c.acos)}`}>
                  {c.acos > 0 ? `${c.acos.toFixed(1)}%` : '—'}
                </td>
                <td className="px-3 py-3 text-right text-gray-700">{c.orders > 0 ? c.orders.toFixed(0) : '—'}</td>
                <td className="px-3 py-3 text-right text-gray-700">{c.clicks.toLocaleString('en-IN')}</td>
                <td className="px-3 py-3 text-right text-gray-500">{c.ctr > 0 ? `${c.ctr.toFixed(2)}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
