import type { Entity, SearchRequest } from '../api/client'

export interface QueryCondition {
  id: string
  field: keyof SearchRequest
  value?: string
  label: string
}
const relations: Record<string, string> = {
  same_company: '曾任职同一公司',
  same_company_overlap: '同公司同期',
  same_school: '同校',
  same_major: '同专业',
}
export function queryConditions(
  filters: SearchRequest | undefined,
  entities: Entity[],
): QueryCondition[] {
  if (!filters) return []
  const conditions: QueryCondition[] = []
  if ((filters.max_hops ?? 1) > 1)
    conditions.push({
      id: 'max_hops',
      field: 'max_hops',
      label: `最多 ${filters.max_hops} 跳`,
    })
  if (filters.require_same_school)
    conditions.push({
      id: 'require_same_school',
      field: 'require_same_school',
      label: '前提 · 同校',
    })
  const groups = {
    organization_ids: '公司',
    school_ids: '学校',
    major_ids: '专业',
    role_ids: '职位',
    position_titles: '职位原文',
    relation_organization_ids: '共同公司',
  } as const
  for (const [field, prefix] of Object.entries(groups)) {
    for (const value of filters[field as keyof typeof groups] ?? []) {
      conditions.push({
        id: `${field}|${value}`,
        field: field as keyof typeof groups,
        value,
        label: `${prefix} · ${entities.find((entity) => entity.id === value)?.name ?? value}`,
      })
    }
  }
  const scalarLabels: Partial<Record<keyof SearchRequest, string>> = {
    source: '来源',
    relation_type: '关系',
    start_month: '任职起始',
    end_month: '任职结束',
    relation_start_month: '共同任职起始',
    relation_end_month: '共同任职结束',
    min_overlap_months: '最短同期月数',
  }
  for (const [field, prefix] of Object.entries(scalarLabels)) {
    const value = filters[field as keyof SearchRequest]
    if (value == null || value === '') continue
    const text =
      field === 'source'
        ? value === 'expert'
          ? '专家库'
          : '简历库'
        : field === 'relation_type'
          ? (relations[String(value)] ?? String(value))
          : field.endsWith('month')
            ? `${String(value).slice(0, 4)}-${String(value).slice(4)}`
            : String(value)
    conditions.push({
      id: field,
      field: field as keyof SearchRequest,
      label: `${prefix} · ${text}`,
    })
  }
  return conditions
}
