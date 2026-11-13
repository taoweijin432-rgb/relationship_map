import type { FactView } from '../api/client'

export interface ExperienceGroup {
  id: string
  views: FactView[]
}

// 同条教育由来源键证明，缺失或格式不符的旧数据逐条展示。
export function experienceGroups(views: FactView[]): ExperienceGroup[] {
  const groups = new Map<string, ExperienceGroup>()
  for (const view of views) {
    const fact = view.fact
    const key = fact.experience_key
    const validKey =
      key && key.startsWith(`${fact.source_system}:`) && /^[^:\s]+:[^:\s]+:[^:\s]+$/.test(key)
    const id =
      fact.type !== 'employment' && validKey ? `${fact.person_id}|${key}` : `fact:${fact.id}`
    const group = groups.get(id) ?? { id, views: [] }
    group.views.push(view)
    groups.set(id, group)
  }
  return [...groups.values()]
}
