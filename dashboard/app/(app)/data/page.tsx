'use client'

import { useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { Megaphone, BarChart2, PlayCircle, ShoppingBag, Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

// Lazy-load existing page content as iframes would be overkill — import existing components
import dynamic from 'next/dynamic'

// We dynamically re-use existing page components in tabs
const MetaCampaignsContent = dynamic(() => import('@/components/data/MetaTabContent'), { ssr: false })
const GoogleAdsContent = dynamic(() => import('@/components/data/GoogleTabContent'), { ssr: false })
const YouTubeContent = dynamic(() => import('@/components/data/YouTubeTabContent'), { ssr: false })
const MarketplaceContent = dynamic(() => import('@/components/data/MarketplaceTabContent'), { ssr: false })
const UploadContent = dynamic(() => import('@/components/data/UploadTabContent'), { ssr: false })

type Tab = 'meta' | 'google' | 'youtube' | 'marketplace' | 'upload'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'meta',        label: 'Meta Ads',   icon: Megaphone   },
  { id: 'google',      label: 'Google Ads', icon: BarChart2   },
  { id: 'youtube',     label: 'YouTube',    icon: PlayCircle  },
  { id: 'marketplace', label: 'Marketplace',icon: ShoppingBag },
  { id: 'upload',      label: 'Upload',     icon: Upload      },
]

export default function DataPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <DataContent />
    </Suspense>
  )
}

function DataContent() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const defaultTab = (searchParams.get('tab') as Tab) ?? 'meta'
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
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors',
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

      {/* Tab content */}
      <div>
        {activeTab === 'meta'        && <MetaCampaignsContent wsId={wsId} />}
        {activeTab === 'google'      && <GoogleAdsContent     wsId={wsId} />}
        {activeTab === 'youtube'     && <YouTubeContent        wsId={wsId} />}
        {activeTab === 'marketplace' && <MarketplaceContent    wsId={wsId} />}
        {activeTab === 'upload'      && <UploadContent         wsId={wsId} />}
      </div>
    </div>
  )
}
