'use client'

import { useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { Sparkles, CheckSquare, ClipboardList, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import dynamic from 'next/dynamic'

const GrowthOSPanel = dynamic(() => import('@/components/growth-os/GrowthOSPanel'), { ssr: false })
const ApprovalQueueTab = dynamic(() => import('@/components/plan/ApprovalQueueTab'), { ssr: false })
const CampaignPlannerTab = dynamic(() => import('@/components/plan/CampaignPlannerTab'), { ssr: false })

type Tab = 'strategy' | 'approvals' | 'briefs'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'strategy',  label: 'Growth Strategy', icon: Sparkles    },
  { id: 'approvals', label: 'Approvals',        icon: CheckSquare },
  { id: 'briefs',    label: 'Campaign Briefs',  icon: ClipboardList },
]

export default function PlanPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <PlanContent />
    </Suspense>
  )
}

function PlanContent() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const defaultTab = (searchParams.get('tab') as Tab) ?? 'strategy'
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
      {activeTab === 'strategy' && (
        <div>
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 w-fit">
            <Zap className="h-4 w-4 text-amber-500" />
            <span className="text-sm font-medium text-amber-800">10 credits per AI generation · Strategy takes 3–8 minutes</span>
          </div>
          <GrowthOSPanel workspaceId={wsId} />
        </div>
      )}
      {activeTab === 'approvals' && <ApprovalQueueTab wsId={wsId} />}
      {activeTab === 'briefs'    && <CampaignPlannerTab wsId={wsId} />}
    </div>
  )
}
