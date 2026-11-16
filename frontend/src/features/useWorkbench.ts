import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  backgroundFilters,
  personQueryFilters,
  savedFilters,
  type QueryMode,
  type QuerySnapshot,
} from './queryState'
import {
  api,
  messageOf,
  type Entity,
  type EvidenceResponse,
  type FactsResponse,
  type GraphData,
  type GraphNode,
  type MetaResponse,
  type Person,
  type SearchRequest,
  type SearchResponse,
} from '../api/client'

const emptyGraph = (): GraphData => ({
  nodes: [],
  edges: [],
  truncated: false,
  truncation_reason: null,
})

export function useWorkbench() {
  const mode = ref<QueryMode>('person')
  const referenceId = ref('')
  const personFilters = reactive(personQueryFilters())
  const entityFilters = reactive(backgroundFilters())
  const topicFilters = reactive(backgroundFilters())
  const activeEntityFilters = computed(() =>
    mode.value === 'topic' ? topicFilters : entityFilters,
  )
  const topicId = ref('')
  const topicKind = ref<'organization' | 'school' | 'major'>('organization')
  const topic = ref<Entity | null>(null)
  const appliedSnapshot = ref<QuerySnapshot | null>(null)
  const meta = ref<MetaResponse | null>(null)
  const hasMaterializedRelations = computed(
    () =>
      meta.value?.relation_backend === 'nebula-materialized' ||
      meta.value?.graph_model === 'uuid-relations-v5',
  )
  const options = reactive<{
    people: Person[]
    organization: Entity[]
    school: Entity[]
    role: Entity[]
    major: Entity[]
  }>({
    people: [],
    organization: [],
    school: [],
    role: [],
    major: [],
  })
  const results = ref<SearchResponse | null>(null)
  const graph = ref<GraphData>(emptyGraph())
  const loading = ref(false)
  const error = ref('')
  const selectedId = ref('')
  const selectedEntity = ref<GraphNode | null>(null)
  const detail = ref<FactsResponse | null>(null)
  const evidence = ref<EvidenceResponse | null>(null)
  const detailError = ref('')
  const detailLoading = ref(false)
  const expanding = ref(false)
  const graphMessage = ref('')
  const highlightedEntityId = ref('')
  const selectedEdgeId = ref('')
  const pageIndex = ref(0)
  const cursors = ref<(string | null)[]>([null])
  let ready = false
  let disposed = false
  let queryController: AbortController | undefined
  let detailController: AbortController | undefined
  let expandController: AbortController | undefined
  let suggestSequence = 0
  let peopleController: AbortController | undefined
  const entityControllers: Partial<Record<Entity['type'], AbortController>> = {}
  let initializeController: AbortController | undefined
  const entitySequences = { organization: 0, school: 0, role: 0, major: 0 }
  let restoreController: AbortController | undefined

  const reference = computed(() => results.value?.reference ?? null)
  const requestFilters = (): SearchRequest =>
    mode.value === 'person'
      ? {
          relation_type: (personFilters.relation || null) as SearchRequest['relation_type'],
          require_same_school:
            personFilters.relation === 'same_major' && personFilters.sameSchoolRequired,
          source: (personFilters.source || null) as SearchRequest['source'],
          page_size: 20,
          max_hops: personFilters.maxHops,
          relation_organization_ids: personFilters.company,
          relation_start_month: personFilters.start ? Number(personFilters.start) : null,
          relation_end_month: personFilters.end ? Number(personFilters.end) : null,
          min_overlap_months: personFilters.minMonths,
        }
      : {
          require_same_school: false,
          max_hops: 1,
          organization_ids:
            mode.value === 'topic' && topicKind.value === 'organization'
              ? [topicId.value]
              : activeEntityFilters.value.company,
          school_ids:
            mode.value === 'topic' && topicKind.value === 'school'
              ? [topicId.value]
              : activeEntityFilters.value.school,
          role_ids: activeEntityFilters.value.role,
          major_ids:
            mode.value === 'topic' && topicKind.value === 'major'
              ? [topicId.value]
              : activeEntityFilters.value.major,
          position_titles: activeEntityFilters.value.positions,
          source: (activeEntityFilters.value.source || null) as SearchRequest['source'],
          start_month: activeEntityFilters.value.start
            ? Number(activeEntityFilters.value.start)
            : null,
          end_month: activeEntityFilters.value.end ? Number(activeEntityFilters.value.end) : null,
          page_size: 20,
        }

  function removeCondition(field: keyof SearchRequest, value?: string) {
    const common = mode.value === 'person' ? personFilters : activeEntityFilters.value
    const arrays: Partial<Record<keyof SearchRequest, string[]>> = {
      organization_ids: activeEntityFilters.value.company,
      school_ids: activeEntityFilters.value.school,
      major_ids: activeEntityFilters.value.major,
      role_ids: activeEntityFilters.value.role,
      position_titles: activeEntityFilters.value.positions,
      relation_organization_ids: personFilters.company,
    }
    const values = arrays[field]
    if (values && value) {
      const index = values.indexOf(value)
      if (index >= 0) values.splice(index, 1)
      return
    }
    const clear: Partial<Record<keyof SearchRequest, () => void>> = {
      max_hops: () => {
        personFilters.maxHops = 1
      },
      source: () => {
        common.source = ''
      },
      require_same_school: () => {
        personFilters.sameSchoolRequired = false
      },
      relation_type: () => {
        personFilters.relation = ''
      },
      start_month: () => {
        common.start = ''
      },
      end_month: () => {
        common.end = ''
      },
      relation_start_month: () => {
        common.start = ''
      },
      relation_end_month: () => {
        common.end = ''
      },
      min_overlap_months: () => {
        personFilters.minMonths = null
      },
    }
    clear[field]?.()
  }

  function clearDetail() {
    detailController?.abort()
    detail.value = null
    evidence.value = null
    selectedId.value = ''
    selectedEntity.value = null
    highlightedEntityId.value = ''
    selectedEdgeId.value = ''
    detailError.value = ''
    detailLoading.value = false
  }

  async function selectPerson(id: string, entityId = '', edgeId = '') {
    clearDetail()
    selectedId.value = id
    highlightedEntityId.value = entityId
    selectedEdgeId.value = edgeId
    const controller = new AbortController()
    detailController = controller
    detailLoading.value = true
    try {
      const root = reference.value?.id
      const { facts, proof } = await api.details(
        id,
        root && root !== id ? root : undefined,
        controller.signal,
        results.value?.applied_filters,
      )
      if (controller.signal.aborted) return
      if (
        results.value &&
        (facts.data_version !== results.value.data_version ||
          facts.reference_month !== results.value.reference_month)
      )
        throw new Error('关系图与经历版本不一致，请重新查询。')
      detail.value = facts
      evidence.value = proof
    } catch (err) {
      if (!controller.signal.aborted) detailError.value = messageOf(err)
    } finally {
      if (!controller.signal.aborted) detailLoading.value = false
    }
  }

  const draftSnapshot = computed(() => ({
    mode: mode.value,
    referenceId: referenceId.value,
    topicId: topicId.value,
    topicKind: topicKind.value,
    filters: savedFilters(requestFilters()),
  }))
  const submittedDraft = ref('')
  const dirty = computed(
    () => !appliedSnapshot.value || JSON.stringify(draftSnapshot.value) !== submittedDraft.value,
  )
  const actionsDisabled = computed(() => dirty.value || loading.value || !results.value)

  async function runQuery(reset = true, requestedPage = pageIndex.value) {
    queryController?.abort()
    restoreController?.abort()
    expandController?.abort()
    expanding.value = false
    loading.value = false
    const snapshot = JSON.parse(JSON.stringify(draftSnapshot.value)) as typeof draftSnapshot.value
    if (snapshot.mode === 'person' && !snapshot.referenceId) {
      error.value = '请先选择一位参考人物'
      return
    }
    if (snapshot.mode === 'topic' && !snapshot.topicId) {
      error.value = '请选择公司、学校或专业以查看专题'
      return
    }
    const controller = new AbortController()
    queryController = controller
    loading.value = true
    error.value = ''
    const targetPage = reset ? 0 : requestedPage
    try {
      let nextTopic: Entity | null = null
      if (snapshot.mode === 'topic') {
        const response = await api.entity(snapshot.topicId, controller.signal)
        if (controller.signal.aborted) return
        if (response.entity.type !== snapshot.topicKind)
          throw new Error('专题实体类型不匹配，请重新选择')
        nextTopic = response.entity
      }
      const response = await api.search(
        { ...snapshot.filters, cursor: reset ? null : cursors.value[targetPage] },
        snapshot.mode === 'person' ? snapshot.referenceId : null,
        controller.signal,
      )
      if (controller.signal.aborted || queryController !== controller) return
      clearDetail()
      results.value = response
      topic.value = nextTopic
      appliedSnapshot.value = {
        ...snapshot,
        dataVersion: response.data_version,
        filters: savedFilters(response.applied_filters),
      }
      // 比较用户提交值，后端的等价默认值和集合归一化不应造成待提交状态。
      submittedDraft.value = JSON.stringify(snapshot)
      graph.value = response.graph
      graphMessage.value = ''
      pageIndex.value = targetPage
      if (reset) cursors.value = [null]
      const first = response.items[0]?.person.id ?? response.reference?.id
      if (first) void selectPerson(first)
    } catch (err) {
      if (!controller.signal.aborted) error.value = messageOf(err)
    } finally {
      if (queryController === controller) loading.value = false
    }
  }

  function invalidate() {
    if (!ready) return
    restoreController?.abort()
    queryController?.abort()
    expandController?.abort()
    expanding.value = false
    loading.value = false
    error.value = ''
  }

  watch(draftSnapshot, invalidate, { deep: true, flush: 'sync' })

  function resetQuery() {
    invalidate()
    if (mode.value === 'person') {
      referenceId.value = ''
      Object.assign(personFilters, personQueryFilters())
    } else Object.assign(activeEntityFilters.value, backgroundFilters())
    if (mode.value === 'topic') mode.value = 'entity'
    results.value = null
    appliedSnapshot.value = null
    submittedDraft.value = ''
    topic.value = null
    graph.value = emptyGraph()
    clearDetail()
    pageIndex.value = 0
    cursors.value = [null]
  }

  watch(
    () => personFilters.relation,
    (kind) => {
      if (kind !== 'same_company_overlap') {
        personFilters.start = ''
        personFilters.end = ''
        personFilters.minMonths = null
      }
      if (kind !== 'same_company_overlap' && kind !== 'same_company') personFilters.company = []
    },
    { flush: 'sync' },
  )

  async function initialChoice<T>(
    request: Promise<T>,
    controller: AbortController,
  ): Promise<T | null> {
    try {
      return await request
    } catch (err) {
      if (controller.signal.aborted) return null
      throw err
    }
  }

  async function initialize() {
    if (disposed) return
    initializeController?.abort()
    const controller = new AbortController()
    initializeController = controller
    peopleController?.abort()
    const people = new AbortController()
    peopleController = people
    const peopleSequence = ++suggestSequence
    const entities = (['organization', 'school', 'role', 'major'] as const).map((kind) => {
      entityControllers[kind]?.abort()
      const pending = new AbortController()
      entityControllers[kind] = pending
      return { kind, controller: pending, sequence: ++entitySequences[kind] }
    })
    error.value = ''
    loading.value = true
    try {
      const [info, peopleResult, entityResults] = await Promise.all([
        api.meta(controller.signal),
        initialChoice(api.people('', people.signal), people),
        Promise.all(
          entities.map(({ kind, controller: pending }) =>
            initialChoice(api.entities(kind, '', pending.signal), pending),
          ),
        ),
      ])
      if (controller.signal.aborted) return
      meta.value = info
      if (peopleResult && peopleSequence === suggestSequence) options.people = peopleResult.items
      entities.forEach(({ kind, sequence }, index) => {
        const result = entityResults[index]
        if (result && sequence === entitySequences[kind]) options[kind] = result.items
      })
      ready = true
      loading.value = false
    } catch (err) {
      if (controller.signal.aborted) return
      controller.abort()
      people.abort()
      entities.forEach(({ controller: pending }) => pending.abort())
      error.value = messageOf(err)
      loading.value = false
    }
  }

  async function suggestPeople(keyword: string) {
    if (disposed) return
    peopleController?.abort()
    const controller = new AbortController()
    peopleController = controller
    const sequence = ++suggestSequence
    try {
      const response = await api.people(keyword, controller.signal)
      if (!controller.signal.aborted && sequence === suggestSequence) {
        const selected = options.people.find((p) => p.id === referenceId.value)
        options.people =
          selected && !response.items.some((p) => p.id === selected.id)
            ? [selected, ...response.items]
            : response.items
      }
    } catch (err) {
      if (!controller.signal.aborted && sequence === suggestSequence) error.value = messageOf(err)
    }
  }

  async function suggestEntities(kind: Entity['type'], keyword: string) {
    if (disposed) return
    entityControllers[kind]?.abort()
    const controller = new AbortController()
    entityControllers[kind] = controller
    const sequence = ++entitySequences[kind]
    try {
      const response = await api.entities(kind, keyword, controller.signal)
      if (controller.signal.aborted || sequence !== entitySequences[kind]) return
      const ids = new Set([
        ...entityFilters.company,
        ...entityFilters.school,
        ...entityFilters.role,
        ...entityFilters.major,
        ...topicFilters.company,
        ...topicFilters.school,
        ...topicFilters.role,
        ...topicFilters.major,
        ...personFilters.company,
        topicId.value,
      ])
      const choices = new Map(options[kind].filter((e) => ids.has(e.id)).map((e) => [e.id, e]))
      response.items.forEach((e) => choices.set(e.id, e))
      options[kind] = [...choices.values()]
    } catch (err) {
      if (!controller.signal.aborted && sequence === entitySequences[kind])
        error.value = messageOf(err)
    }
  }

  async function restoreQuery(snapshot: QuerySnapshot) {
    if (
      snapshot.mode === 'person' &&
      (snapshot.filters.max_hops ?? 1) > (meta.value?.max_relation_hops ?? 1)
    )
      throw new Error('当前数据模式支持1跳关联，请使用支持多跳的图数据源恢复这组条件')
    restoreController?.abort()
    const controller = new AbortController()
    restoreController = controller
    const ids = new Set([
      ...(snapshot.filters.organization_ids ?? []),
      ...(snapshot.filters.school_ids ?? []),
      ...(snapshot.filters.role_ids ?? []),
      ...(snapshot.filters.major_ids ?? []),
      ...(snapshot.filters.relation_organization_ids ?? []),
      ...(snapshot.mode === 'topic' ? [snapshot.topicId] : []),
    ])
    const [entities, person] = await Promise.all([
      Promise.all([...ids].map((id) => api.entity(id, controller.signal))),
      snapshot.mode === 'person'
        ? api.facts(snapshot.referenceId, controller.signal)
        : Promise.resolve(null),
    ])
    if (controller.signal.aborted) throw new Error('恢复已取消，筛选条件已变化')
    entities.forEach(({ entity }) => {
      if (!options[entity.type].some((e) => e.id === entity.id)) options[entity.type].push(entity)
    })
    if (person && !options.people.some((p) => p.id === person.person.id))
      options.people.push(person.person)
    ready = false
    mode.value = snapshot.mode
    referenceId.value = snapshot.referenceId
    topicId.value = snapshot.topicId
    topicKind.value = snapshot.topicKind
    const f = snapshot.filters
    if (snapshot.mode === 'person')
      Object.assign(personFilters, {
        source: f.source ?? '',
        relation: f.relation_type ?? '',
        sameSchoolRequired: f.require_same_school ?? false,
        company: f.relation_organization_ids ?? [],
        start: f.relation_start_month ? String(f.relation_start_month) : '',
        end: f.relation_end_month ? String(f.relation_end_month) : '',
        minMonths: f.min_overlap_months ?? null,
        maxHops: f.max_hops ?? 1,
      })
    else
      Object.assign(activeEntityFilters.value, {
        company: f.organization_ids ?? [],
        school: f.school_ids ?? [],
        role: f.role_ids ?? [],
        major: f.major_ids ?? [],
        positions: f.position_titles ?? [],
        source: f.source ?? '',
        start: f.start_month ? String(f.start_month) : '',
        end: f.end_month ? String(f.end_month) : '',
      })
    await nextTick()
    ready = true
    await runQuery()
  }

  async function openTopic(node?: GraphNode) {
    if (node && node.type !== 'person') {
      topicId.value = node.id
      topicKind.value = node.type
      const kind = node.type
      if (!options[kind].some((e) => e.id === node.id))
        options[kind].push({ id: node.id, name: node.label, type: kind, aliases: [] })
      Object.assign(topicFilters, backgroundFilters())
    }
    mode.value = 'topic'
    await runQuery()
  }

  function changePage(direction: 1 | -1) {
    if (actionsDisabled.value) return
    const nextPage = pageIndex.value + direction
    if (direction === 1 && results.value?.next_cursor) {
      cursors.value[nextPage] = results.value.next_cursor
    } else if (direction !== -1 || nextPage < 0) return
    void runQuery(false, nextPage)
  }

  async function setCenter(person: Person) {
    if (!options.people.some((p) => p.id === person.id)) options.people.push(person)
    mode.value = 'person'
    referenceId.value = person.id
    await runQuery()
  }

  function selectNode(id: string) {
    const node = graph.value.nodes.find((n) => n.id === id)
    if (!node) return
    if (node.type === 'person') void selectPerson(id)
    else {
      clearDetail()
      selectedEntity.value = node
    }
  }

  function selectEdge(id: string) {
    const edge = graph.value.edges.find((e) => e.id === id)
    if (edge) void selectPerson(edge.source, edge.target, edge.id)
  }

  function retryDetail() {
    void selectPerson(selectedId.value, highlightedEntityId.value, selectedEdgeId.value)
  }

  async function searchEntity(node: GraphNode) {
    if (node.type === 'person') return
    entityFilters.company = node.type === 'organization' ? [node.id] : []
    entityFilters.school = node.type === 'school' ? [node.id] : []
    entityFilters.major = node.type === 'major' ? [node.id] : []
    entityFilters.positions = []
    entityFilters.role = []
    entityFilters.start = ''
    entityFilters.end = ''
    entityFilters.source = ''
    mode.value = 'entity'
    await runQuery()
  }

  async function expandSelected() {
    if (!selectedId.value || expanding.value || actionsDisabled.value) return
    const controller = new AbortController()
    expandController?.abort()
    expandController = controller
    expanding.value = true
    graphMessage.value = ''
    try {
      const response = await api.expand(
        {
          person_id: selectedId.value,
          filters:
            appliedSnapshot.value?.mode === 'person'
              ? (results.value?.applied_filters ?? {
                  page_size: 20,
                  max_hops: 1,
                  require_same_school: false,
                })
              : {
                  page_size: 20,
                  max_hops: 1,
                  require_same_school: false,
                  source: results.value?.applied_filters.source,
                },
          existing_node_ids: graph.value.nodes.map((n) => n.id),
          existing_edge_ids: graph.value.edges.map((e) => e.id),
        },
        controller.signal,
      )
      if (controller.signal.aborted) return
      const nodes = new Map(graph.value.nodes.map((n) => [n.id, n]))
      const edges = new Map(graph.value.edges.map((e) => [e.id, e]))
      response.graph.nodes.forEach((n) =>
        nodes.set(n.id, { ...n, is_reference: n.id === reference.value?.id }),
      )
      response.graph.edges.forEach((e) => edges.set(e.id, e))
      graph.value = {
        nodes: [...nodes.values()],
        edges: [...edges.values()],
        truncated: response.graph.truncated,
        truncation_reason: response.graph.truncation_reason,
      }
      graphMessage.value =
        response.graph.truncation_reason ??
        (response.graph.nodes.length
          ? `已加入 ${response.graph.nodes.length} 个节点`
          : '这些直接关联已在图中，无新增节点')
    } catch (err) {
      if (!controller.signal.aborted) graphMessage.value = messageOf(err)
    } finally {
      if (!controller.signal.aborted) expanding.value = false
    }
  }

  onMounted(() => void initialize())
  onBeforeUnmount(() => {
    disposed = true
    initializeController?.abort()
    peopleController?.abort()
    Object.values(entityControllers).forEach((controller) => controller.abort())
    queryController?.abort()
    detailController?.abort()
    expandController?.abort()
    restoreController?.abort()
  })
  return {
    mode,
    referenceId,
    personFilters,
    entityFilters,
    activeEntityFilters,
    topicFilters,
    topicId,
    topicKind,
    topic,
    appliedSnapshot,
    options,
    meta,
    hasMaterializedRelations,
    results,
    graph,
    loading,
    error,
    selectedId,
    selectedEntity,
    detail,
    evidence,
    detailError,
    detailLoading,
    expanding,
    graphMessage,
    highlightedEntityId,
    selectedEdgeId,
    pageIndex,
    reference,
    runQuery,
    resetQuery,
    dirty,
    actionsDisabled,
    removeCondition,
    initialize,
    suggestPeople,
    suggestEntities,
    restoreQuery,
    openTopic,
    selectPerson,
    selectNode,
    selectEdge,
    retryDetail,
    setCenter,
    searchEntity,
    changePage,
    expandSelected,
  }
}
