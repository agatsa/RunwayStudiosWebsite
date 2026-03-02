'use client'

import { useEffect, useState } from 'react'
import { Zap, Crown, Users, TrendingUp, RefreshCw, X, Check, Link } from 'lucide-react'
import PlanBadge from '@/components/billing/PlanBadge'
import type { PlanName } from '@/lib/types'

interface OrgRow {
  id: string
  name: string
  plan: PlanName
  credit_balance: number
  clerk_user_id: string | null
  workspace_count: number
  last_credit_activity: string | null
}

interface DashboardData {
  orgs: OrgRow[]
  summary: {
    total_orgs: number
    paying_orgs: number
    total_credits_outstanding: number
    mrr_estimate_inr: number
  }
}

function AddCreditsModal({ org, onClose, onDone }: { org: OrgRow; onClose: () => void; onDone: () => void }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('Admin grant')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async () => {
    const n = parseInt(amount, 10)
    if (!n || n <= 0) return
    setLoading(true)
    try {
      const res = await fetch('/api/admin/add-credits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_id: org.id, amount: n, reason }),
      })
      if (res.ok) {
        setSuccess(true)
        setTimeout(() => { onDone(); onClose() }, 1200)
      }
    } catch { /* ignore */ }
    setLoading(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Add Credits</p>
            <p className="text-sm font-bold text-gray-900">{org.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {success ? (
          <div className="px-5 py-10 flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
              <Check className="h-6 w-6 text-green-600" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Credits added!</p>
          </div>
        ) : (
          <div className="px-5 py-5 space-y-4">
            <div className="rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 flex items-center justify-between">
              <span className="text-sm text-amber-700">Current balance</span>
              <span className="flex items-center gap-1 font-bold text-amber-800">
                <Zap className="h-4 w-4 text-amber-500" />{org.credit_balance}
              </span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-500 mb-1.5">Credits to add</label>
              <input
                type="number"
                min={1}
                autoFocus
                placeholder="e.g. 500"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                className="w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-500 mb-1.5">Reason</label>
              <input
                type="text"
                value={reason}
                onChange={e => setReason(e.target.value)}
                className="w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>

            <button
              onClick={handleSubmit}
              disabled={loading || !amount || parseInt(amount) <= 0}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-amber-500 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
            >
              <Zap className="h-4 w-4" />
              {loading ? 'Adding…' : `Add ${amount || '0'} credits`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function SetPlanModal({ org, onClose, onDone }: { org: OrgRow; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<PlanName>(org.plan)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async () => {
    if (plan === org.plan) return
    setLoading(true)
    try {
      const res = await fetch('/api/admin/set-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_id: org.id, plan }),
      })
      if (res.ok) {
        setSuccess(true)
        setTimeout(() => { onDone(); onClose() }, 1200)
      }
    } catch { /* ignore */ }
    setLoading(false)
  }

  const PLANS: { key: PlanName; label: string; credits: string; price: string }[] = [
    { key: 'free',    label: 'Free',    credits: '50 one-time', price: '₹0' },
    { key: 'starter', label: 'Starter', credits: '150/mo',      price: '₹1,999/mo' },
    { key: 'growth',  label: 'Growth',  credits: '500/mo',      price: '₹4,999/mo' },
    { key: 'agency',  label: 'Agency',  credits: '2,000/mo',    price: '₹11,999/mo' },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Change Plan</p>
            <p className="text-sm font-bold text-gray-900">{org.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {success ? (
          <div className="px-5 py-10 flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
              <Check className="h-6 w-6 text-green-600" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Plan updated!</p>
          </div>
        ) : (
          <div className="px-5 py-5 space-y-3">
            {PLANS.map(p => (
              <button
                key={p.key}
                onClick={() => setPlan(p.key)}
                className={`w-full flex items-center justify-between rounded-xl border-2 px-4 py-3 text-left transition-all ${
                  plan === p.key
                    ? 'border-purple-400 bg-purple-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <div>
                  <p className="text-sm font-semibold text-gray-900">{p.label}</p>
                  <p className="text-xs text-gray-400">⚡ {p.credits}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs font-medium text-gray-500">{p.price}</p>
                  {org.plan === p.key && (
                    <span className="text-[10px] font-semibold text-purple-600">Current</span>
                  )}
                </div>
              </button>
            ))}

            <button
              onClick={handleSubmit}
              disabled={loading || plan === org.plan}
              className="w-full rounded-xl bg-purple-600 py-2.5 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50 transition-colors mt-1"
            >
              {loading ? 'Saving…' : `Set to ${plan.charAt(0).toUpperCase() + plan.slice(1)}`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function AdminPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [creditsModal, setCreditsModal] = useState<OrgRow | null>(null)
  const [planModal, setPlanModal] = useState<OrgRow | null>(null)
  const [claiming, setClaiming] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/billing-dashboard')
      if (res.ok) setData(await res.json())
    } catch { /* ignore */ }
    setLoading(false)
  }

  const claimOrg = async (org: OrgRow) => {
    if (!confirm(`Claim "${org.name}" for your account? This will link your Clerk user ID to this org so only you see it.`)) return
    setClaiming(org.id)
    try {
      const res = await fetch('/api/admin/claim-org', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_id: org.id }),
      })
      if (res.ok) {
        await load()
      } else {
        const d = await res.json()
        alert(d.error ?? 'Failed to claim org')
      }
    } catch { alert('Network error') }
    setClaiming(null)
  }

  useEffect(() => { load() }, [])

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-gray-400">
        Loading admin dashboard…
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-red-500">
        Failed to load dashboard data.
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Super Admin</h1>
          <p className="text-sm text-gray-500 mt-1">All client orgs, plans, and credits</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { icon: Users,     color: 'text-gray-400',   label: 'Total Orgs',          value: data.summary.total_orgs },
          { icon: Crown,     color: 'text-purple-500',  label: 'Paying Orgs',         value: data.summary.paying_orgs },
          { icon: Zap,       color: 'text-amber-400',   label: 'Credits Outstanding', value: data.summary.total_credits_outstanding.toLocaleString() },
          { icon: TrendingUp,color: 'text-green-500',   label: 'Est. MRR',            value: `₹${data.summary.mrr_estimate_inr.toLocaleString('en-IN')}` },
        ].map(({ icon: Icon, color, label, value }) => (
          <div key={label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`h-4 w-4 ${color}`} />
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
            </div>
            <p className="text-3xl font-bold text-gray-900">{value}</p>
          </div>
        ))}
      </div>

      {/* Org cards */}
      <div className="space-y-3">
        <h2 className="text-base font-bold text-gray-900">Client Organizations</h2>
        {data.orgs.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white py-12 text-center text-sm text-gray-400">
            No organizations yet. Users sign up via the onboarding flow.
          </div>
        ) : (
          data.orgs.map(org => (
            <div key={org.id} className="rounded-xl border border-gray-200 bg-white px-5 py-4 flex items-center gap-4">
              {/* Org info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-gray-900 truncate">{org.name}</p>
                  {!org.clerk_user_id && (
                    <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
                      Unclaimed
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{org.id.slice(0, 8)}…</p>
              </div>

              {/* Plan badge */}
              <PlanBadge plan={(org.plan as PlanName) ?? 'free'} />

              {/* Credit balance */}
              <div className="flex items-center gap-1.5 rounded-lg bg-amber-50 border border-amber-100 px-3 py-1.5">
                <Zap className="h-4 w-4 text-amber-500" />
                <span className="text-sm font-bold text-amber-800">{org.credit_balance}</span>
                <span className="text-xs text-amber-600">credits</span>
              </div>

              {/* Workspaces */}
              <span className="text-xs text-gray-400 whitespace-nowrap">
                {org.workspace_count} workspace{org.workspace_count !== 1 ? 's' : ''}
              </span>

              {/* Last active */}
              <span className="text-xs text-gray-400 whitespace-nowrap hidden lg:block">
                {org.last_credit_activity
                  ? new Date(org.last_credit_activity).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
                  : 'No activity'}
              </span>

              {/* Actions */}
              <div className="flex items-center gap-2 shrink-0">
                {!org.clerk_user_id && (
                  <button
                    onClick={() => claimOrg(org)}
                    disabled={claiming === org.id}
                    className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50 transition-colors"
                    title="Link this legacy org to your account"
                  >
                    <Link className="h-3.5 w-3.5" />
                    {claiming === org.id ? 'Claiming…' : 'Claim'}
                  </button>
                )}
                <button
                  onClick={() => setCreditsModal(org)}
                  className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-600 transition-colors"
                >
                  <Zap className="h-3.5 w-3.5" />
                  Add Credits
                </button>
                <button
                  onClick={() => setPlanModal(org)}
                  className="flex items-center gap-1.5 rounded-lg border border-purple-200 px-3 py-1.5 text-xs font-semibold text-purple-700 hover:bg-purple-50 transition-colors"
                >
                  <Crown className="h-3.5 w-3.5" />
                  Change Plan
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Modals */}
      {creditsModal && (
        <AddCreditsModal
          org={creditsModal}
          onClose={() => setCreditsModal(null)}
          onDone={load}
        />
      )}
      {planModal && (
        <SetPlanModal
          org={planModal}
          onClose={() => setPlanModal(null)}
          onDone={load}
        />
      )}
    </div>
  )
}
