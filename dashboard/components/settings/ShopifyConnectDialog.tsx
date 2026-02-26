'use client'

import { useState } from 'react'
import { X, ShoppingBag, ExternalLink, CheckCircle } from 'lucide-react'

interface Props {
  workspaceId: string
  onClose: () => void
}

export default function ShopifyConnectDialog({ workspaceId, onClose }: Props) {
  const [shopDomain, setShopDomain] = useState('')
  const [error, setError] = useState('')

  function handleInstall() {
    const domain = shopDomain.trim()
      .replace(/^https?:\/\//, '')
      .replace(/\/$/, '')
    if (!domain) {
      setError('Enter your Shopify store domain')
      return
    }
    setError('')
    window.location.href = `/api/shopify/install?shop=${encodeURIComponent(domain)}&ws=${workspaceId}`
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
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

        <div className="px-6 py-5 space-y-4">
          {/* What we'll access */}
          <div className="rounded-xl bg-green-50 border border-green-100 p-4 space-y-2">
            <p className="text-xs font-semibold text-green-800 uppercase tracking-wide">Permissions requested</p>
            <ul className="space-y-1.5">
              {[
                'Read all products + variants + images',
                'Read inventory levels',
                'Real-time sync via webhooks (auto-update on changes)',
              ].map(item => (
                <li key={item} className="flex items-start gap-2 text-sm text-green-700">
                  <CheckCircle className="h-4 w-4 mt-0.5 shrink-0 text-green-500" />
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* Store URL input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Your Shopify store domain
            </label>
            <input
              value={shopDomain}
              onChange={e => { setShopDomain(e.target.value); setError('') }}
              onKeyDown={e => e.key === 'Enter' && handleInstall()}
              placeholder="agatsaone.myshopify.com"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-green-400 focus:outline-none"
            />
            <p className="mt-1 text-xs text-gray-400">
              Find it in Shopify Admin → Settings → Domains → Primary domain
            </p>
            {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
          </div>

          <p className="text-xs text-gray-500">
            You&apos;ll be redirected to Shopify to approve the connection.
            After approval, all your products and images sync automatically into the Runway catalog.
          </p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-gray-100 px-6 py-4">
          <a
            href="https://partners.shopify.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
          >
            <ExternalLink className="h-3 w-3" /> Shopify Partners
          </a>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleInstall}
              disabled={!shopDomain.trim()}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-5 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              <ShoppingBag className="h-4 w-4" />
              Install App
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
