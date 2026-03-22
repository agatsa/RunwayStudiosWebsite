'use client'

import { useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Link2, Package, CreditCard, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import Link from 'next/link'
import { ExternalLink } from 'lucide-react'

type Tab = 'connect' | 'products' | 'billing' | 'team'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'connect',  label: 'Connect Accounts', icon: Link2     },
  { id: 'products', label: 'Products',          icon: Package   },
  { id: 'billing',  label: 'Billing',           icon: CreditCard },
  { id: 'team',     label: 'Team',              icon: Users      },
]

export default function SetupPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const defaultTab = (searchParams.get('tab') as Tab) ?? 'connect'
  const [activeTab, setActiveTab] = useState<Tab>(defaultTab)

  if (!wsId) {
    return (
      <div className="p-8 text-center text-sm text-gray-500">
        No workspace selected.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300',
            )}
          >
            <tab.icon className="h-4 w-4 shrink-0" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content — delegate to existing pages */}
      {activeTab === 'connect' && (
        <div className="rounded-xl border border-gray-200 bg-white p-1 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Platform Connections</p>
            <Link href={`/settings?ws=${wsId}`} className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
              Full settings <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <PlatformConnectEmbed wsId={wsId} />
        </div>
      )}
      {activeTab === 'products' && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Product Catalog</p>
            <Link href={`/products?ws=${wsId}`} className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
              Full catalog <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="p-4">
            <p className="text-sm text-gray-500">
              Manage your product catalog here. ARIA uses your products to personalise all growth recommendations.
            </p>
            <Link
              href={`/products?ws=${wsId}`}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              Manage products
            </Link>
          </div>
        </div>
      )}
      {activeTab === 'billing' && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Billing & Credits</p>
            <Link href={`/billing?ws=${wsId}`} className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
              Full billing <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="p-4">
            <p className="text-sm text-gray-500">
              Manage your plan, credits, and billing information.
            </p>
            <Link
              href={`/billing?ws=${wsId}`}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              View billing
            </Link>
          </div>
        </div>
      )}
      {activeTab === 'team' && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Team Members</p>
          </div>
          <div className="p-4">
            <p className="text-sm text-gray-500">
              Team member management coming soon. Additional seats available for ₹299/month per person.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// Inline embed of platform connection cards
function PlatformConnectEmbed({ wsId }: { wsId: string }) {
  const platforms = [
    { name: 'Meta Ads', icon: '📘', href: `/settings?ws=${wsId}#meta`, desc: 'Connect your Meta Business account to sync campaign data live' },
    { name: 'Google Ads', icon: '🟢', href: `/settings?ws=${wsId}#google`, desc: 'Connect Google Ads via OAuth for campaign sync and GA4 analytics' },
    { name: 'YouTube', icon: '▶️', href: `/settings?ws=${wsId}#youtube`, desc: 'Link your YouTube channel for content intelligence and competitor analysis' },
    { name: 'Shopify', icon: '🛍️', href: `/settings?ws=${wsId}#shopify`, desc: 'Connect your Shopify store to auto-sync your product catalog' },
  ]

  return (
    <div className="p-4 grid grid-cols-2 gap-3">
      {platforms.map(p => (
        <Link
          key={p.name}
          href={p.href}
          className="flex gap-3 rounded-xl border border-gray-100 bg-gray-50 p-4 hover:border-brand-200 hover:bg-white transition-all group"
        >
          <span className="text-xl shrink-0">{p.icon}</span>
          <div>
            <p className="text-sm font-semibold text-gray-900">{p.name}</p>
            <p className="text-xs text-gray-500 mt-0.5">{p.desc}</p>
          </div>
        </Link>
      ))}
    </div>
  )
}
