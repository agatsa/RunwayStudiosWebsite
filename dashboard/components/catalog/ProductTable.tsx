import Image from 'next/image'
import McStatusBadge from './McStatusBadge'
import DisapprovalReasonModal from './DisapprovalReasonModal'
import { formatINR } from '@/lib/utils'
import type { Product } from '@/lib/types'

interface Props {
  products: Product[]
}

export default function ProductTable({ products }: Props) {
  if (products.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-sm text-gray-400">No products in catalog</p>
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
                <div className="flex items-center gap-3">
                  {product.images?.[0] ? (
                    <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg border border-gray-200">
                      <Image
                        src={product.images[0]}
                        alt={product.name}
                        fill
                        className="object-cover"
                        sizes="40px"
                      />
                    </div>
                  ) : (
                    <div className="h-10 w-10 shrink-0 rounded-lg bg-gray-100" />
                  )}
                  <div>
                    <p className="font-medium text-gray-900">{product.name}</p>
                    {product.brand && <p className="text-xs text-gray-500">{product.brand}</p>}
                  </div>
                </div>
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
