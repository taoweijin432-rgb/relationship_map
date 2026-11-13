<script setup lang="ts">
import { computed } from 'vue'
import { factLabel, monthLabel, type FactView, type GraphNode } from '../api/client'
import { experienceGroups } from '../features/experienceGroups'
const props = defineProps<{ views: FactView[]; highlightedFactId?: string }>()
const emit = defineEmits<{ topic: [entity: GraphNode] }>()
const groups = computed(() => experienceGroups(props.views))
function open(view: FactView) {
  if (view.entity.type === 'role') return
  emit('topic', {
    id: view.entity.id,
    label: view.entity.name,
    type: view.entity.type,
    is_reference: false,
  })
}
</script>
<template>
  <div class="experience-list">
    <article
      v-for="group in groups"
      :key="group.id"
      class="fact-card"
      data-testid="experience-group"
    >
      <span class="muted small">{{
        group.views[0].fact.type === 'employment' ? '工作经历' : '教育经历'
      }}</span>
      <div
        v-for="view in group.views"
        :key="view.fact.id"
        class="experience-fact"
        :class="{ 'selected-fact': view.fact.id === highlightedFactId }"
      >
        <el-button
          text
          class="entity-link"
          :aria-label="`查看${view.entity.name}专题`"
          @click="open(view)"
          >{{ view.entity.name }}</el-button
        >
        <p>{{ factLabel(view) }}</p>
        <p class="small muted">
          {{ monthLabel(view.fact.start_month) }} —
          {{ view.fact.is_current ? '当前任职' : monthLabel(view.fact.end_month) }}
        </p>
      </div>
      <details class="source-details">
        <summary>来源详情 · {{ group.views.length }} 条事实</summary>
        <div v-for="view in group.views" :key="view.fact.id">
          <p>{{ view.fact.source_system === 'expert' ? '专家库' : '简历库' }}</p>
          <code>{{ view.fact.id }}</code
          ><code>{{ view.fact.source_record_id }}</code
          ><code v-if="view.fact.experience_key">{{ view.fact.experience_key }}</code>
        </div>
      </details>
    </article>
  </div>
</template>
