'use client'

import { useState } from 'react'
import { X, ShoppingBag } from 'lucide-react'

interface Props {
  workspaceId: string
  onClose: () => void
}

export default function ShopifyConnectDialog({ workspaceId, onClose }: Props) {
  const [shopDomain, setShopDomain] = useState('')
  const [error, setError] = useState('')

  function normalizeDomain(d: string) {
    return d.trim().replace(/^https?:\/\//, '').replace(/\/$/, '')
  }

  function handleInstall() {
    const domain = normalizeDomain(shopDomain)
    if (!domain) { setError('Enter your myshopify.com domain'); return }
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
          <p className="text-sm text-gray-500">
            Enter your store domain and you&apos;ll be redirected to Shopify to approve the connection. Products, orders and inventory sync automatically after approval.
          </p>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Store domain</label>
            <input
              value={shopDomain}
              onChange={e => { setShopDomain(e.target.value); setError('') }}
              onKeyDown={e => e.key === 'Enter' && handleInstall()}
              placeholder="yourstore.myshopify.com"
              autoFocus
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-green-400 focus:outline-none"
            />
            {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 px-6 py-4">
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
            Connect with Shopify
          </button>
        </div>
      </div>
    </div>
  )
}
