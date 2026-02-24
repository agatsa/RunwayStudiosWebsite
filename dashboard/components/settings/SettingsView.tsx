'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { CheckCircle, Link2, Trash2, Loader2 } from 'lucide-react'
import MetaConnectDialog from './MetaConnectDialog'
import GoogleConnectDialog from './GoogleConnectDialog'
import YouTubeConnectDialog from './YouTubeConnectDialog'
import type { PlatformConnection } from '@/lib/types'

interface Props {
  connections: PlatformConnection[]
  workspaceId: string
  workspaceName: string
  googleConnected?: boolean
  googleError?: string
  googleOAuthConfigured?: boolean
}

function PlatformCard({
  name,
  connection,
  workspaceId,
  onConnect,
  onDisconnected,
  icon,
  comingSoon,
}: {
  name: string
  connection: PlatformConnection | undefined
  workspaceId: string
  onConnect: () => void
  onDisconnected: () => void
  icon: React.ReactNode
  comingSoon?: boolean
}) {
  const [disconnecting, setDisconnecting] = useState(false)
  const isConnected = !!connection?.has_token

  const handleDisconnect = async () => {
    if (!confirm(`Disconnect ${name}? This will stop campaign management for this platform.`)) return
    setDisconnecting(true)
    try {
      const res = await fetch(`/api/settings/disconnect/${connection!.platform}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      if (!res.ok) throw new Error('Failed')
      toast.success(`${name} disconnected`)
      onDisconnected()
    } catch {
      toast.error(`Failed to disconnect ${name}`)
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="shrink-0">{icon}</div>
          <div>
            <p className="font-semibold text-gray-900">{name}</p>
            {isConnected ? (
              <p className="text-xs text-gray-500">
                {connection?.account_name ?? connection?.account_id ?? 'Connected'}
                {connection?.ad_account_id ? ` · ${connection.ad_account_id}` : ''}
              </p>
            ) : (
              <p className="text-xs text-gray-400">Not connected</p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isConnected ? (
            <>
              <span className="flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
                <CheckCircle className="h-3 w-3" />
                Connected
              </span>
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {disconnecting
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <Trash2 className="h-3 w-3" />}
                Disconnect
              </button>
            </>
          ) : comingSoon ? (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-500">
              Coming soon
            </span>
          ) : (
            <button
              onClick={onConnect}
              className="flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-700"
            >
              <Link2 className="h-3 w-3" />
              Connect
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function SettingsView({ connections, workspaceId, workspaceName, googleConnected, googleError, googleOAuthConfigured = false }: Props) {
  const [showMetaDialog, setShowMetaDialog] = useState(false)
  const [showGoogleDialog, setShowGoogleDialog] = useState(false)
  const [showYouTubeDialog, setShowYouTubeDialog] = useState(false)
  const router = useRouter()

  useEffect(() => {
    if (googleConnected) {
      toast.success('Google Ads connected! YouTube channel auto-discovered if linked.')
    } else if (googleError) {
      const messages: Record<string, string> = {
        access_denied: 'Google sign-in was cancelled.',
        no_refresh_token: 'No refresh token received — please try again.',
        token_exchange_failed: 'Token exchange failed. Check your OAuth credentials.',
        save_failed: 'Failed to save credentials. Check server logs.',
        fastapi_unreachable: 'Could not reach backend server.',
        server_not_configured: 'Google OAuth not configured on server (missing env vars).',
      }
      toast.error(messages[googleError] ?? `Google connect error: ${googleError}`)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const metaConn = connections.find(c => c.platform === 'meta')
  const googleConn = connections.find(c => c.platform === 'google')
  const youtubeConn = connections.find(c => c.platform === 'youtube')

  const refresh = () => router.refresh()

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500">Workspace: {workspaceName}</p>
      </div>

      {/* Platform connections */}
      <section className="space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Platform Connections</h2>
          <p className="text-sm text-gray-500">
            Connect your ad platforms to manage campaigns and view analytics from this dashboard.
          </p>
        </div>

        {/* Meta */}
        <PlatformCard
          name="Meta Ads (Facebook & Instagram)"
          connection={metaConn}
          workspaceId={workspaceId}
          onConnect={() => setShowMetaDialog(true)}
          onDisconnected={refresh}
          icon={
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-lg font-bold text-white">
              f
            </div>
          }
        />

        {/* Google */}
        <PlatformCard
          name="Google Ads + Merchant Center"
          connection={googleConn}
          workspaceId={workspaceId}
          onConnect={() => setShowGoogleDialog(true)}
          onDisconnected={refresh}
          icon={
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 bg-white">
              <svg viewBox="0 0 48 48" className="h-6 w-6">
                <path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
            </div>
          }
        />

        {/* YouTube */}
        <PlatformCard
          name="YouTube Channel Intelligence"
          connection={youtubeConn}
          workspaceId={workspaceId}
          onConnect={() => setShowYouTubeDialog(true)}
          onDisconnected={refresh}
          icon={
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-600">
              <svg viewBox="0 0 24 24" className="h-6 w-6 fill-white">
                <path d="M19.59 6.69a4.83 4.83 0 01-3.77-2.75 12.58 12.58 0 00-7.64 0A4.83 4.83 0 014.41 6.69 48.75 48.75 0 004 12a48.75 48.75 0 00.41 5.31 4.83 4.83 0 003.77 2.75 12.58 12.58 0 007.64 0 4.83 4.83 0 003.77-2.75A48.75 48.75 0 0020 12a48.75 48.75 0 00-.41-5.31zM10 15.5v-7l6 3.5-6 3.5z" />
              </svg>
            </div>
          }
        />
      </section>

      {/* Workspace info */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-gray-900">Workspace</h2>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs text-gray-500">Workspace Name</p>
              <p className="mt-0.5 font-medium text-gray-900">{workspaceName}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Workspace ID</p>
              <p className="mt-0.5 font-mono text-xs text-gray-600 break-all">{workspaceId}</p>
            </div>
          </div>
        </div>
      </section>

      {/* Meta connect dialog */}
      {showMetaDialog && (
        <MetaConnectDialog
          workspaceId={workspaceId}
          onConnected={refresh}
          onClose={() => setShowMetaDialog(false)}
        />
      )}

      {/* Google connect dialog */}
      {showGoogleDialog && (
        <GoogleConnectDialog
          workspaceId={workspaceId}
          onConnected={refresh}
          onClose={() => setShowGoogleDialog(false)}
          oauthConfigured={googleOAuthConfigured}
        />
      )}

      {/* YouTube connect dialog */}
      {showYouTubeDialog && (
        <YouTubeConnectDialog
          workspaceId={workspaceId}
          onConnected={refresh}
          onClose={() => setShowYouTubeDialog(false)}
        />
      )}
    </div>
  )
}
