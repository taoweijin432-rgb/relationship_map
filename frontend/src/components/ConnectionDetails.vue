<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, ref } from 'vue'
import {
  factLabel,
  factPeriod,
  monthLabel,
  type ConnectionDetail,
  type GraphNode,
} from '../api/client'
import { selectedPathGraph } from '../features/paths/view'

const props = defineProps<{
  connection: ConnectionDetail
  highlightedFactId?: string
  dataVersion: string
  referenceMonth: number
}>()
defineEmits<{ topic: [entity: GraphNode] }>()
const GraphCanvas = defineAsyncComponent(() => import('./GraphCanvas.vue'))
const showGraph = ref(false)
const root = ref<HTMLElement>()
const clickedFactId = ref('')
const selectedFactId = computed(() => clickedFactId.value || props.highlightedFactId)
const graph = computed(() => selectedPathGraph(props.connection.segments, {}))
async function selectEdge(id: string) {
  clickedFactId.value = graph.value.edges.find((edge) => edge.id === id)?.fact_id ?? ''
  await nextTick()
  root.value?.querySelector('.connection-fact-selected')?.scrollIntoView({ block: 'nearest' })
}
</script>

<template>
  <section ref="root" class="connection-details" data-testid="connection-details">
    <p class="connection-chain">
      <strong>{{ connection.hop_count }} 跳关联</strong>
      {{ connection.persons.map((person) => person.name).join(' → ') }}
    </p>
    <el-button size="small" @click="showGraph = !showGraph">{{
      showGraph ? '收起连接图' : '查看连接图'
    }}</el-button>
    <div v-if="showGraph" class="connection-graph">
      <GraphCanvas
        :data="graph"
        selected-id=""
        layout="chain"
        :data-version="dataVersion"
        :reference-month="referenceMonth"
        @edge-click="selectEdge"
        :highlighted-edge-ids="
          graph.edges.filter((edge) => edge.fact_id === selectedFactId).map((edge) => edge.id)
        "
      />
    </div>
    <section
      v-for="(segment, index) in connection.segments"
      :key="segment.id"
      class="connection-segment"
    >
      <h4>{{ index + 1 }} · {{ segment.from_person.name }} → {{ segment.to_person.name }}</h4>
      <p v-if="segment.evidence_truncated" class="detail-note">本段证据展示达到上限</p>
      <article
        v-for="proof in segment.evidence"
        :key="proof.id"
        class="proof-card"
        data-testid="connection-proof"
      >
        <div class="proof-label">{{ proof.label }}</div>
        <el-button
          link
          type="primary"
          @click="
            $emit('topic', {
              id: proof.entity.id,
              label: proof.entity.name,
              type:
                proof.entity.type === 'organization'
                  ? 'organization'
                  : proof.entity.type === 'major'
                    ? 'major'
                    : 'school',
              is_reference: false,
            })
          "
          >{{ proof.entity.name }}</el-button
        >
        <div v-if="proof.overlap_months" class="overlap-chip">
          {{ monthLabel(proof.overlap_start) }} — {{ monthLabel(proof.overlap_end) }}
          <strong>{{ proof.overlap_months }} 个月</strong>
        </div>
        <div
          v-for="(view, side) in [proof.reference, proof.candidate]"
          :key="view.fact.id"
          class="evidence-fact"
          :class="{ 'connection-fact-selected': selectedFactId === view.fact.id }"
        >
          <strong>{{ side === 0 ? segment.from_person.name : segment.to_person.name }}</strong>
          <span>{{ factLabel(view) }}</span
          ><small>{{ factPeriod(view) }}</small>
          <details class="source-details" :open="selectedFactId === view.fact.id">
            <summary>来源详情</summary>
            <small
              >{{ view.fact.source_system }} · {{ view.fact.source_record_id }} ·
              {{ view.fact.id }}</small
            >
          </details>
        </div>
        <p class="explanation">{{ proof.explanation }}</p>
      </article>
    </section>
  </section>
</template>

<style scoped>
.connection-details {
  padding: 16px;
}
.connection-chain {
  line-height: 1.9;
  overflow-wrap: anywhere;
}
.connection-chain strong {
  display: block;
}
.connection-segment h4 {
  margin: 20px 0 12px;
}
.connection-fact-selected {
  outline: 2px solid var(--el-color-primary);
}
.connection-graph {
  height: 340px;
  margin-top: 12px;
}
.connection-graph :deep(.graph-surface) {
  height: 100%;
  min-height: 0;
}
</style>
