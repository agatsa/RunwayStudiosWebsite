'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { toast } from 'sonner'
import { CheckCircle, Link2, Trash2, Loader2, RefreshCw, ShoppingBag, Crown, Lock, Youtube, Building2, MonitorSmartphone } from 'lucide-react'
import MetaConnectDialog from './MetaConnectDialog'
import GoogleConnectDialog from './GoogleConnectDialog'
import GoogleAccountSelectDialog from './GoogleAccountSelectDialog'
import YouTubeConnectDialog from './YouTubeConnectDialog'
import ExcelUploadDialog from './ExcelUploadDialog'
import MetaCompetitorPages from './MetaCompetitorPages'
import type { PlatformConnection, PlanName } from '@/lib/types'

interface Props {
  connections: PlatformConnection[]
  workspaceId: string
  workspaceName: string
  googleConnected?: boolean
  googleError?: string
  googleOAuthConfigured?: boolean
  ga4PropertyId?: string | null
  ga4Connected?: boolean
  metaConnected?: boolean
  metaSession?: string
  metaError?: string
}

function PlatformCard({
  name,
  connection,
  workspaceId,
  onConnect,
  onDisconnected,
  icon,
  comingSoon,
  planRequired,
  approvalPending,
}: {
  name: string
  connection: PlatformConnection | undefined
  workspaceId: string
  onConnect: () => void
  onDisconnected: () => void
  icon: React.ReactNode
  comingSoon?: boolean
  planRequired?: string   // e.g. "Starter" or "Growth" — if set and not connected, shows lock UI
  approvalPending?: boolean
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
              <div>
                <p className="text-xs text-gray-500">
                  {connection?.account_name ?? connection?.account_id ?? 'Connected'}
                  {connection?.ad_account_id ? ` · ${connection.ad_account_id}` : ''}
                </p>
                {connection?.account_name && connection?.account_id && connection.account_name !== connection.account_id && (
                  <p className="text-[10px] text-gray-400 font-mono mt-0.5">{connection.account_id}</p>
                )}
              </div>
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
          ) : approvalPending ? (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-500">
              Coming Soon
            </span>
          ) : comingSoon ? (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-500">
              Coming soon
            </span>
          ) : planRequired ? (
            <button
              onClick={onConnect}
              className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
            >
              <Lock className="h-3 w-3" />
              {planRequired}+ Required
            </button>
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

export default function SettingsView({ connections, workspaceId, workspaceName, googleConnected, googleError, googleOAuthConfigured = false, ga4PropertyId, ga4Connected = false, metaConnected, metaSession, metaError }: Props) {
  const [showMetaDialog, setShowMetaDialog] = useState(false)
  const [showGoogleDialog, setShowGoogleDialog] = useState(false)
  const [showYouTubeDialog, setShowYouTubeDialog] = useState(false)
  const [showGoogleAccountSelect, setShowGoogleAccountSelect] = useState(false)
  const [showUpload, setShowUpload] = useState<'meta' | 'google' | null>(null)
  const [plan, setPlan] = useState<PlanName | null>(null)
  const [planGate, setPlanGate] = useState<{ platform: string; required: string } | null>(null)
  const [workspaceType, setWorkspaceType] = useState<string | null>(null)
  const [savingType, setSavingType] = useState(false)
  const router = useRouter()

  // Fetch billing plan + workspace type on mount
  useEffect(() => {
    if (!workspaceId) return
    fetch(`/api/billing/status?workspace_id=${workspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.plan) setPlan(d.plan) })
      .catch(() => {})
    fetch(`/api/workspace?workspace_id=${workspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.workspace_type) setWorkspaceType(d.workspace_type) })
      .catch(() => {})
  }, [workspaceId])

  const [resettingOnboarding, setResettingOnboarding] = useState(false)

  const handleResetOnboarding = async () => {
    if (!confirm('This will re-show the ARIA setup wizard on next page load. Continue?')) return
    setResettingOnboarding(true)
    try {
      await fetch('/api/workspace/reset-onboarding', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      toast.success('Setup wizard reset — reload to see it')
      router.refresh()
    } catch {
      toast.error('Failed to reset')
    } finally {
      setResettingOnboarding(false)
    }
  }

  const handleSaveWorkspaceType = async (type: string) => {
    setWorkspaceType(type)
    setSavingType(true)
    try {
      await fetch('/api/workspace/type', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, workspace_type: type }),
      })
      toast.success('Business type updated')
    } catch {
      toast.error('Failed to save')
    } finally {
      setSavingType(false)
    }
  }

  // Plan-gate helpers
  const isStarterLocked = plan === 'free'                                    // Meta, Google require Starter+
  const isGrowthLocked  = plan === 'free' || plan === 'starter'              // YouTube requires Growth+

  const handleMetaConnect = () => {
    if (isStarterLocked) { setPlanGate({ platform: 'Meta Ads', required: 'Starter' }); return }
    setShowMetaDialog(true)
  }
  const handleGoogleConnect = () => {
    if (isStarterLocked) { setPlanGate({ platform: 'Google Ads', required: 'Starter' }); return }
    setShowGoogleDialog(true)
  }
  const handleYouTubeConnect = () => {
    if (isGrowthLocked) { setPlanGate({ platform: 'YouTube', required: 'Growth' }); return }
    setShowYouTubeDialog(true)
  }

  useEffect(() => {
    if (googleConnected) {
      toast.success('Google Ads connected! YouTube + GA4 auto-discovered if linked.')
    } else if (googleError) {
      const messages: Record<string, string> = {
        access_denied: 'Google sign-in was cancelled.',
        no_refresh_token: 'No refresh token — please try again (select your Google account fresh).',
        token_exchange_failed: 'Token exchange failed. Check your OAuth credentials.',
        no_ads_account: 'No Google Ads account found for this Google account. Make sure Google Ads is active.',
        save_failed: 'Failed to save credentials. Contact support if this persists.',
        fastapi_unreachable: 'Could not reach backend server.',
        server_not_configured: 'Google OAuth not configured on server (missing env vars).',
      }
      toast.error(messages[googleError] ?? `Google connect error: ${googleError}`)
    }
    // Meta OAuth result
    if (metaConnected) {
      toast.success('Meta Ads connected!')
      router.refresh()
    } else if (metaSession) {
      // Multiple ad accounts — auto-open dialog in session mode
      setShowMetaDialog(true)
    } else if (metaError) {
      const metaErrMessages: Record<string, string> = {
        missing_params: 'Missing OAuth parameters — please try again.',
        server_error: 'Server error during Meta OAuth. Please try again.',
      }
      toast.error(metaErrMessages[metaError] ?? `Meta connect error: ${decodeURIComponent(metaError)}`)
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
          onConnect={handleMetaConnect}
          onDisconnected={refresh}
          approvalPending={!metaConn?.has_token}
          icon={
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-lg font-bold text-white">
              f
            </div>
          }
        />
        {!metaConn?.has_token && (
          <div className="flex justify-end -mt-2 px-1">
            <button
              onClick={() => setShowUpload('meta')}
              className="text-xs text-blue-600 underline hover:text-blue-800"
            >
              Upload Excel instead
            </button>
          </div>
        )}

        {/* Google */}
        <PlatformCard
          name="Google Ads + Merchant Center"
          connection={googleConn}
          workspaceId={workspaceId}
          onConnect={handleGoogleConnect}
          onDisconnected={refresh}
          approvalPending={!googleConn?.has_token}
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
        {googleConn?.has_token ? (
          <div className="flex justify-end -mt-2 px-1">
            <button
              onClick={() => setShowGoogleAccountSelect(true)}
              className="text-xs text-gray-500 underline hover:text-gray-700"
            >
              Switch Account
            </button>
          </div>
        ) : (
          <div className="flex justify-end -mt-2 px-1">
            <button
              onClick={() => setShowUpload('google')}
              className="text-xs text-blue-600 underline hover:text-blue-800"
            >
              Upload Excel instead
            </button>
          </div>
        )}

        {/* YouTube */}
        <PlatformCard
          name="YouTube Channel Intelligence"
          connection={youtubeConn}
          workspaceId={workspaceId}
          onConnect={handleYouTubeConnect}
          onDisconnected={refresh}
          planRequired={!youtubeConn?.has_token && isGrowthLocked ? 'Growth' : undefined}
          icon={
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-600">
              <svg viewBox="0 0 24 24" className="h-6 w-6 fill-white">
                <path d="M19.59 6.69a4.83 4.83 0 01-3.77-2.75 12.58 12.58 0 00-7.64 0A4.83 4.83 0 014.41 6.69 48.75 48.75 0 004 12a48.75 48.75 0 00.41 5.31 4.83 4.83 0 003.77 2.75 12.58 12.58 0 007.64 0 4.83 4.83 0 003.77-2.75A48.75 48.75 0 0020 12a48.75 48.75 0 00-.41-5.31zM10 15.5v-7l6 3.5-6 3.5z" />
              </svg>
            </div>
          }
        />

        {/* GA4 — auto-discovered via Google OAuth */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-500 text-white font-bold text-sm shrink-0">
                GA4
              </div>
              <div>
                <p className="font-semibold text-gray-900">Google Analytics 4</p>
                {ga4Connected && ga4PropertyId ? (
                  <p className="text-xs text-gray-500">Property ID: {ga4PropertyId} · Auto-discovered</p>
                ) : (
                  <p className="text-xs text-gray-400">Available once Google Ads API is approved</p>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {ga4Connected ? (
                <span className="flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
                  <CheckCircle className="h-3 w-3" />
                  Connected
                </span>
              ) : (
                <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-500">
                  Coming Soon
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Workspace info */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-gray-900">Workspace</h2>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="grid grid-cols-2 gap-4 text-sm mb-4">
            <div>
              <p className="text-xs text-gray-500">Workspace Name</p>
              <p className="mt-0.5 font-medium text-gray-900">{workspaceName}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Workspace ID</p>
              <p className="mt-0.5 font-mono text-xs text-gray-600 break-all">{workspaceId}</p>
            </div>
          </div>
          <button
            onClick={handleResetOnboarding}
            disabled={resettingOnboarding}
            className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-100 transition-colors disabled:opacity-50"
          >
            {resettingOnboarding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Re-run ARIA Setup Wizard
          </button>
        </div>
      </section>

      {/* Business type */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Business Type</h2>
          <p className="text-sm text-gray-500">ARIA personalises your Growth OS, competitor intel and recommendations based on this.</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {([
              { key: 'd2c',     icon: ShoppingBag,      label: 'D2C Brand',       desc: 'Selling products via ads',       accent: 'text-blue-600',   bg: 'bg-blue-50',   border: 'border-blue-500' },
              { key: 'creator', icon: Youtube,           label: 'Creator',         desc: 'Growing a YouTube channel',      accent: 'text-red-600',    bg: 'bg-red-50',    border: 'border-red-500' },
              { key: 'agency',  icon: Building2,         label: 'Agency',          desc: 'Managing client accounts',       accent: 'text-purple-600', bg: 'bg-purple-50', border: 'border-purple-500' },
              { key: 'saas',    icon: MonitorSmartphone, label: 'SaaS / App',      desc: 'Driving signups & subs',         accent: 'text-emerald-600',bg: 'bg-emerald-50',border: 'border-emerald-500' },
            ] as const).map(bt => {
              const Icon = bt.icon
              const selected = workspaceType === bt.key
              return (
                <button
                  key={bt.key}
                  onClick={() => handleSaveWorkspaceType(bt.key)}
                  disabled={savingType}
                  className={`relative flex flex-col items-start gap-2 rounded-xl border-2 p-3 text-left transition-all ${
                    selected ? `${bt.border} ${bt.bg}` : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {selected && <CheckCircle className={`absolute top-2.5 right-2.5 h-3.5 w-3.5 ${bt.accent}`} />}
                  <Icon className={`h-5 w-5 ${selected ? bt.accent : 'text-gray-400'}`} />
                  <div>
                    <p className={`text-xs font-semibold ${selected ? 'text-gray-900' : 'text-gray-700'}`}>{bt.label}</p>
                    <p className="text-[10px] text-gray-400 leading-tight mt-0.5">{bt.desc}</p>
                  </div>
                </button>
              )
            })}
          </div>
          {savingType && <p className="mt-2 text-xs text-gray-400 flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Saving…</p>}
        </div>
      </section>

      {/* Products & Competitor Tracking */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Competitor Tracking</h2>
          <p className="text-sm text-gray-500">Track competitor Facebook/Meta ad pages.</p>
        </div>
        <MetaCompetitorPages workspaceId={workspaceId} />
      </section>

      {/* Coming soon integrations */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Future Integrations</h2>
          <p className="text-sm text-gray-500">These will be available in upcoming releases</p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[
            { name: 'Email (Klaviyo / Mailchimp)', desc: 'Revenue per email, sequence optimization, repeat purchase attribution', color: 'indigo' },
            { name: 'Marketplace (Amazon / Flipkart)', desc: 'BSR tracking, review velocity, buy box intelligence', color: 'amber' },
            { name: 'Search Console', desc: 'Brand search lift, keyword growth trends, geographic demand map', color: 'emerald' },
              ].map(({ name, desc, color }) => (
            <div key={name} className={`rounded-xl border border-${color}-200 bg-${color}-50/30 p-4`}>
              <p className="text-sm font-semibold text-gray-900">{name}</p>
              <p className="text-xs text-gray-500 mt-1">{desc}</p>
              <span className={`mt-2 inline-block rounded-full bg-${color}-100 px-2 py-0.5 text-[10px] font-semibold text-${color}-700`}>Coming Soon</span>
            </div>
          ))}
        </div>
      </section>

      {/* Meta connect dialog */}
      {showMetaDialog && (
        <MetaConnectDialog
          workspaceId={workspaceId}
          onConnected={refresh}
          onClose={() => setShowMetaDialog(false)}
          sessionId={metaSession}
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

      {/* Google account switcher */}
      {showGoogleAccountSelect && (
        <GoogleAccountSelectDialog
          workspaceId={workspaceId}
          onSuccess={refresh}
          onClose={() => setShowGoogleAccountSelect(false)}
        />
      )}

      {/* Excel upload dialog */}
      {showUpload && (
        <ExcelUploadDialog
          workspaceId={workspaceId}
          platform={showUpload}
          onSuccess={() => { setShowUpload(null); refresh() }}
          onClose={() => setShowUpload(null)}
        />
      )}

      {/* Plan gate upgrade modal */}
      {planGate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl overflow-hidden">
            <div className="bg-gradient-to-br from-amber-400 to-orange-500 px-6 py-8 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/20 mx-auto mb-3">
                <Crown className="h-7 w-7 text-white" />
              </div>
              <h3 className="text-xl font-bold text-white">{planGate.required} Plan Required</h3>
              <p className="text-sm text-white/80 mt-1">
                Connecting {planGate.platform} requires the {planGate.required} plan or higher
              </p>
            </div>
            <div className="px-6 py-5 space-y-4">
              <div className="rounded-xl bg-gray-50 border border-gray-100 px-4 py-3 text-sm text-gray-600">
                You&apos;re on the <strong className="text-gray-900 capitalize">{plan ?? 'Free'}</strong> plan.
                {planGate.required === 'Starter'
                  ? ' Upgrade to Starter (₹1,999/mo) to connect Meta Ads and Google Ads.'
                  : ' Upgrade to Growth (₹4,999/mo) to connect YouTube.'}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setPlanGate(null)}
                  className="flex-1 rounded-xl border border-gray-200 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <Link
                  href={`/billing?ws=${workspaceId}`}
                  onClick={() => setPlanGate(null)}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl bg-amber-500 py-2.5 text-sm font-semibold text-white hover:bg-amber-600"
                >
                  <Crown className="h-4 w-4" />
                  View Plans
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
