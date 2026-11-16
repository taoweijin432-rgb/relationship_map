import type { components } from './schema'

export type Person = components['schemas']['Person']
export type Entity = components['schemas']['Entity']
export type SearchRequest = components['schemas']['SearchRequest']
export type SearchResponse = components['schemas']['SearchResponse']
export type GraphData = components['schemas']['GraphData']
export type GraphNode = components['schemas']['GraphNode']
export type GraphEdge = components['schemas']['GraphEdge']
export type FactsResponse = components['schemas']['FactsResponse']
export type EvidenceResponse = components['schemas']['EvidenceResponse']
export type PersonDetailsResponse = components['schemas']['PersonDetailsResponse']
export type MetaResponse = components['schemas']['MetaResponse']
export type ComparisonResponse = components['schemas']['ComparisonResponse']
export type FactView = components['schemas']['FactView']
export type Evidence = components['schemas']['Evidence']
export type EntityResponse = components['schemas']['EntityResponse']
export type ExportResponse = components['schemas']['ExportResponse']
export type ExportRequest = components['schemas']['ExportRequest']
export type PathRequest = components['schemas']['PathRequest']
export type PathResponse = components['schemas']['PathResponse']
export type PathSegment = components['schemas']['PathSegment']
export type ConnectionDetail = components['schemas']['ConnectionDetail']
export type RelationScope = components['schemas']['RelationScope']
export function factLabel(view: FactView): string {
  return (
    view.fact.position_title ||
    view.role?.name ||
    [view.fact.education_level, view.fact.is_regular_enrollment].filter(Boolean).join(' · ') ||
    (view.fact.type === 'employment'
      ? '工作经历（职位未知）'
      : view.fact.type === 'major'
        ? '所学专业'
        : '教育经历')
  )
}
export function factRelationLabel(type: FactView['fact']['type']): string {
  return { employment: '任职', education: '就读', major: '所学专业' }[type]
}
export function factPeriod(view: FactView): string {
  return `${monthLabel(view.fact.start_month)} — ${view.fact.is_current ? '当前任职' : monthLabel(view.fact.end_month)}`
}
type ExpandRequest = components['schemas']['ExpandRequest']

async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const message =
      payload &&
      typeof payload === 'object' &&
      'message' in payload &&
      typeof payload.message === 'string'
        ? payload.message
        : `请求失败（${response.status}）`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  paths: (body: PathRequest, signal: AbortSignal) =>
    request<PathResponse>('/relations/paths', body, signal),
  meta: (signal?: AbortSignal) => request<MetaResponse>('/meta', undefined, signal),
  compare: (referenceId: string, candidateId: string, signal: AbortSignal) =>
    request<ComparisonResponse>(
      '/persons/compare',
      {
        reference_id: referenceId,
        candidate_id: candidateId,
      },
      signal,
    ),
  people: (keyword = '', signal?: AbortSignal) =>
    request<components['schemas']['PersonsResponse']>(
      `/persons/suggest?q=${encodeURIComponent(keyword)}&limit=50`,
      undefined,
      signal,
    ),
  entities: (type: Entity['type'], keyword = '', signal?: AbortSignal) =>
    request<components['schemas']['EntitiesResponse']>(
      `/entities/suggest?type=${type}&q=${encodeURIComponent(keyword)}&limit=50`,
      undefined,
      signal,
    ),
  entity: (id: string, signal?: AbortSignal) =>
    request<EntityResponse>(`/entities/${encodeURIComponent(id)}`, undefined, signal),
  exportPage: (body: ExportRequest, signal: AbortSignal) =>
    request<ExportResponse>('/exports/persons', body, signal),
  search: (body: SearchRequest, referenceId: string | null, signal: AbortSignal) =>
    request<SearchResponse>(
      referenceId
        ? `/persons/${encodeURIComponent(referenceId)}/relations/search`
        : '/persons/search',
      body,
      signal,
    ),
  facts: (id: string, signal: AbortSignal) =>
    request<FactsResponse>(`/persons/${encodeURIComponent(id)}/facts`, undefined, signal),
  details: async (
    id: string,
    reference: string | undefined,
    signal: AbortSignal,
    filters?: SearchRequest,
  ): Promise<{ facts: FactsResponse; proof: EvidenceResponse | null }> => {
    const data = await request<PersonDetailsResponse>(
      `/persons/${encodeURIComponent(id)}/details`,
      { reference_id: reference, filters: filters ?? {} },
      signal,
    )
    const metadata = {
      data_mode: data.data_mode,
      data_version: data.data_version,
      reference_month: data.reference_month,
    }
    return {
      facts: { ...metadata, person: data.person, items: data.facts },
      proof: data.reference
        ? {
            ...metadata,
            reference: data.reference,
            candidate: data.person,
            items: data.evidence,
            connection: data.connection,
          }
        : null,
    }
  },
  expand: (body: ExpandRequest, signal: AbortSignal) =>
    request<components['schemas']['ExpandResponse']>('/graph/expand', body, signal),
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '服务暂不可用，请稍后重试'
}

export function monthLabel(month: number | null | undefined): string {
  return month ? `${Math.floor(month / 100)}.${String(month % 100).padStart(2, '0')}` : '时间未知'
}

export function dataModeLabel(mode: MetaResponse['data_mode'] | undefined): string {
  return mode === 'real' ? '真实数据' : '模拟数据'
}
