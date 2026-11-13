import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  api,
  messageOf,
  type Entity,
  type PathRequest,
  type PathResponse,
  type RelationScope,
} from '../../api/client'
import { usePersonPair } from '../usePersonPair'
import { personQueryFilters } from '../queryState'

export function usePaths(initialReference: string, initialCandidate: string) {
  const pair = usePersonPair(initialReference, initialCandidate)
  const filters = reactive(personQueryFilters())
  const limits = reactive({ candidates: 200, paths: 10 })
  const companies = ref<Entity[]>([])
  const result = ref<PathResponse | null>(null)
  const loading = ref(false)
  const error = ref('')
  const entityError = ref('')
  const cancelled = ref(false)
  let controller: AbortController | undefined
  let disposed = false
  let entitySequence = 0

  const submitted = ref('')
  const draft = computed(() =>
    JSON.stringify([pair.referenceId.value, pair.candidateId.value, filters, limits]),
  )
  const dirty = computed(() => draft.value !== submitted.value)

  async function search() {
    controller?.abort()
    error.value = ''
    cancelled.value = false
    loading.value = false
    if (!pair.referenceId.value || !pair.candidateId.value) {
      error.value = '请选择两位人物'
      return
    }
    if (pair.referenceId.value === pair.candidateId.value) {
      error.value = '请选择两位不同的人物'
      return
    }
    const submittedValue = draft.value
    const current = new AbortController()
    controller = current
    loading.value = true
    const body: PathRequest = {
      reference_id: pair.referenceId.value,
      candidate_id: pair.candidateId.value,
      scope: {
        relation_type: (filters.relation || null) as RelationScope['relation_type'],
        require_same_school: filters.relation === 'same_major' && filters.sameSchoolRequired,
        relation_organization_ids: filters.company,
        relation_start_month: filters.start ? Number(filters.start) : null,
        relation_end_month: filters.end ? Number(filters.end) : null,
        min_overlap_months: filters.minMonths,
      },
      intermediate_source: (filters.source || null) as PathRequest['intermediate_source'],
      limits: {
        candidate_limit: limits.candidates,
        path_limit: limits.paths,
        fact_limit: 2000,
        evidence_limit: 20,
        time_budget_ms: 1500,
      },
    }
    try {
      const response = await api.paths(body, current.signal)
      if (current.signal.aborted) return
      result.value = response
      submitted.value = submittedValue
      pair.remember([response.reference, response.candidate])
    } catch (err) {
      if (!current.signal.aborted) error.value = messageOf(err)
    } finally {
      if (!current.signal.aborted) loading.value = false
    }
  }

  function cancel() {
    result.value = null
    controller?.abort()
    loading.value = false
    error.value = ''
    cancelled.value = true
  }

  async function suggestCompanies(keyword = '') {
    const current = ++entitySequence
    entityError.value = ''
    try {
      const response = await api.entities('organization', keyword)
      if (disposed || current !== entitySequence) return
      const selected = companies.value.filter((company) => filters.company.includes(company.id))
      companies.value = [
        ...new Map(
          [...selected, ...response.items].map((company) => [company.id, company]),
        ).values(),
      ]
    } catch (err) {
      if (!disposed && current === entitySequence) entityError.value = messageOf(err)
    }
  }

  watch(
    () => filters.relation,
    (kind) => {
      if (kind !== 'same_company_overlap') {
        filters.start = ''
        filters.end = ''
        filters.minMonths = null
      }
      if (kind !== 'same_company_overlap' && kind !== 'same_company') filters.company = []
    },
    { flush: 'sync' },
  )
  watch(
    [pair.referenceId, pair.candidateId, filters, limits],
    () => {
      controller?.abort()
      error.value = ''
      cancelled.value = false
      loading.value = false
    },
    { deep: true, flush: 'sync' },
  )
  onMounted(() => {
    void suggestCompanies()
    if (pair.referenceId.value && pair.candidateId.value) void search()
  })
  onBeforeUnmount(() => {
    disposed = true
    controller?.abort()
  })
  return {
    ...pair,
    filters,
    limits,
    companies,
    result,
    dirty,
    loading,
    error,
    entityError,
    cancelled,
    search,
    cancel,
    suggestCompanies,
  }
}
