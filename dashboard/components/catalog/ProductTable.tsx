'use client'

import { useState, useRef } from 'react'
import Image from 'next/image'
import { toast } from 'sonner'
import { Upload, Link as LinkIcon, X, Loader2, ImagePlus } from 'lucide-react'
import McStatusBadge from './McStatusBadge'
import DisapprovalReasonModal from './DisapprovalReasonModal'
import { formatINR } from '@/lib/utils'
import type { Product } from '@/lib/types'

interface Props {
  products: Product[]
}

// ── Per-product image cell ─────────────────────────────────────────────────────
function ProductImageCell({ product }: { product: Product }) {
  const _img0 = product.images?.[0]
  const [imageUrl, setImageUrl]   = useState<string>(typeof _img0 === 'string' ? _img0 : (_img0 as any)?.url ?? '')
  const [mode, setMode]           = useState<'idle' | 'url' | 'uploading'>('idle')
  const [urlInput, setUrlInput]   = useState('')
  const [saving, setSaving]       = useState(false)
  const fileInputRef              = useRef<HTMLInputElement>(null)

  async function saveImageUrl(url: string) {
    if (!url.trim()) return
    setSaving(true)
    try {
      const res = await fetch('/api/catalog/product-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_id:   product.id,
          workspace_id: product.workspace_id,
          image_url:    url.trim(),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to save image')
      setImageUrl(url.trim())
      setMode('idle')
      setUrlInput('')
      toast.success('Product image saved')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save image')
    } finally {
      setSaving(false)
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setMode('uploading')
    setSaving(true)
    try {
      const reader = new FileReader()
      reader.onload = async () => {
        const b64 = (reader.result as string).split(',')[1]
        const res = await fetch('/api/catalog/product-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product_id:   product.id,
            workspace_id: product.workspace_id,
            image_b64:    b64,
            filename:     file.name,
          }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Upload failed')
        setImageUrl(data.image_url)
        setMode('idle')
        toast.success('Product image uploaded')
        setSaving(false)
      }
      reader.readAsDataURL(file)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed')
      setMode('idle')
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      {/* Image thumbnail */}
      <div className="relative h-10 w-10 shrink-0">
        {imageUrl ? (
          <div className="relative h-10 w-10 overflow-hidden rounded-lg border border-gray-200 group cursor-pointer"
               onClick={() => setMode(m => m === 'idle' ? 'url' : 'idle')}>
            <Image src={imageUrl} alt={product.name} fill className="object-cover" sizes="40px" />
            <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg">
              <ImagePlus className="h-4 w-4 text-white" />
            </div>
          </div>
        ) : (
          <button
            onClick={() => setMode(m => m === 'idle' ? 'url' : 'idle')}
            className="flex h-10 w-10 items-center justify-center rounded-lg border-2 border-dashed border-gray-200 hover:border-indigo-400 hover:bg-indigo-50 transition-colors"
            title="Add product image"
          >
            <ImagePlus className="h-4 w-4 text-gray-400" />
          </button>
        )}
      </div>

      {/* Product name + inline image input */}
      <div className="min-w-0 flex-1">
        <p className="font-medium text-gray-900 truncate">{product.name}</p>
        {product.brand && <p className="text-xs text-gray-500">{product.brand}</p>}

        {/* URL paste mode */}
        {mode === 'url' && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <input
              autoFocus
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') saveImageUrl(urlInput) }}
              placeholder="Paste image URL or upload file →"
              className="flex-1 rounded border border-gray-200 px-2 py-1 text-xs focus:border-indigo-400 focus:outline-none min-w-0"
            />
            <button
              onClick={() => saveImageUrl(urlInput)}
              disabled={saving || !urlInput.trim()}
              className="flex items-center gap-1 rounded bg-indigo-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <LinkIcon className="h-3 w-3" />}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
              title="Upload from computer"
            >
              <Upload className="h-3 w-3" />
            </button>
            <button onClick={() => setMode('idle')} className="text-gray-400 hover:text-gray-600">
              <X className="h-3.5 w-3.5" />
            </button>
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
          </div>
        )}

        {/* Uploading state */}
        {mode === 'uploading' && (
          <div className="mt-1 flex items-center gap-1.5 text-xs text-indigo-600">
            <Loader2 className="h-3 w-3 animate-spin" /> Uploading…
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main table ─────────────────────────────────────────────────────────────────
export default function ProductTable({ products }: Props) {
  if (products.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-sm text-gray-400">No products in catalog — import from Shopify above</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-gray-200 bg-gray-50">
          <tr>
            <th className="py-3 pl-4 pr-4 text-left text-xs font-medium uppercase text-gray-500">Product</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Price</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">SKU</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">MC Status</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Issues</th>
            <th className="py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {products.map(product => (
            <tr key={product.id} className="hover:bg-gray-50">
              <td className="py-3 pl-4 pr-4">
                <ProductImageCell product={product} />
              </td>
              <td className="py-3 pr-4 font-mono text-gray-700">
                {formatINR(product.price_inr ?? null)}
              </td>
              <td className="py-3 pr-4 text-gray-500">{product.sku ?? '—'}</td>
              <td className="py-3 pr-4">
                <McStatusBadge status={product.mc_status ?? null} />
              </td>
              <td className="py-3 pr-4">
                <DisapprovalReasonModal product={product} />
              </td>
              <td className="py-3">
                <span className={`text-xs font-medium ${product.active ? 'text-green-600' : 'text-gray-400'}`}>
                  {product.active ? 'Active' : 'Inactive'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
