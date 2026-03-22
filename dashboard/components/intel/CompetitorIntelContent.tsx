'use client'

import { useState } from 'react'
import { BarChart2, PlayCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import BrandIntelPanel from '@/components/competitor-intel/BrandIntelPanel'
import dynamic from 'next/dynamic'

const YouTubeCompetitorIntel = dynamic(
  () => import('@/components/youtube/YouTubeCompetitorIntel'),
  { ssr: false }
)

type SubTab = 'brand' | 'youtube'

export default function CompetitorIntelContent({ wsId }: { wsId: string }) {
  const [sub, setSub] = useState<SubTab>('brand')

  return (
    <div className="space-y-4">
      {/* Sub-tab pills */}
      <div className="flex gap-2">
        <button
          onClick={() => setSub('brand')}
          className={cn(
            'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
            sub === 'brand'
              ? 'bg-brand-600 text-white'
              : 'border border-gray-200 text-gray-600 hover:bg-gray-50',
          )}
        >
          <BarChart2 className="h-3.5 w-3.5" />
          Brand & Ad Intel
        </button>
        <button
          onClick={() => setSub('youtube')}
          className={cn(
            'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
            sub === 'youtube'
              ? 'bg-brand-600 text-white'
              : 'border border-gray-200 text-gray-600 hover:bg-gray-50',
          )}
        >
          <PlayCircle className="h-3.5 w-3.5" />
          YouTube Competitors
        </button>
      </div>

      {sub === 'brand'   && <BrandIntelPanel workspaceId={wsId} />}
      {sub === 'youtube' && <YouTubeCompetitorIntel workspaceId={wsId} />}
    </div>
  )
}
