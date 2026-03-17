'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Zap, Crown, CheckCircle2, ArrowRight, TrendingUp } from 'lucide-react'
import type { BillingStatus, PlanName } from '@/lib/types'
import PlanBadge from '@/components/billing/PlanBadge'
import TopUpModal from '@/components/billing/TopUpModal'
import PageLoader from '@/components/ui/PageLoader'

const PLANS: { key: PlanName; label: string; monthly: string; yearly: string; credits: number; features: string[]; highlight?: boolean }[] = [
  {
    key: 'free', label: 'Free', monthly: '₹0', yearly: '₹0', credits: 50,
    features: ['1 workspace', 'CSV upload only', 'Growth OS (credits)', 'Campaign Brief (credits)', '50 one-time signup credits'],
  },
  {
    key: 'starter', label: 'Starter', monthly: '₹1,999', yearly: '₹19,999', credits: 150,
    features: ['1 workspace', 'Meta + Google live', '150 credits/month', 'Competitor Intel AI', 'Basic AI insights'],
  },
  {
    key: 'growth', label: 'Growth', monthly: '₹4,999', yearly: '₹47,988', credits: 500, highlight: true,
    features: ['1 workspace', 'All channels + YouTube', '500 credits/month', 'YT Competitor Intel', 'Growth Recipe', 'WhatsApp/Telegram alerts'],
  },
  {
    key: 'agency', label: 'Agency', monthly: '₹11,999', yearly: '₹1,11,999', credits: 2000,
    features: ['5 workspaces', 'Everything in Growth', '2,000 credits/month', 'Admin panel', 'Priority support'],
  },
]

const FEATURE_LABELS: Record<string, string> = {
  yt_competitor_intel: 'YT Competitor Intel',
  growth_os: 'Growth OS',
  video_ai_insights: 'Video AI Insights',
  campaign_brief: 'Campaign Brief',
  competitor_ai: 'Competitor Intel AI',
  growth_recipe_regen: 'Growth Recipe Regen',
  signup_grant: 'Signup Bonus',
  topup: 'Top-Up',
  monthly_plan: 'Monthly Plan',
  admin_grant: 'Admin Grant',
}

