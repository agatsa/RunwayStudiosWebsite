'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { CheckCircle, Link2, Trash2, Loader2, RefreshCw, ShoppingBag } from 'lucide-react'
import MetaConnectDialog from './MetaConnectDialog'
import GoogleConnectDialog from './GoogleConnectDialog'
import GoogleAccountSelectDialog from './GoogleAccountSelectDialog'
import YouTubeConnectDialog from './YouTubeConnectDialog'
import ShopifyConnectDialog from './ShopifyConnectDialog'
import ExcelUploadDialog from './ExcelUploadDialog'
import ProductUrlsSection from './ProductUrlsSection'
import type { PlatformConnection } from '@/lib/types'

interface Props {
  connections: PlatformConnection[]
  workspaceId: string
  workspaceName: string
  googleConnected?: boolean
  googleError?: string
  googleOAuthConfigured?: boolean
  ga4PropertyId?: string | null
  ga4Connected?: boolean
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

export default function SettingsView({ connections, workspaceId, workspaceName, googleConnected, googleError, googleOAuthConfigured = false, ga4PropertyId, ga4Connected = false }: Props) {
  const [showMetaDialog, setShowMetaDialog] = useState(false)
  const [showGoogleDialog, setShowGoogleDialog] = useState(false)
  const [showYouTubeDialog, setShowYouTubeDialog] = useState(false)
  const [showShopifyDialog, setShowShopifyDialog] = useState(false)
  const [showGoogleAccountSelect, setShowGoogleAccountSelect] = useState(false)
  const [showUpload, setShowUpload] = useState<'meta' | 'google' | null>(null)
  const [shopifyStatus, setShopifyStatus] = useState<{ connected: boolean; shop_domain?: string; shop_name?: string; synced_at?: string; products_count?: number } | null>(null)
  const [shopifyLoading, setShopifyLoading] = useState(false)
  const router = useRouter()

  const fetchShopifyStatus = useCallback(async () => {
    if (!workspaceId) return
    try {
      const r = await fetch(`/api/shopify/status?workspace_id=${workspaceId}`)
      if (r.ok) setShopifyStatus(await r.json())
    } catch { /* ignore */ }
  }, [workspaceId])

  const handleShopifySync = async () => {
    setShopifyLoading(true)
    try {
      const r = await fetch('/api/shopify/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail ?? 'Sync failed')
      toast.success(`Synced ${d.products_synced} products from Shopify`)
      fetchShopifyStatus()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setShopifyLoading(false)
    }
  }

  const handleShopifyDisconnect = async () => {
    if (!confirm('Disconnect Shopify? Product catalog will no longer auto-sync.')) return
    setShopifyLoading(true)
    try {
      const r = await fetch('/api/shopify/disconnect', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      if (!r.ok) throw new Error('Failed')
      toast.success('Shopify disconnected')
      setShopifyStatus({ connected: false })
    } catch {
      toast.error('Failed to disconnect Shopify')
    } finally {
      setShopifyLoading(false)
    }
  }

  useEffect(() => {
    fetchShopifyStatus()
  }, [fetchShopifyStatus])

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
    // Shopify OAuth result toasts
    const params = new URLSearchParams(window.location.search)
    if (params.get('shopify_connected') === '1') {
      toast.success('Shopify store connected! Products are syncing now.')
      fetchShopifyStatus()
    }
    const shopifyError = params.get('shopify_error')
    if (shopifyError) {
      const errMessages: Record<string, string> = {
        invalid_state: 'Invalid OAuth state — please try again.',
        hmac_failed: 'Security check failed — please try again.',
        missing_params: 'Shopify did not return required parameters.',
        token_exchange_failed: 'Could not exchange token with Shopify. Check app credentials.',
        save_failed: 'Could not save Shopify connection. Try again or contact support.',
      }
      toast.error(errMessages[shopifyError] ?? `Shopify error: ${shopifyError}`)
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

        {/* Shopify */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-green-600 shrink-0">
                <ShoppingBag className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="font-semibold text-gray-900">Shopify Store</p>
                {shopifyStatus?.connected ? (
                  <p className="text-xs text-gray-500">
                    {shopifyStatus.shop_name ?? shopifyStatus.shop_domain}
                    {shopifyStatus.products_count != null ? ` · ${shopifyStatus.products_count} products` : ''}
                    {shopifyStatus.synced_at ? ` · Synced ${new Date(shopifyStatus.synced_at).toLocaleDateString()}` : ''}
                  </p>
                ) : (
                  <p className="text-xs text-gray-400">Not connected — connect to auto-sync products + images</p>
                )}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {shopifyStatus?.connected ? (
                <>
                  <span className="flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
                    <CheckCircle className="h-3 w-3" />
                    Connected
                  </span>
                  <button
                    onClick={handleShopifySync}
                    disabled={shopifyLoading}
                    className="flex items-center gap-1 rounded-lg border border-green-200 px-2.5 py-1 text-xs text-green-700 hover:bg-green-50 disabled:opacity-50"
                  >
                    {shopifyLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                    Sync Now
                  </button>
                  <button
                    onClick={handleShopifyDisconnect}
                    disabled={shopifyLoading}
                    className="flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
                  >
                    <Trash2 className="h-3 w-3" />
                    Disconnect
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setShowShopifyDialog(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700"
                >
                  <Link2 className="h-3 w-3" />
                  Connect Store
                </button>
              )}
            </div>
          </div>
        </div>

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
                ) : googleConn?.has_token ? (
                  <p className="text-xs text-amber-600">GA4 not found — reconnect Google to auto-discover</p>
                ) : (
                  <p className="text-xs text-gray-400">Connect Google Ads first (includes GA4 scope)</p>
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
                <button
                  onClick={() => setShowGoogleDialog(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600"
                >
                  <Link2 className="h-3 w-3" />
                  {googleConn?.has_token ? 'Reconnect Google' : 'Connect Google'}
                </button>
              )}
            </div>
          </div>
        </div>
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

      {/* Business type */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Business Type</h2>
          <p className="text-sm text-gray-500">Helps ARIA personalize recommendations for your business model</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {[
              { key: 'd2c', label: 'D2C Product', desc: 'Meta → YouTube → Google → Marketplace' },
              { key: 'creator', label: 'YouTuber / Creator', desc: 'YouTube-first → Instagram → Email' },
              { key: 'service', label: 'Service / SaaS', desc: 'Google Search → LinkedIn → YouTube' },
              { key: 'local', label: 'Local Business', desc: 'Google Maps → Local Search → Instagram' },
              { key: 'b2b', label: 'B2B / Enterprise', desc: 'LinkedIn → Google → Email → Webinars' },
            ].map(bt => (
              <div key={bt.key}
                className="rounded-lg border border-gray-200 p-3 cursor-pointer hover:border-brand-400 hover:bg-brand-50 transition-colors">
                <p className="text-sm font-medium text-gray-900">{bt.label}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{bt.desc}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-gray-400">Saving business type — coming soon</p>
        </div>
      </section>

      {/* Product & Competitor URLs */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Product & Competitor URLs</h2>
          <p className="text-sm text-gray-500">Used for price monitoring, ad library tracking, and competitor intelligence</p>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ProductUrlsSection workspaceId={workspaceId} />
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <p className="text-sm font-semibold text-gray-800 mb-2">Competitor URLs</p>
            <div className="space-y-2 opacity-50">
              {['https://www.livemed.in', 'https://www.omronhealthcare.in'].map(url => (
                <div key={url} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                  <span className="flex-1 truncate">{url}</span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-gray-400">Competitor monitoring — coming soon</p>
          </div>
        </div>
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

      {/* Shopify connect dialog */}
      {showShopifyDialog && (
        <ShopifyConnectDialog
          workspaceId={workspaceId}
          onClose={() => setShowShopifyDialog(false)}
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
    </div>
  )
}
