import { fetchFromFastAPI } from '@/lib/api'
import CampaignSection from '@/components/campaigns/CampaignSection'
import type { MetaCampaignsResponse, GoogleCampaignsResponse, MetaCampaign, GoogleCampaign } from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string }
}

async function fetchMeta(wsId: string): Promise<MetaCampaignsResponse | null> {
  try {
    const r = await fetchFromFastAPI(`/meta/campaigns?workspace_id=${wsId}`)
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

async function fetchGoogle(wsId: string): Promise<GoogleCampaignsResponse | null> {
  if (process.env.NEXT_PUBLIC_SHOW_GOOGLE !== 'true') return null
  try {
    const r = await fetchFromFastAPI(`/google/campaigns?workspace_id=${wsId}`)
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

export default async function CampaignsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view campaigns</p>
      </div>
    )
  }

  const [metaData, googleData] = await Promise.all([
    fetchMeta(workspaceId),
    fetchGoogle(workspaceId),
  ])

  const metaCampaigns: (MetaCampaign & { _platform: 'meta' })[] = (metaData?.campaigns ?? []).map(c => ({ ...c, _platform: 'meta' as const }))
  const googleCampaigns: (GoogleCampaign & { _platform: 'google' })[] = (googleData?.campaigns ?? []).map(c => ({ ...c, _platform: 'google' as const }))

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Campaigns</h1>
        <p className="text-sm text-gray-500">
          {metaCampaigns.length + googleCampaigns.length} total campaigns
        </p>
      </div>

      <CampaignSection
        title="Meta Campaigns"
        campaigns={metaCampaigns}
        workspaceId={workspaceId}
        emptyMessage={metaData?.error ?? 'No Meta campaigns found'}
      />

      {process.env.NEXT_PUBLIC_SHOW_GOOGLE === 'true' && (
        <CampaignSection
          title="Google Campaigns"
          campaigns={googleCampaigns}
          workspaceId={workspaceId}
          emptyMessage={googleData?.error ?? 'No Google campaigns found'}
        />
      )}
    </div>
  )
}