export default function BillingPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''

  const [billing, setBilling] = useState<BillingStatus | null>(null)
  const [period, setPeriod] = useState<'monthly' | 'yearly'>('monthly')
  const [showTopUp, setShowTopUp] = useState(false)
  const [upgrading, setUpgrading] = useState<PlanName | null>(null)

  const load = async () => {
    if (!wsId) return
    try {
      const res = await fetch(`/api/billing/status?workspace_id=${wsId}`)
      if (res.ok) setBilling(await res.json())
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [wsId])

  const handleUpgrade = async (plan: PlanName) => {
    if (!wsId) return
    setUpgrading(plan)
    try {
      const res = await fetch('/api/billing/upgrade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, plan, period }),
      })
      const data = await res.json()
      if (data.stub) {
        alert(`Razorpay not yet configured. Set RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET on Cloud Run to enable payments.`)
      } else if (data.payment_url) {
        window.open(data.payment_url, '_blank')
      }
    } catch { /* ignore */ }
    setUpgrading(null)
  }

  if (!billing) {
    return <PageLoader section="Billing" />
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Billing & Credits</h1>
        <p className="text-sm text-gray-500 mt-1">Manage your plan and credit balance</p>
      </div>

      {/* Current plan summary */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-1">Current Plan</p>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-gray-900 capitalize">{billing.plan}</span>
              <PlanBadge plan={billing.plan} />
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-1">Credits</p>
            <div className="flex items-center gap-1.5 text-2xl font-bold text-gray-900">
              <Zap className="h-6 w-6 text-amber-400" />
              {billing.credit_balance}
            </div>
          </div>
        </div>
        {billing.subscription_status && (
          <p className="text-xs text-gray-400">
            Subscription: <span className="capitalize font-medium text-gray-600">{billing.subscription_status}</span>
            {billing.current_period_end && (
              <span className="ml-2">· Renews {new Date(billing.current_period_end).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
            )}
          </p>
        )}
      </div>

      {/* Top-up packs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold text-gray-900">Top Up Credits</h2>
          <p className="text-xs text-gray-400">Credits never expire</p>
        </div>
        <div className="grid grid-cols-3 gap-4">
          {[
            { key: '100', credits: 100, price: '₹799', perCredit: '₹7.99' },
            { key: '250', credits: 250, price: '₹1,499', perCredit: '₹5.99', badge: 'Popular' },
            { key: '600', credits: 600, price: '₹2,999', perCredit: '₹4.99', badge: 'Best Value' },
          ].map(pack => (
            <div key={pack.key} className="relative rounded-xl border border-gray-200 bg-white p-4 text-center hover:border-amber-300 hover:shadow-sm transition-all">
              {pack.badge && (
                <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-amber-400 px-2.5 py-0.5 text-[10px] font-bold text-white">
                  {pack.badge}
                </span>
              )}
              <div className="flex items-center justify-center gap-1 mb-1 mt-1">
                <Zap className="h-5 w-5 text-amber-400" />
                <span className="text-2xl font-bold text-gray-900">{pack.credits}</span>
              </div>
              <p className="text-xs text-gray-400 mb-3">{pack.perCredit}/credit</p>
              <button
                onClick={() => setShowTopUp(true)}
                className="w-full rounded-lg bg-amber-500 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-600 transition-colors"
              >
                {pack.price}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Plan upgrade */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold text-gray-900">Plans</h2>
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1 text-xs">
            <button
              onClick={() => setPeriod('monthly')}
              className={`rounded px-3 py-1.5 font-medium transition-colors ${period === 'monthly' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:text-gray-700'}`}
            >
              Monthly
            </button>
            <button
              onClick={() => setPeriod('yearly')}
              className={`rounded px-3 py-1.5 font-medium transition-colors ${period === 'yearly' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:text-gray-700'}`}
            >
              Yearly <span className="text-green-600 font-bold">-20%</span>
            </button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {PLANS.map(plan => {
            const isCurrent = billing.plan === plan.key
            const price = period === 'yearly' ? plan.yearly : plan.monthly
            return (
              <div key={plan.key} className={`relative rounded-xl border-2 p-4 flex flex-col gap-3 ${
                plan.highlight
                  ? 'border-purple-400 bg-purple-50'
                  : isCurrent
                  ? 'border-brand-300 bg-brand-50'
                  : 'border-gray-200 bg-white'
              }`}>
                {plan.highlight && (
                  <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-purple-500 px-2.5 py-0.5 text-[10px] font-bold text-white whitespace-nowrap">
                    Most Popular
                  </span>
                )}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">{plan.label}</p>
                  <p className="text-xl font-bold text-gray-900 mt-1">{price}<span className="text-xs font-normal text-gray-400">/{period === 'yearly' ? 'yr' : 'mo'}</span></p>
                  <div className="flex items-center gap-1 mt-1 text-xs text-amber-600 font-medium">
                    <Zap className="h-3 w-3" />{plan.credits === 50 ? '50 one-time' : `${plan.credits}/mo`}
                  </div>
                </div>
                <ul className="space-y-1 flex-1">
                  {plan.features.map(f => (
                    <li key={f} className="flex items-start gap-1.5 text-xs text-gray-600">
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" />
                      {f}
                    </li>
                  ))}
                </ul>
                {isCurrent ? (
                  <span className="w-full rounded-lg border border-gray-200 px-3 py-2 text-center text-xs font-semibold text-gray-400">
                    Current plan
                  </span>
                ) : plan.key === 'free' ? null : (
                  <button
                    onClick={() => handleUpgrade(plan.key)}
                    disabled={upgrading === plan.key}
                    className={`w-full flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-white transition-colors ${
                      plan.highlight
                        ? 'bg-purple-600 hover:bg-purple-700'
                        : 'bg-gray-900 hover:bg-gray-700'
                    } disabled:opacity-50`}
                  >
                    {upgrading === plan.key ? 'Redirecting…' : <>Upgrade <ArrowRight className="h-3 w-3" /></>}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Feature credit costs */}
      <div>
        <h2 className="text-lg font-bold text-gray-900 mb-3">Credit Costs per Feature</h2>
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-400">
              <tr>
                <th className="px-4 py-3 text-left">Feature</th>
                <th className="px-4 py-3 text-right">Credits</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {Object.entries(billing.feature_costs).map(([key, cost]) => (
                <tr key={key} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-700">{FEATURE_LABELS[key] ?? key}</td>
                  <td className="px-4 py-3 text-right font-semibold text-gray-900 flex items-center justify-end gap-1">
                    <Zap className="h-3.5 w-3.5 text-amber-400" />{cost}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Usage history */}
      {billing.recent_ledger.length > 0 && (
        <div>
          <h2 className="text-lg font-bold text-gray-900 mb-3">Recent Activity</h2>
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-400">
                <tr>
                  <th className="px-4 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Description</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3 text-right">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {billing.recent_ledger.map((entry, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                      {new Date(entry.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">{entry.description}</td>
                    <td className={`px-4 py-2.5 text-right font-semibold tabular-nums ${entry.amount > 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {entry.amount > 0 ? '+' : ''}{entry.amount}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-500 tabular-nums flex items-center justify-end gap-1">
                      <Zap className="h-3 w-3 text-amber-400" />{entry.balance_after}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showTopUp && (
        <TopUpModal
          wsId={wsId}
          onClose={() => setShowTopUp(false)}
          onSuccess={(newBalance) => {
            setShowTopUp(false)
            setBilling(prev => prev ? { ...prev, credit_balance: newBalance } : prev)
          }}
        />
      )}
    </div>
  )
}
