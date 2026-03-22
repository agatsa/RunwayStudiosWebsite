'use client'

import { useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Crosshair, Layout, MessageSquare, TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import dynamic from 'next/dynamic'

// Import existing page content components
const CompetitorIntelContent = dynamic(
  () => import('@/components/intel/CompetitorIntelContent'),
  { ssr: false, loading: () => <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading...</div> }
)
const LandingPageContent = dynamic(
  () => import('@/components/intel/LandingPageContent'),
  { ssr: false, loading: () => <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading...</div> }
)
const CommentsContent = dynamic(
  () => import('@/components/intel/CommentsContent'),
  { ssr: false, loading: () => <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading...</div> }
)

type Tab = 'competitors' | 'lp_audit' | 'comments'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'competitors', label: 'Competitor Intel', icon: Crosshair    },
  { id: 'lp_audit',   label: 'LP Audit',          icon: Layout       },
  { id: 'comments',   label: 'Comments & Reviews', icon: MessageSquare },
]

export default function IntelPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const defaultTab = (searchParams.get('tab') as Tab) ?? 'competitors'
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

      {/* Content */}
      {activeTab === 'competitors' && <CompetitorIntelContent wsId={wsId} />}
      {activeTab === 'lp_audit'   && <LandingPageContent     wsId={wsId} />}
      {activeTab === 'comments'   && <CommentsContent         wsId={wsId} />}
    </div>
  )
}
