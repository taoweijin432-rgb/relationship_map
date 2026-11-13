<script setup lang="ts">
import type { QuerySnapshot } from '../features/queryState'
import { useSavedQueries } from '../features/useSavedQueries'
const props = defineProps<{
  snapshot: QuerySnapshot | null
  restore: (query: QuerySnapshot) => Promise<void>
}>()
const {
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
} = useSavedQueries(() => props.snapshot, props.restore)
</script>
<template>
  <section class="saved-queries" aria-label="保存查询条件">
    <h3>常用条件 <span>仅此浏览器</span></h3>
    <el-input
      v-model="name"
      aria-label="条件名称"
      placeholder="为当前条件命名"
      :maxlength="40"
      @keyup.enter="save"
    />
    <el-button class="save-query-button" :disabled="!snapshot || restoring" @click="save"
      >保存当前条件</el-button
    >
    <p v-if="message" :role="failed ? 'alert' : 'status'" class="saved-message" :class="{ failed }">
      {{ message }}
    </p>
    <el-button v-if="corrupted" size="small" @click="clearCorrupted">清空损坏记录</el-button>
    <div v-for="entry in entries" :key="entry.id" class="saved-entry">
      <el-button
        text
        :disabled="restoring"
        :aria-label="`恢复条件 ${entry.name}`"
        @click="apply(entry)"
        >{{ entry.name }}</el-button
      >
      <el-button
        text
        :disabled="restoring"
        :aria-label="`删除条件 ${entry.name}`"
        @click="remove(entry.id)"
        >×</el-button
      >
    </div>
    <p v-if="!entries.length" class="small muted">保存后可恢复条件，重新查询最新数据。</p>
  </section>
</template>
