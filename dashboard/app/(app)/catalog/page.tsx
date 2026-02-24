import { fetchFromFastAPI } from '@/lib/api'
import ProductTable from '@/components/catalog/ProductTable'
import SyncButton from '@/components/catalog/SyncButton'
import type { ProductsResponse } from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string }
}

async function fetchProducts(workspaceId: string): Promise<ProductsResponse | null> {
  if (!workspaceId) return null
  try {
    const r = await fetchFromFastAPI(`/catalog/products?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

export default async function CatalogPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const data = await fetchProducts(workspaceId)

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view the product catalog</p>
      </div>
    )
  }

  const products = data?.products ?? []
  const approvedCount    = products.filter(p => p.mc_status === 'approved').length
  const disapprovedCount = products.filter(p => p.mc_status === 'disapproved').length
  const pendingCount     = products.filter(p => p.mc_status === 'pending').length

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Product Catalog</h1>
          <p className="text-sm text-gray-500">
            {products.length} products ·{' '}
            <span className="text-green-600">{approvedCount} approved</span>
            {disapprovedCount > 0 && (
              <span className="text-red-600"> · {disapprovedCount} disapproved</span>
            )}
            {pendingCount > 0 && (
              <span className="text-yellow-600"> · {pendingCount} pending</span>
            )}
          </p>
        </div>
        <SyncButton workspaceId={workspaceId} />
      </div>

      <ProductTable products={products} />
    </div>
  )
}
