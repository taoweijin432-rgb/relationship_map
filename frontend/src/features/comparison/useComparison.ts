import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, messageOf, type ComparisonResponse } from '../../api/client'
import { usePersonPair } from '../usePersonPair'

export function useComparison(initialReference: string, initialCandidate: string) {
  const { referenceId, candidateId, choices, suggestionError, remember, suggest, swap } =
    usePersonPair(initialReference, initialCandidate)
  const result = ref<ComparisonResponse | null>(null)
  const loading = ref(false)
  const error = ref('')
  const dirty = computed(
    () =>
      !result.value ||
      result.value.reference.id !== referenceId.value ||
      result.value.candidate.id !== candidateId.value,
  )
  let controller: AbortController | undefined

  async function compare() {
    controller?.abort()
    error.value = ''
    loading.value = false
    if (!referenceId.value || !candidateId.value) {
      error.value = '请选择两位人物'
      return
    }
    if (referenceId.value === candidateId.value) {
      error.value = '请选择两位不同的人物进行对比'
      return
    }
    const current = new AbortController()
    controller = current
    loading.value = true
    try {
      const response = await api.compare(referenceId.value, candidateId.value, current.signal)
      if (current.signal.aborted) return
      result.value = response
      remember([response.reference, response.candidate])
    } catch (err) {
      if (!current.signal.aborted) error.value = messageOf(err)
    } finally {
      if (!current.signal.aborted) loading.value = false
    }
  }

  watch(
    [referenceId, candidateId],
    () => {
      controller?.abort()
      error.value = ''
      loading.value = false
    },
    { flush: 'sync' },
  )
  onMounted(() => {
    if (referenceId.value && candidateId.value) void compare()
  })
  onBeforeUnmount(() => {
    controller?.abort()
  })
  return {
    referenceId,
    candidateId,
    choices,
    result,
    dirty,
    loading,
    error,
    suggestionError,
    compare,
    suggest,
    swap,
  }
}
