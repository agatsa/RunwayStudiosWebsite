import { Suspense } from 'react'
import HomeContent from './HomeContent'

export default function HomePage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <HomeContent />
    </Suspense>
  )
}
