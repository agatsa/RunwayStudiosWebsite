'use client'

import { useState } from 'react'
import { X, Zap, Check } from 'lucide-react'

interface Pack {
  key: string
  credits: number
  amount_paise: number
  label: string
  badge?: string
}

const PACKS: Pack[] = [
  { key: '100', credits: 100, amount_paise: 79900,  label: '₹799',   },
  { key: '250', credits: 250, amount_paise: 149900, label: '₹1,499', badge: 'Popular' },
  { key: '600', credits: 600, amount_paise: 299900, label: '₹2,999', badge: 'Best Value' },
]

interface Props {
  wsId: string
  onClose: () => void
  onSuccess: (newBalance: number) => void
}

declare global {
  interface Window {
    Razorpay: any
  }
}

export default function TopUpModal({ wsId, onClose, onSuccess }: Props) {
  const [selected, setSelected] = useState<string>('250')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  const loadRazorpay = (): Promise<boolean> =>
    new Promise(resolve => {
      if (window.Razorpay) return resolve(true)
      const s = document.createElement('script')
      s.src = 'https://checkout.razorpay.com/v1/checkout.js'
      s.onload = () => resolve(true)
      s.onerror = () => resolve(false)
      document.body.appendChild(s)
    })

  const handlePay = async () => {
    setLoading(true)
    try {
      // 1. Create order
      const res = await fetch('/api/billing/topup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, pack: selected }),
      })
      const order = await res.json()
      if (!res.ok) throw new Error(order.detail ?? 'Failed to create order')

      // 2. Load Razorpay
      if (order.razorpay_key_id === 'TEST_MODE' || order.order_id?.startsWith('stub_')) {
        // Test mode: skip payment, call confirm directly
        const confirmRes = await fetch('/api/billing/topup-confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: wsId,
            razorpay_order_id: order.order_id,
            razorpay_payment_id: 'test_payment',
            razorpay_signature: '',
          }),
        })
        const confirmData = await confirmRes.json()
        if (confirmRes.ok) {
          setDone(true)
          onSuccess(confirmData.new_balance)
        }
        return
      }

      await loadRazorpay()
      const pack = PACKS.find(p => p.key === selected)!

      new window.Razorpay({
        key: order.razorpay_key_id,
        order_id: order.order_id,
        amount: order.amount_paise,
        currency: 'INR',
        name: 'Runway Studios',
        description: `${pack.credits} Credits Top-Up`,
        handler: async (response: any) => {
          const confirmRes = await fetch('/api/billing/topup-confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              workspace_id: wsId,
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            }),
          })
          const confirmData = await confirmRes.json()
          if (confirmRes.ok) {
            setDone(true)
            onSuccess(confirmData.new_balance)
          }
        },
        theme: { color: '#7c3aed' },
      }).open()
    } catch (e) {
      alert((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const pack = PACKS.find(p => p.key === selected)!

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-amber-500" />
            <h2 className="text-base font-bold text-gray-900">Buy Credits</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {done ? (
          <div className="px-6 py-10 flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
              <Check className="h-6 w-6 text-green-600" />
            </div>
            <p className="text-base font-semibold text-gray-900">Credits added!</p>
            <p className="text-sm text-gray-500">{pack.credits} credits added to your account.</p>
            <button
              onClick={onClose}
              className="mt-2 rounded-xl bg-brand-600 px-5 py-2 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <div className="px-6 py-5">
            <p className="text-sm text-gray-500 mb-4">Credits never expire. Use them anytime on any AI feature.</p>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {PACKS.map(p => (
                <button
                  key={p.key}
                  onClick={() => setSelected(p.key)}
                  className={`relative flex flex-col items-center gap-1 rounded-xl border-2 p-3 text-center transition-all ${
                    selected === p.key
                      ? 'border-amber-400 bg-amber-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {p.badge && (
                    <span className="absolute -top-2 left-1/2 -translate-x-1/2 rounded-full bg-amber-400 px-2 py-0.5 text-[9px] font-bold text-white whitespace-nowrap">
                      {p.badge}
                    </span>
                  )}
                  <span className="text-lg font-bold text-gray-900 flex items-center gap-0.5">
                    <Zap className="h-4 w-4 text-amber-400" />{p.credits}
                  </span>
                  <span className="text-xs font-semibold text-gray-600">{p.label}</span>
                </button>
              ))}
            </div>
            <button
              onClick={handlePay}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-3 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-60 transition-colors"
            >
              {loading ? 'Processing…' : `Pay ${pack.label} → Get ${pack.credits} credits`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
