'use client'

import { useState, Suspense, useRef, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import { Crosshair, Layout, MessageSquare, Library, Loader2, X, Users } from 'lucide-react'
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
const AdLibraryContent = dynamic(
  () => import('@/components/intel/AdLibraryContent'),
  { ssr: false, loading: () => <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading...</div> }
)
const VoCContent = dynamic(
  () => import('@/components/intel/VoCContent'),
  { ssr: false, loading: () => <div className="flex items-center justify-center py-16 text-sm text-gray-400">Loading...</div> }
)

type Tab = 'competitors' | 'lp_audit' | 'comments' | 'ad_library' | 'voc'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'competitors', label: 'Competitor Intel', icon: Crosshair      },
  { id: 'ad_library',  label: 'Ad Library',       icon: Library        },
  { id: 'voc',         label: 'Voice of Customer', icon: Users         },
  { id: 'lp_audit',   label: 'LP Audit',          icon: Layout         },
  { id: 'comments',   label: 'Comments & Reviews', icon: MessageSquare },
]

export default function IntelPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <IntelContent />
    </Suspense>
  )
}

function IntelContent() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const defaultTab = (searchParams.get('tab') as Tab) ?? 'competitors'
  const [activeTab, setActiveTab] = useState<Tab>(defaultTab)

  // Shared ad-library search status — lifted up so it survives tab switches
  const [adLibRunning, setAdLibRunning] = useState(false)
  const adLibStopRef = useRef<(() => void) | null>(null)

  const handleAdLibStop = useCallback(() => {
    adLibStopRef.current?.()
    setAdLibRunning(false)
  }, [])

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
      <div className="flex items-center gap-1 border-b border-gray-200">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300',
              tab.id === 'ad_library' && adLibRunning && activeTab !== 'ad_library'
                ? 'text-indigo-600'
                : '',
            )}
          >
            <tab.icon className="h-4 w-4 shrink-0" />
            {tab.label}
            {tab.id === 'ad_library' && adLibRunning && (
              <Loader2 className="h-3 w-3 animate-spin text-indigo-500" />
            )}
          </button>
        ))}

        {/* Running search badge with stop button */}
        {adLibRunning && activeTab !== 'ad_library' && (
          <div className="ml-auto flex items-center gap-1.5 rounded-full bg-indigo-50 border border-indigo-200 px-3 py-1 text-xs font-medium text-indigo-700">
            <Loader2 className="h-3 w-3 animate-spin" />
            Ad Library search running
            <button
              onClick={handleAdLibStop}
              className="ml-1 rounded-full hover:bg-indigo-100 p-0.5"
              title="Stop search"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {/* Content — AdLibraryContent stays mounted (hidden) to preserve search state */}
      {activeTab === 'competitors' && <CompetitorIntelContent wsId={wsId} />}
      <div style={{ display: activeTab === 'ad_library' ? 'block' : 'none' }}>
        <AdLibraryContent
          wsId={wsId}
          onRunningChange={setAdLibRunning}
          stopRef={adLibStopRef}
        />
      </div>
      {activeTab === 'voc'       && <VoCContent         wsId={wsId} />}
      {activeTab === 'lp_audit'  && <LandingPageContent wsId={wsId} />}
      {activeTab === 'comments'  && <CommentsContent    wsId={wsId} />}
    </div>
  )
}
