import type { SearchRequest } from '../api/client'

export type QueryMode = 'person' | 'entity' | 'topic'
export interface QuerySnapshot {
  mode: QueryMode
  referenceId: string
  topicId: string
  topicKind: 'organization' | 'school' | 'major'
  filters: SearchRequest
  dataVersion: string
}

export function backgroundFilters() {
  return {
    company: [] as string[],
    school: [] as string[],
    role: [] as string[],
    major: [] as string[],
    positions: [] as string[],
    source: '',
    start: '',
    end: '',
  }
}

export function personQueryFilters() {
  return {
    maxHops: 1,
    source: '',
    relation: 'same_company_overlap',
    sameSchoolRequired: true,
    company: [] as string[],
    start: '',
    end: '',
    minMonths: null as number | null,
  }
}

// 浏览器存储也需验证；只恢复条件，不保存或信任旧游标和查询结果。
export function parseSnapshot(value: unknown): QuerySnapshot | null {
  if (!isRecord(value) || !isRecord(value.filters)) return null
  if (!['person', 'entity', 'topic'].includes(String(value.mode))) return null
  if (
    value.topicKind !== 'organization' &&
    value.topicKind !== 'school' &&
    value.topicKind !== 'major'
  )
    return null
  if (
    ![value.referenceId, value.topicId, value.dataVersion].every(
      (v) => typeof v === 'string' && v.length <= 200,
    )
  )
    return null
  if ((value.mode === 'person' && !value.referenceId) || (value.mode === 'topic' && !value.topicId))
    return null
  const filters = value.filters
  const arrays = [
    'organization_ids',
    'school_ids',
    'major_ids',
    'role_ids',
    'relation_organization_ids',
    'position_titles',
  ]
  const months = ['start_month', 'end_month', 'relation_start_month', 'relation_end_month']
  const allowed = new Set([
    ...arrays,
    ...months,
    'source',
    'relation_type',
    'min_overlap_months',
    'page_size',
    'max_hops',
    'require_same_school',
  ])
  if (Object.keys(filters).some((k) => !allowed.has(k))) return null
  if (
    arrays.some(
      (k) =>
        filters[k] !== undefined &&
        (!Array.isArray(filters[k]) ||
          filters[k].length > 50 ||
          !filters[k].every(
            (id: unknown) =>
              typeof id === 'string' &&
              id.length > 0 &&
              id.length <= (k === 'position_titles' ? 255 : 100),
          )),
    )
  )
    return null
  if (months.some((k) => filters[k] != null && !validMonth(filters[k]))) return null
  if (filters.source != null && !['expert', 'resume'].includes(String(filters.source))) return null
  if (
    filters.relation_type != null &&
    !['same_company', 'same_company_overlap', 'same_school', 'same_major'].includes(
      String(filters.relation_type),
    )
  )
    return null
  if (
    filters.min_overlap_months != null &&
    (!Number.isInteger(filters.min_overlap_months) ||
      Number(filters.min_overlap_months) < 1 ||
      Number(filters.min_overlap_months) > 2412)
  )
    return null
  if (filters.require_same_school !== undefined && typeof filters.require_same_school !== 'boolean')
    return null
  if (filters.require_same_school && filters.relation_type !== 'same_major') return null
  if (filters.page_size !== 20) return null
  if (
    filters.max_hops !== undefined &&
    (!Number.isInteger(filters.max_hops) ||
      Number(filters.max_hops) < 1 ||
      Number(filters.max_hops) > 4)
  )
    return null
  return {
    mode: value.mode as QueryMode,
    referenceId: String(value.referenceId),
    topicId: String(value.topicId),
    topicKind: value.topicKind,
    filters: { ...filters, max_hops: filters.max_hops ?? 1 } as SearchRequest,
    dataVersion: String(value.dataVersion),
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validMonth(value: unknown) {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 190001 &&
    value <= 210012 &&
    value % 100 >= 1 &&
    value % 100 <= 12
  )
}

export function savedFilters(filters: SearchRequest): SearchRequest {
  const {
    cursor: _cursor,
    organization_id: _company,
    school_id: _school,
    role_id: _role,
    ...conditions
  } = filters
  return { ...conditions, page_size: 20 }
}
