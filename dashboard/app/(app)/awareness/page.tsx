import { Layers } from 'lucide-react'
import ComingSoonPage from '@/components/ui/ComingSoonPage'

interface PageProps { searchParams: { ws?: string } }

export default function AwarenessPage({ searchParams }: PageProps) {
  return (
    <ComingSoonPage
      icon={Layers}
      title="Awareness Funnel"
      subtitle="Full-funnel attribution from impression to purchase"
      description="See exactly where prospects drop off — from first ad impression through to completed purchase — with real attribution data across every channel."
      blockedBy="Google Analytics 4 (GA4) connection"
      blockedByDetail="GA4 tracks website sessions, bounce rate, and conversion funnel. This will be ready once Google Analytics is connected."
      features={[
        { label: 'TOFU → MOFU → BOFU attribution', description: 'Unaware → Problem Aware → Solution Aware → Purchase stages' },
        { label: 'Blended ROAS across Meta + Google', description: 'Single view of all paid channels combined' },
        { label: 'Organic vs paid session split', description: 'See what share of customers come from SEO, direct, paid ads' },
        { label: 'Drop-off analysis at each funnel stage', description: 'Pinpoint exactly where you lose customers' },
        { label: 'Cross-channel touchpoint map', description: 'YouTube → Meta retargeting → Google search journey' },
      ]}
      etaLabel="Coming Soon"
      workspaceId={searchParams.ws}
      ctaLabel="Connect Google in Settings"
      ctaHref="/settings"
    />
  )
}
