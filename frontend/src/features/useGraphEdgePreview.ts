import { onBeforeUnmount, ref, watch } from 'vue'
import { api, messageOf, type FactsResponse, type FactView, type GraphData } from '../api/client'

export function useGraphEdgePreview(
  data: () => GraphData,
  version: () => string | undefined,
  referenceMonth: () => number | undefined,
) {
  const hoveredId = ref('')
  const view = ref<FactView | null>(null)
  const loading = ref(false)
  const error = ref('')
  const cache = new Map<string, FactsResponse>()
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined

  function hide() {
    clearTimeout(timer)
    controller?.abort()
    hoveredId.value = ''
    view.value = null
    loading.value = false
    error.value = ''
  }

  function show(id: string) {
    if (id === hoveredId.value) return
    hide()
    const edge = data().edges.find((item) => item.id === id)
    const person = data().nodes.find(
      (node) => node.type === 'person' && (node.id === edge?.source || node.id === edge?.target),
    )
    if (!edge || !person) return
    hoveredId.value = id
    loading.value = true
    const request = new AbortController()
    controller = request
    // 掠过连线时不发请求，缓存仅属于当前图版本并在图更新时清除。
    timer = setTimeout(async () => {
      try {
        const facts = cache.get(person.id) ?? (await api.facts(person.id, request.signal))
        if (request.signal.aborted) return
        if (
          (version() && facts.data_version !== version()) ||
          (referenceMonth() != null && facts.reference_month !== referenceMonth())
        )
          throw new Error('关系图与经历版本不一致，请重新查询。')
        cache.set(person.id, facts)
        const matched = facts.items.find(
          (item) => item.fact.id === edge.fact_id && item.fact.person_id === person.id,
        )
        if (!matched) throw new Error('该连线的有效经历暂不可用，请重新查询。')
        view.value = matched
      } catch (err) {
        if (!request.signal.aborted) error.value = messageOf(err)
      } finally {
        if (!request.signal.aborted) loading.value = false
      }
    }, 150)
  }

  watch([data, version, referenceMonth], () => {
    hide()
    cache.clear()
  })
  onBeforeUnmount(hide)
  return { hoveredId, view, loading, error, show, hide }
}
