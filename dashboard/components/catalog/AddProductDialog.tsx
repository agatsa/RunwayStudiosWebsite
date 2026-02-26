'use client'

import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Plus, X, Upload, Loader2, ImagePlus, Link as LinkIcon } from 'lucide-react'

interface Props {
  workspaceId: string
}

export default function AddProductDialog({ workspaceId }: Props) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [imagePreview, setImagePreview] = useState('')
  const [imageB64, setImageB64] = useState('')
  const [imageFilename, setImageFilename] = useState('')
  const [imageUrlInput, setImageUrlInput] = useState('')
  const [imageMode, setImageMode] = useState<'url' | 'file'>('url')
  const fileRef = useRef<HTMLInputElement>(null)
  const router = useRouter()

  const [form, setForm] = useState({
    name: '',
    description: '',
    price_inr: '',
    product_url: '',
    sku: '',
  })

  function reset() {
    setForm({ name: '', description: '', price_inr: '', product_url: '', sku: '' })
    setImagePreview(''); setImageB64(''); setImageFilename(''); setImageUrlInput('')
    setImageMode('url')
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      setImagePreview(result)
      setImageB64(result.split(',')[1])
      setImageFilename(file.name)
    }
    reader.readAsDataURL(file)
  }

  async function handleSave() {
    if (!form.name.trim()) { toast.error('Product name is required'); return }
    setSaving(true)
    try {
      // 1. Create the product
      const res = await fetch('/api/catalog/add-product', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          name:         form.name.trim(),
          description:  form.description.trim() || null,
          price_inr:    form.price_inr ? Number(form.price_inr) : null,
          product_url:  form.product_url.trim() || null,
          sku:          form.sku.trim() || null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to create product')
      const productId = data.product_id

      // 2. Add image if provided
      const imageUrl = imageMode === 'url' ? imageUrlInput.trim() : ''
      if (imageUrl || imageB64) {
        await fetch('/api/catalog/product-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product_id:   productId,
            workspace_id: workspaceId,
            ...(imageUrl  ? { image_url: imageUrl } : {}),
            ...(imageB64  ? { image_b64: imageB64, filename: imageFilename } : {}),
          }),
        })
      }

      toast.success(`"${form.name}" added to catalog`)
      setOpen(false)
      reset()
      router.refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
      >
        <Plus className="h-4 w-4" /> Add Product
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <h2 className="text-base font-semibold text-gray-900">Add Product to Catalog</h2>
          <button onClick={() => { setOpen(false); reset() }} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Product Name *</label>
            <input
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. SanketLife 2.0"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
            />
          </div>

          {/* Price + SKU */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Price (₹)</label>
              <input
                type="number"
                value={form.price_inr}
                onChange={e => setForm(f => ({ ...f, price_inr: e.target.value }))}
                placeholder="15999"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SKU</label>
              <input
                value={form.sku}
                onChange={e => setForm(f => ({ ...f, sku: e.target.value }))}
                placeholder="SKU-001"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
              />
            </div>
          </div>

          {/* Product URL */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Product Page URL</label>
            <input
              value={form.product_url}
              onChange={e => setForm(f => ({ ...f, product_url: e.target.value }))}
              placeholder="https://agatsaone.com/products/sanketlife-2-0"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              rows={2}
              placeholder="Short product description for AI campaigns"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none resize-none"
            />
          </div>

          {/* Image */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Product Image</label>
            <div className="flex gap-2 mb-2">
              <button
                onClick={() => setImageMode('url')}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${imageMode === 'url' ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-gray-200 text-gray-500'}`}
              >
                <LinkIcon className="h-3.5 w-3.5" /> Paste URL
              </button>
              <button
                onClick={() => setImageMode('file')}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${imageMode === 'file' ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-gray-200 text-gray-500'}`}
              >
                <Upload className="h-3.5 w-3.5" /> Upload File
              </button>
            </div>

            {imageMode === 'url' ? (
              <input
                value={imageUrlInput}
                onChange={e => { setImageUrlInput(e.target.value); setImagePreview(e.target.value) }}
                placeholder="https://cdn.shopify.com/… or any image URL"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
              />
            ) : (
              <div
                onClick={() => fileRef.current?.click()}
                className="flex h-20 cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-gray-200 hover:border-indigo-400 hover:bg-indigo-50 transition-colors"
              >
                {imagePreview && imageB64 ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={imagePreview} alt="preview" className="h-full w-full object-contain rounded-lg" />
                ) : (
                  <div className="text-center">
                    <ImagePlus className="h-6 w-6 text-gray-300 mx-auto mb-1" />
                    <p className="text-xs text-gray-400">Click to upload JPG / PNG</p>
                  </div>
                )}
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
              </div>
            )}

            {/* Preview for URL mode */}
            {imageMode === 'url' && imagePreview && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imagePreview} alt="preview" className="mt-2 h-16 w-16 rounded-lg border border-gray-200 object-cover" onError={() => setImagePreview('')} />
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 px-6 py-4">
          <button onClick={() => { setOpen(false); reset() }} className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !form.name.trim()}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {saving ? 'Saving…' : 'Add Product'}
          </button>
        </div>
      </div>
    </div>
  )
}
