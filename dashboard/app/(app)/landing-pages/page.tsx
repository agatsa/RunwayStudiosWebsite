import { Layout } from 'lucide-react'
import ComingSoonPage from '@/components/ui/ComingSoonPage'

interface PageProps { searchParams: { ws?: string } }

export default function LandingPagesPage({ searchParams }: PageProps) {
  return (
    <ComingSoonPage
      icon={Layout}
      title="Landing Page Intelligence"
      subtitle="Drop-off analysis — from ad click to completed purchase"
      description="Connect GA4 to see exactly where your paid traffic leaks. Every drop-off stage shows you how much revenue you're losing and why."
      blockedBy="Google Analytics 4 (GA4) connection"
      blockedByDetail="Landing page data (sessions, bounce rate, scroll depth, conversion funnel) is tracked by GA4. This will be ready once Google Analytics is connected."
      features={[
        { label: 'Per-URL drop-off rates', description: 'See which landing pages lose visitors fastest' },
        { label: 'Bounce rate & avg engagement time', description: 'Is your page holding attention after the ad click?' },
        { label: 'Purchase funnel stages', description: 'Landed → Scrolled → Clicked CTA → Checkout → Purchased' },
        { label: 'Page Speed scores (LCP, CLS, FID)', description: 'Technical drop-offs from slow page load' },
        { label: 'A/B test planner', description: 'Log hypothesis, track statistical significance automatically' },
      ]}
      etaLabel="Coming Soon"
      workspaceId={searchParams.ws}
      ctaLabel="Connect Google in Settings"
      ctaHref="/settings"
    />
  )
}
