import { Suspense } from 'react'
import UnsubscribeClient from './UnsubscribeClient'

export default function UnsubscribePage() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <Suspense fallback={
        <div className="text-center text-gray-500 text-sm">Loading...</div>
      }>
        <UnsubscribeClient />
      </Suspense>
    </div>
  )
}
