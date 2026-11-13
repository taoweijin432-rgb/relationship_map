import { onMounted, ref } from 'vue'
import { isRecord, parseSnapshot, type QuerySnapshot } from './queryState'
import { messageOf } from '../api/client'

const STORAGE_KEY = 'relationship-query.saved.v1'
interface SavedQuery {
  id: string
  name: string
  savedAt: string
  query: QuerySnapshot
}

function copyQuery(query: QuerySnapshot): QuerySnapshot {
  const result = parseSnapshot(JSON.parse(JSON.stringify(query)))
  if (!result) throw new Error('查询条件格式无效，请重新查询后保存')
  return result
}

export function useSavedQueries(
  capture: () => QuerySnapshot | null,
  restore: (query: QuerySnapshot) => Promise<void>,
) {
  const entries = ref<SavedQuery[]>([])
  const name = ref('')
  const message = ref('')
  const failed = ref(false)
  const restoring = ref(false)
  const corrupted = ref(false)

  function report(text: string, error = false) {
    message.value = text
    failed.value = error
  }

  onMounted(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const data: unknown = JSON.parse(raw)
      if (
        !isRecord(data) ||
        data.schemaVersion !== 1 ||
        !Array.isArray(data.entries) ||
        data.entries.length > 20
      )
        throw new Error('保存记录格式无效；未覆盖原记录')
      const parsed: SavedQuery[] = []
      for (const item of data.entries) {
        if (
          !isRecord(item) ||
          typeof item.id !== 'string' ||
          typeof item.name !== 'string' ||
          !item.name.trim() ||
          item.name.length > 40 ||
          typeof item.savedAt !== 'string'
        )
          throw new Error('保存记录损坏；未覆盖原记录')
        const query = parseSnapshot(item.query)
        if (!query) throw new Error('保存的查询条件格式无效；未覆盖原记录')
        parsed.push({ id: item.id, name: item.name, savedAt: item.savedAt, query })
      }
      entries.value = parsed
    } catch (error) {
      corrupted.value = true
      report(messageOf(error), true)
    }
  })

  function persist(next: SavedQuery[]) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ schemaVersion: 1, entries: next }))
      entries.value = next
      return true
    } catch {
      report('浏览器无法保存条件，请检查存储权限或剩余空间', true)
      return false
    }
  }

  function save() {
    if (corrupted.value) return report('请先清空损坏记录，再保存新条件', true)
    const query = capture()
    if (!query) return report('请等待查询成功后再保存条件', true)
    const label = name.value.trim()
    if (!label || label.length > 40) return report('请输入 1–40 字的条件名称', true)
    if (entries.value.length >= 20)
      return report('最多保存 20 组条件，请先删除不再使用的记录', true)
    if (entries.value.some((e) => e.name === label))
      return report('名称已存在，请使用其他名称', true)
    const randomBytes = crypto.getRandomValues(new Uint8Array(16))
    const id = Array.from(randomBytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    const entry = {
      id,
      name: label,
      savedAt: new Date().toISOString(),
      query: copyQuery(query),
    }
    if (persist([...entries.value, entry])) {
      name.value = ''
      report('条件已保存在本浏览器，仅保存条件，不保存结果')
    }
  }

  function clearCorrupted() {
    try {
      localStorage.removeItem(STORAGE_KEY)
      corrupted.value = false
      entries.value = []
      report('已清空损坏记录，可以重新保存条件')
    } catch {
      report('浏览器拒绝清空记录，请检查存储权限', true)
    }
  }

  function remove(id: string) {
    if (persist(entries.value.filter((e) => e.id !== id))) report('已删除保存条件')
  }

  async function apply(entry: SavedQuery) {
    if (restoring.value) return
    restoring.value = true
    try {
      const oldVersion = entry.query.dataVersion
      await restore(copyQuery(entry.query))
      const current = capture()
      if (!current) throw new Error('恢复条件后的查询未成功，请检查查询提示')
      report(
        current.dataVersion === oldVersion
          ? '条件已恢复，已重新查询第一页'
          : '数据版本已变化，条件已重新校验并查询；结果可能不同',
      )
    } catch (error) {
      report(messageOf(error), true)
    } finally {
      restoring.value = false
    }
  }

  return {
    entries,
    name,
    message,
    failed,
    restoring,
    corrupted,
    clearCorrupted,
    save,
    remove,
    apply,
  }
}
