'use client'

import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Plus, RefreshCw, Trash2, ExternalLink, Package,
  Globe, Youtube, Sparkles, Link as LinkIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import type { Product } from '@/lib/types'

// ── Product Card ─────────────────────────────────────────────────────────────

function ProductCard({
  product,
  onDelete,
  onResync,
  resyncing,
}: {
  product: Product
  onDelete: (id: string) => void
  onResync: (id: string) => void
  resyncing: boolean
}) {
  const imgs = product.images ?? []
  const firstImg = imgs[0]
  const imgUrl = typeof firstImg === 'string' ? firstImg : (firstImg as any)?.url
  const isYouTube = product.product_type === 'youtube_channel'
  const isComp = product.is_competitor

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden hover:shadow-md transition-shadow flex flex-col">
      {/* Image */}
      {imgUrl ? (
        <div className="aspect-video w-full bg-gray-100 overflow-hidden shrink-0">
          <img
            src={imgUrl}
            alt={product.name}
            className="w-full h-full object-cover"
            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
          />
        </div>
      ) : (
        <div className="aspect-video w-full bg-gray-50 flex items-center justify-center shrink-0">
          {isYouTube
            ? <Youtube className="h-8 w-8 text-red-400 opacity-50" />
            : <Package className="h-8 w-8 text-gray-300" />}
        </div>
      )}

      <div className="p-4 space-y-2 flex-1 flex flex-col">
        {/* Name + badge */}
        <div className="flex items-start justify-between gap-2">
          <p className="font-semibold text-gray-900 text-sm leading-snug">{product.name}</p>
          {isComp && (
            <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600 leading-none mt-0.5">
              Competitor
            </span>
          )}
        </div>

        {/* Price */}
        {product.price_inr != null && (
          <p className="text-sm font-semibold text-indigo-600">
            ₹{Number(product.price_inr).toLocaleString('en-IN')}
            {product.mrp_inr && Number(product.mrp_inr) > Number(product.price_inr) && (
              <span className="ml-1.5 text-xs font-normal text-gray-400 line-through">
                ₹{Number(product.mrp_inr).toLocaleString('en-IN')}
              </span>
            )}
          </p>
        )}

        {/* Description */}
        {product.description && (
          <p className="text-xs text-gray-500 line-clamp-2 flex-1">{product.description}</p>
        )}

        {/* Key features */}
        {product.key_features && product.key_features.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {product.key_features.slice(0, 3).map((f, i) => (
              <span key={i} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                {f}
              </span>
            ))}
          </div>
        )}

        {/* Source */}
        {product.source_platform && (
          <p className="text-[10px] text-gray-400 uppercase tracking-wide">
            via {product.source_platform}
          </p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 pt-1 mt-auto">
          {product.product_url && (
            <a
              href={product.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-400 hover:text-blue-500"
              title="Open URL"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            onClick={() => onResync(product.id)}
            disabled={resyncing}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${resyncing ? 'animate-spin' : ''}`} />
            Re-sync
          </button>
          <button
            onClick={() => onDelete(product.id)}
            className="ml-auto flex items-center gap-1 text-xs text-red-400 hover:text-red-600"
          >
            <Trash2 className="h-3 w-3" />
            Remove
          </button>
        </div>
      </div>
    </div>
  )
}

// ── URL Add Bar ──────────────────────────────────────────────────────────────

function AddUrlBar({
  placeholder,
  onAdd,
  saving,
}: {
  placeholder: string
  onAdd: (url: string) => void
  saving: boolean
}) {
  const [url, setUrl] = useState('')
  const submit = () => {
    if (!url.trim()) return
    onAdd(url.trim())
    setUrl('')
  }
  return (
    <div className="flex gap-2">
      <div className="relative flex-1">
        <LinkIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder={placeholder}
          className="w-full rounded-lg border border-gray-200 pl-9 pr-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>
      <button
        onClick={submit}
        disabled={saving || !url.trim()}
        className="flex items-center gap-1.5 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50 shrink-0"
      >
        {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Fetch & Save
      </button>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function ProductsPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''

  const [myProducts, setMyProducts] = useState<Product[]>([])
  const [compProducts, setCompProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resyncingId, setResyncingId] = useState<string | null>(null)

  const fetchProducts = useCallback(async () => {
    if (!wsId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/products?workspace_id=${wsId}`)
      const d = await r.json()
      const all: Product[] = d.products ?? []
      setMyProducts(all.filter(p => !p.is_competitor))
      setCompProducts(all.filter(p => p.is_competitor))
    } catch {
      toast.error('Could not load products')
    } finally {
      setLoading(false)
    }
  }, [wsId])

  useEffect(() => { fetchProducts() }, [fetchProducts])

  const addProduct = async (url: string, isCompetitor: boolean) => {
    setSaving(true)
    try {
      const r = await fetch('/api/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, workspace_id: wsId, is_competitor: isCompetitor }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail ?? 'Failed to fetch product')
      toast.success(`Saved: ${d.name}`)
      fetchProducts()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not fetch product')
    } finally {
      setSaving(false)
    }
  }

  const deleteProduct = async (id: string) => {
    try {
      await fetch(`/api/products/${id}?workspace_id=${wsId}`, { method: 'DELETE' })
      toast.success('Product removed')
      fetchProducts()
    } catch {
      toast.error('Failed to remove')
    }
  }

  const resyncProduct = async (id: string) => {
    setResyncingId(id)
    try {
      const r = await fetch(`/api/products/${id}?action=resync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail ?? 'Re-sync failed')
      toast.success(`Re-synced: ${d.name}`)
      fetchProducts()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Re-sync failed')
    } finally {
      setResyncingId(null)
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8 space-y-12">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Product Intelligence</h1>
        <p className="mt-1 text-sm text-gray-500 max-w-2xl">
          Paste any product URL — ARIA reads the page and extracts name, price, features and images.
          Product data feeds into email campaigns, campaign briefs, ARIA, and Growth OS.
        </p>
      </div>

      {/* ── My Products ─────────────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">My Products</h2>
          <p className="text-sm text-gray-500">
            Add your product pages. Works for Shopify, WooCommerce, Amazon, any website — including JS-rendered stores.
          </p>
        </div>

        <AddUrlBar
          placeholder="https://yourstore.com/products/product-name"
          onAdd={url => addProduct(url, false)}
          saving={saving}
        />

        {loading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-gray-400">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading products…
          </div>
        ) : myProducts.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-12 text-center">
            <Package className="h-10 w-10 mx-auto mb-3 text-gray-300" />
            <p className="text-sm text-gray-500 font-medium">No products yet</p>
            <p className="text-xs text-gray-400 mt-1">
              Paste a product URL above — AI will read it and extract all details automatically
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {myProducts.map(p => (
              <ProductCard
                key={p.id}
                product={p}
                onDelete={deleteProduct}
                onResync={resyncProduct}
                resyncing={resyncingId === p.id}
              />
            ))}
          </div>
        )}
      </section>

      {/* ── Competitor Products ──────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            Competitor Products
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-600">
              Intel
            </span>
          </h2>
          <p className="text-sm text-gray-500">
            Add competitor product pages. AI uses these for ad positioning, email comparisons, and growth strategy.
            Also works for competitor YouTube channels.
          </p>
        </div>

        <AddUrlBar
          placeholder="https://competitor.com/products/their-product — or YouTube channel URL"
          onAdd={url => addProduct(url, true)}
          saving={saving}
        />

        {!loading && compProducts.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-12 text-center">
            <Globe className="h-10 w-10 mx-auto mb-3 text-gray-300" />
            <p className="text-sm text-gray-500 font-medium">No competitor products yet</p>
            <p className="text-xs text-gray-400 mt-1">
              Add competitor URLs to sharpen your positioning and ad copy
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {compProducts.map(p => (
              <ProductCard
                key={p.id}
                product={p}
                onDelete={deleteProduct}
                onResync={resyncProduct}
                resyncing={resyncingId === p.id}
              />
            ))}
          </div>
        )}
      </section>

      {/* Tip banner */}
      <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 flex items-start gap-3">
        <Sparkles className="h-4 w-4 text-indigo-500 mt-0.5 shrink-0" />
        <div className="text-sm text-indigo-700">
          <strong>How products power ARIA:</strong> Every product you add is available to ARIA, the email builder, campaign planner, and Growth OS. For YouTubers — add your channel URL and competitor channel URLs here, then visit <strong>YouTube Intel</strong> to run deep analysis.
        </div>
      </div>
    </div>
  )
}
