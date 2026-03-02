import { fetchFromFastAPI } from '@/lib/api'
import GrowthOSPanel from '@/components/growth-os/GrowthOSPanel'
import { Zap } from 'lucide-react'

interface PageProps {
  searchParams: { ws?: string }
}

async function fetchLatestPlan(workspaceId: string) {
  try {
    const r = await fetchFromFastAPI(`/growth-os/latest?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
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

  const plan = await fetchLatestPlan(workspaceId)

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-4">
      {/* Credit cost chip */}
      <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 w-fit">
        <Zap className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium text-amber-800">10 credits per AI generation</span>
      </div>
      <GrowthOSPanel workspaceId={workspaceId} initialPlan={plan} />
    </div>
  )
}
