import { onBeforeUnmount, ref, watch, type Ref, type ComputedRef } from 'vue'
import { api, messageOf, type GraphData, type SearchResponse } from '../api/client'
import { downloadBlob, graphImage, pageCsv } from './exports'
import type { QuerySnapshot } from './queryState'

export function usePageExport(
  result: Ref<SearchResponse | null>,
  snapshot: Ref<QuerySnapshot | null>,
  graph: Ref<GraphData>,
  getImage: () => Promise<string>,
  disabled: ComputedRef<boolean>,
) {
  const busy = ref(false)
  const message = ref('')
  let controller: AbortController | undefined
  watch([result, graph, disabled], () => {
    controller?.abort()
    busy.value = false
    message.value = ''
  })
  onBeforeUnmount(() => controller?.abort())

  async function exportFile(format: 'json' | 'csv' | 'png') {
    if (!result.value || !snapshot.value || busy.value || disabled.value) return
    const current = result.value
    const query = snapshot.value
    controller?.abort()
    const active = new AbortController()
    controller = active
    busy.value = true
    message.value = ''
    try {
      let blob: Blob
      if (format === 'png')
        blob = await graphImage(await getImage(), query, graph.value, current.data_mode)
      else {
        const data = await api.exportPage(
          {
            reference_id: current.reference?.id ?? null,
            filters: current.applied_filters,
            data_version: current.data_version,
            expected_person_ids: current.items.map((item) => item.person.id),
          },
          active.signal,
        )
        blob =
          format === 'json'
            ? new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
            : new Blob([pageCsv(data)], { type: 'text/csv;charset=utf-8' })
      }
      if (active.signal.aborted) return
      downloadBlob(blob, `relationship-${current.data_mode}-${Date.now()}.${format}`)
      message.value =
        format === 'png'
          ? `已导出局部图，图片含${current.data_mode === 'real' ? '真实数据标识' : '模拟标识'}和范围说明`
          : '已导出当前页；人物履历与筛选内关系证据分别标明'
    } catch (error) {
      if (!active.signal.aborted) message.value = `导出失败：${messageOf(error)}`
    } finally {
      if (!active.signal.aborted) busy.value = false
    }
  }
  return { busy, message, exportFile }
}
