'use client'

import { useState } from 'react'
import { X, ShoppingBag, ExternalLink, CheckCircle, Key, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useRouter } from 'next/navigation'

interface Props {
  workspaceId: string
  onClose: () => void
}

type Mode = 'token' | 'oauth'

export default function ShopifyConnectDialog({ workspaceId, onClose }: Props) {
  const [mode, setMode] = useState<Mode>('token')
  const [shopDomain, setShopDomain] = useState('')
  const [accessToken, setAccessToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()

  function normalizeDomain(d: string) {
    return d.trim().replace(/^https?:\/\//, '').replace(/\/$/, '')
  }

  // ── Custom App token mode ────────────────────────────────────────────────
  async function handleConnectToken() {
    const domain = normalizeDomain(shopDomain)
    const token  = accessToken.trim()
    if (!domain) { setError('Enter your myshopify.com domain'); return }
    if (!token)  { setError('Paste your Admin API access token'); return }
    setError('')
    setSaving(true)
    try {
      const res = await fetch('/api/shopify/connect-token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          shop_domain:  domain,
          access_token: token,
          scope:        'read_products,read_inventory,read_orders,read_draft_orders,read_price_rules,read_discounts,read_locations,read_fulfillments',
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Connection failed')
      toast.success(`Connected ${data.shop_name ?? domain} — ${data.products_synced ?? 0} products synced`)
      onClose()
      router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed')
    } finally {
      setSaving(false)
    }
  }

  // ── OAuth mode ───────────────────────────────────────────────────────────
  function handleOAuthInstall() {
    const domain = normalizeDomain(shopDomain)
    if (!domain) { setError('Enter your myshopify.com domain'); return }
    setError('')
    window.location.href = `/api/shopify/install?shop=${encodeURIComponent(domain)}&ws=${workspaceId}`
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <ShoppingBag className="h-5 w-5 text-green-600" />
            <h2 className="text-base font-semibold text-gray-900">Connect Shopify Store</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Mode tabs */}
        <div className="flex border-b border-gray-100 px-6 pt-4 gap-1">
          <button
            onClick={() => { setMode('token'); setError('') }}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
              mode === 'token'
                ? 'border-green-600 text-green-700 bg-green-50'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <span className="flex items-center gap-1.5"><Key className="h-3.5 w-3.5" /> Custom App Token</span>
          </button>
          <button
            onClick={() => { setMode('oauth'); setError('') }}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
              mode === 'oauth'
                ? 'border-green-600 text-green-700 bg-green-50'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <span className="flex items-center gap-1.5"><ShoppingBag className="h-3.5 w-3.5" /> OAuth Install</span>
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {mode === 'token' ? (
            <>
              {/* Recommended badge */}
              <div className="rounded-xl bg-green-50 border border-green-100 p-3 flex items-start gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-semibold text-green-800">Recommended for your own store</p>
                  <p className="text-xs text-green-700 mt-0.5">
                    Create a Custom App directly in Shopify Admin — no Shopify review needed, full scope access, works immediately.
                  </p>
                </div>
              </div>

              {/* Steps */}
              <ol className="space-y-1.5 text-xs text-gray-600 list-decimal list-inside">
                <li>Go to <strong>Shopify Admin → Settings → Apps and sales channels</strong></li>
                <li>Click <strong>Develop apps</strong> → <strong>Create an app</strong> → name it &quot;Runway Studios&quot;</li>
                <li>Click <strong>Configure Admin API scopes</strong> → check all product/order/inventory scopes</li>
                <li>Click <strong>Install app</strong> → copy the <strong>Admin API access token</strong></li>
              </ol>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">myshopify.com domain</label>
                <input
                  value={shopDomain}
                  onChange={e => { setShopDomain(e.target.value); setError('') }}
                  placeholder="agatsaone.myshopify.com"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-green-400 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin API access token</label>
                <input
                  value={accessToken}
                  onChange={e => { setAccessToken(e.target.value); setError('') }}
                  type="password"
                  placeholder="shpat_xxxxxxxxxxxxxxxxxxxx"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-green-400 focus:outline-none font-mono"
                />
                <p className="mt-1 text-xs text-gray-400">Starts with <code className="bg-gray-100 px-1 rounded">shpat_</code></p>
              </div>

              {error && <p className="text-xs text-red-500">{error}</p>}
            </>
          ) : (
            <>
              <div className="rounded-xl bg-amber-50 border border-amber-100 p-3 flex items-start gap-2">
                <ExternalLink className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-semibold text-amber-800">For client stores</p>
                  <p className="text-xs text-amber-700 mt-0.5">
                    OAuth works for installing on any merchant&apos;s store. Requires your Shopify Partner app to have
                    non-protected scopes. <code className="bg-amber-100 px-1 rounded">read_orders</code> may block — use token mode for your own store.
                  </p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Store domain</label>
                <input
                  value={shopDomain}
                  onChange={e => { setShopDomain(e.target.value); setError('') }}
                  placeholder="agatsaone.myshopify.com"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-green-400 focus:outline-none"
                />
              </div>

              {error && <p className="text-xs text-red-500">{error}</p>}

              <p className="text-xs text-gray-500">
                You&apos;ll be redirected to Shopify to approve the connection.
              </p>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          {mode === 'token' ? (
            <button
              onClick={handleConnectToken}
              disabled={saving || !shopDomain.trim() || !accessToken.trim()}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-5 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Key className="h-4 w-4" />}
              {saving ? 'Connecting…' : 'Connect Store'}
            </button>
          ) : (
            <button
              onClick={handleOAuthInstall}
              disabled={!shopDomain.trim()}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-5 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              <ShoppingBag className="h-4 w-4" />
              Install App
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
