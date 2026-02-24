import { fetchFromFastAPI } from '@/lib/api'
import SettingsView from '@/components/settings/SettingsView'
import type { ConnectionsResponse, Workspace } from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string; google_connected?: string; google_error?: string }
}

async function fetchConnections(workspaceId: string): Promise<ConnectionsResponse | null> {
  if (!workspaceId) return null
  try {
    const r = await fetchFromFastAPI(`/settings/connections?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

async function fetchWorkspaces(): Promise<Workspace[]> {
  try {
    const r = await fetchFromFastAPI('/workspace/list')
    if (!r.ok) return []
    const d = await r.json()
    return d.workspaces ?? []
  } catch {
    return []
  }
}

export default async function SettingsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const googleConnected = searchParams.google_connected === '1'
  const googleError = searchParams.google_error

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to manage settings</p>
      </div>
    )
  }

  const [connectionsData, workspaces] = await Promise.all([
    fetchConnections(workspaceId),
    fetchWorkspaces(),
  ])

  const workspace = workspaces.find((w: Workspace) => w.id === workspaceId)
  const workspaceName = workspace?.name ?? workspaceId

  return (
    <SettingsView
      connections={connectionsData?.connections ?? []}
      workspaceId={workspaceId}
      workspaceName={workspaceName}
      googleConnected={googleConnected}
      googleError={googleError}
    />
  )
}
