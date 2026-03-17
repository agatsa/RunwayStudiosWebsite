'use client'

import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import { Mail, Globe, Users, Send, BarChart2, AlertCircle, Zap } from 'lucide-react'
import DomainSetupWizard from '@/components/email/DomainSetupWizard'
import ContactListManager from '@/components/email/ContactListManager'
import CampaignBuilder from '@/components/email/CampaignBuilder'
import CampaignStats from '@/components/email/CampaignStats'
import type { EmailDomain, EmailList, EmailCampaign, EmailQuota } from '@/lib/types'
import PageLoader from '@/components/ui/PageLoader'

type Tab = 'domains' | 'contacts' | 'compose' | 'campaigns'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'domains',   label: 'Domains',         icon: Globe },
  { id: 'contacts',  label: 'Contact Lists',   icon: Users },
  { id: 'compose',   label: 'New Campaign',    icon: Send },
  { id: 'campaigns', label: 'Campaigns',       icon: BarChart2 },
]

export default function EmailPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''

  const [tab, setTab] = useState<Tab>('domains')
  const [domains, setDomains] = useState<EmailDomain[]>([])
  const [lists, setLists] = useState<EmailList[]>([])
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([])
  const [quota, setQuota] = useState<EmailQuota | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshDomains = useCallback(async () => {
    if (!wsId) return
    const res = await fetch(`/api/email/domain?workspace_id=${wsId}`)
    const data = await res.json()
    setDomains(data.domains ?? [])
  }, [wsId])

  const refreshLists = useCallback(async () => {
    if (!wsId) return
    const res = await fetch(`/api/email/lists?workspace_id=${wsId}`)
    const data = await res.json()
    setLists(data.lists ?? [])
  }, [wsId])

  const refreshCampaigns = useCallback(async () => {
    if (!wsId) return
    const res = await fetch(`/api/email/campaigns?workspace_id=${wsId}`)
    const data = await res.json()
    setCampaigns(data.campaigns ?? [])
  }, [wsId])

  const refreshQuota = useCallback(async () => {
    if (!wsId) return
    const res = await fetch(`/api/email/quota?workspace_id=${wsId}`)
    if (res.ok) {
      const data = await res.json()
      setQuota(data)
    }
  }, [wsId])

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshDomains(), refreshLists(), refreshCampaigns(), refreshQuota()])
  }, [refreshDomains, refreshLists, refreshCampaigns, refreshQuota])

  useEffect(() => {
    if (!wsId) return
    setLoading(true)
    refreshAll().finally(() => setLoading(false))
  }, [wsId, refreshAll])

  const verifiedDomains = domains.filter(d => d.verified)

  if (loading) return <PageLoader section="Email" />

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600">
            <Mail className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Email Marketing</h1>
            <p className="text-sm text-gray-500">Send campaigns from your own domain · Powered by Resend</p>
          </div>
        </div>

        {quota && (
          <div className="flex items-center gap-4">
            {quota.monthly_limit === 0 ? (
              <div className="flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs font-medium text-amber-700">
                <AlertCircle className="h-3.5 w-3.5" />
                No email plan — upgrade to send
              </div>
            ) : (
              <div className="text-right">
                <p className="text-xs font-medium text-gray-900">
                  {quota.monthly_used.toLocaleString()} / {quota.monthly_limit.toLocaleString()} emails sent
                </p>
                <div className="mt-1 h-1.5 w-32 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${Math.min(100, (quota.monthly_used / quota.monthly_limit) * 100)}%` }}
                  />
                </div>
                <p className="text-[10px] text-gray-400 mt-0.5">Resets {new Date(quota.reset_date).toLocaleDateString()}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Quick setup nudge */}
      {!loading && verifiedDomains.length === 0 && (
        <div
          onClick={() => setTab('domains')}
          className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 cursor-pointer hover:bg-amber-100 transition-colors"
        >
          <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800">Set up a sending domain first</p>
            <p className="text-xs text-amber-600 mt-0.5">
              Add your domain and configure DNS records to send emails from your own address (e.g. hello@yourbrand.com).
              <span className="ml-1 font-medium underline">Go to Domains →</span>
            </p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-1">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === id
                  ? 'border-indigo-500 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
              {id === 'campaigns' && campaigns.length > 0 && (
                <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                  {campaigns.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div>
        {loading ? (
          <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading…</div>
        ) : tab === 'domains' ? (
          <DomainSetupWizard wsId={wsId} domains={domains} onRefresh={refreshDomains} />
        ) : tab === 'contacts' ? (
          <ContactListManager wsId={wsId} lists={lists} onRefresh={refreshLists} />
        ) : tab === 'compose' ? (
          lists.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-gray-200 p-10 text-center space-y-3">
              <Users className="h-10 w-10 text-gray-300 mx-auto" />
              <p className="text-sm font-medium text-gray-700">You need at least one contact list before creating a campaign.</p>
              <button
                onClick={() => setTab('contacts')}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Create a Contact List
              </button>
            </div>
          ) : (
            <CampaignBuilder
              wsId={wsId}
              domains={domains}
              lists={lists}
              onCreated={() => { refreshCampaigns(); setTab('campaigns') }}
            />
          )
        ) : (
          <CampaignStats wsId={wsId} campaigns={campaigns} onRefresh={refreshCampaigns} />
        )}
      </div>
    </div>
  )
}
