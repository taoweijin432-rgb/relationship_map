import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, messageOf, type Person } from '../api/client'

export function usePersonPair(initialReference: string, initialCandidate: string) {
  const referenceId = ref(initialReference)
  const candidateId = ref(initialCandidate)
  const choices = ref<Person[]>([])
  const suggestionError = ref('')
  let sequence = 0
  let disposed = false

  function remember(people: Person[]) {
    const byId = new Map(choices.value.map((person) => [person.id, person]))
    people.forEach((person) => byId.set(person.id, person))
    choices.value = [...byId.values()]
  }

  async function suggest(keyword = '') {
    const current = ++sequence
    suggestionError.value = ''
    try {
      const response = await api.people(keyword)
      if (disposed || current !== sequence) return
      const selected = choices.value.filter((person) =>
        [referenceId.value, candidateId.value].includes(person.id),
      )
      choices.value = response.items
      remember(selected)
    } catch (error) {
      if (!disposed && current === sequence) suggestionError.value = messageOf(error)
    }
  }

  function swap() {
    const previous = referenceId.value
    referenceId.value = candidateId.value
    candidateId.value = previous
  }

  onMounted(() => void suggest())
  onBeforeUnmount(() => {
    disposed = true
  })
  return { referenceId, candidateId, choices, suggestionError, remember, suggest, swap }
}
