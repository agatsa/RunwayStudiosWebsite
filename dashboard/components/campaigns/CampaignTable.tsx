import CampaignRow from './CampaignRow'
import type { MetaCampaign, GoogleCampaign } from '@/lib/types'

type EnrichedCampaign = (MetaCampaign | GoogleCampaign) & { _platform: 'meta' | 'google' }

interface Props {
  campaigns: EnrichedCampaign[]
  workspaceId: string
  title: string
  emptyMessage?: string
}

export default function CampaignTable({ campaigns, workspaceId, title, emptyMessage }: Props) {
  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-gray-700">{title}</h2>
      {campaigns.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
          <p className="text-sm text-gray-400">{emptyMessage ?? 'No campaigns'}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="py-3 pl-4 pr-4 text-left text-xs font-medium uppercase text-gray-500">Campaign</th>
                <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Daily Budget</th>
                <th className="py-3 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map(c => (
                <CampaignRow key={`${c._platform}-${c.id}`} campaign={c} workspaceId={workspaceId} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
