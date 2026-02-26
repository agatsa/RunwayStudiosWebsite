import { ClipboardList, Target, TrendingUp, CheckCircle, Zap } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'
import BriefForm from '@/components/campaign-planner/BriefForm'
import ActivePlans from '@/components/campaign-planner/ActivePlans'

interface PageProps { searchParams: { ws?: string } }

async function getPlans(workspaceId: string) {
  try {
    const r = await fetchFromFastAPI(`/campaign-planner/plans?workspace_id=${workspaceId}`)
    if (!r.ok) return []
    const data = await r.json()
    return data.plans ?? []
  } catch {
    return []
  }
}

export default async function CampaignPlannerPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const plans = workspaceId ? await getPlans(workspaceId) : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600">
            <ClipboardList className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Campaign Planner</h1>
            <p className="text-sm text-gray-500">AI-generated campaign briefs with KPI targets — submit to Approvals queue</p>
          </div>
        </div>
      </div>

      {/* Brief Form — client component */}
      <BriefForm workspaceId={workspaceId} />

      {/* Active plans from action_log */}
      {plans.length > 0 && <ActivePlans plans={plans} />}

      {/* How it works */}
      <div className="rounded-xl border border-gray-200 bg-gray-50 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Zap className="h-4 w-4 text-yellow-500" /> How the Campaign Planner Works
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          {[
            { icon: Target, step: '1', title: 'Fill Brief', desc: 'Product, audience, goal, budget, channels' },
            { icon: ClipboardList, step: '2', title: 'AI Generates', desc: 'Headline, copy, hook, creative direction, KPI targets' },
            { icon: TrendingUp, step: '3', title: 'Review & Edit', desc: 'Edit the concept before submitting' },
            { icon: CheckCircle, step: '4', title: 'Submit', desc: 'Lands in Approvals queue for your team' },
          ].map(s => (
            <div key={s.step} className="text-center">
              <div className="mx-auto mb-2 flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100">
                <s.icon className="h-4 w-4 text-indigo-600" />
              </div>
              <p className="text-xs font-semibold text-gray-800">{s.title}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
