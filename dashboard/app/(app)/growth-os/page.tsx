import GrowthOSPanel from '@/components/growth-os/GrowthOSPanel'
import SubscriptionUpsellBanner from '@/components/billing/SubscriptionUpsellBanner'
import { Zap } from 'lucide-react'

interface PageProps {
  searchParams: { ws?: string }
}

export default async function GrowthOSPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="p-8 text-center text-gray-500 text-sm">
        No workspace selected. Add <code>?ws=&lt;id&gt;</code> to the URL.
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-4">
      <SubscriptionUpsellBanner workspaceId={workspaceId} />
      <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 w-fit">
        <Zap className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium text-amber-800">10 credits per AI generation · Strategy takes 3–8 minutes</span>
      </div>
      <GrowthOSPanel workspaceId={workspaceId} />
    </div>
  )
}
