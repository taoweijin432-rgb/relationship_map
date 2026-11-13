<script setup lang="ts">
import { experienceGroups } from '../features/experienceGroups'
import { computed } from 'vue'
import {
  factLabel,
  monthLabel,
  type ComparisonResponse,
  type FactView,
  type Evidence,
} from '../api/client'
import {
  monthIndex,
  indexMonth,
  timelineSides,
  type TimelineRow,
} from '../features/comparison/timeline'

const props = defineProps<{ data: ComparisonResponse; selectedEvidenceId: string }>()
const emit = defineEmits<{ selectEvidence: [id: string] }>()
const sides = computed(() => timelineSides(props.data))
const range = computed(() => {
  const rows = sides.value.flatMap((side) => side.rows)
  if (!rows.length) return null
  return {
    start: Math.min(...rows.map((row) => monthIndex(row.start))),
    end: Math.max(...rows.map((row) => monthIndex(row.end))) + 1,
  }
})
const ticks = computed(() => {
  const axis = range.value
  if (!axis) return []
  return Array.from({ length: 5 }, (_, i) => {
    const index = Math.round(axis.start + ((axis.end - axis.start - 1) * i) / 4)
    return {
      label: monthLabel(indexMonth(index)),
      left: `${((index - axis.start) / (axis.end - axis.start)) * 100}%`,
    }
  })
})
const selected = computed(() =>
  props.data.evidence.find((proof) => proof.id === props.selectedEvidenceId),
)
function factSelected(view: FactView) {
  return (
    selected.value &&
    [selected.value.reference.fact.id, selected.value.candidate.fact.id].includes(view.fact.id)
  )
}
function barStyle(row: TimelineRow) {
  const axis = range.value
  if (!axis) return {}
  const span = axis.end - axis.start
  return {
    left: `${((monthIndex(row.start) - axis.start) / span) * 100}%`,
    width: `${((monthIndex(row.end) - monthIndex(row.start) + 1) / span) * 100}%`,
  }
}
function overlapStyle(row: TimelineRow, proof: Evidence) {
  if (proof.overlap_start == null || proof.overlap_end == null) return {}
  const span = monthIndex(row.end) - monthIndex(row.start) + 1
  return {
    left: `${((monthIndex(proof.overlap_start) - monthIndex(row.start)) / span) * 100}%`,
    width: `${((monthIndex(proof.overlap_end) - monthIndex(proof.overlap_start) + 1) / span) * 100}%`,
  }
}
function selectFact(view: FactView) {
  const proof = props.data.evidence.find((ev) =>
    [ev.reference.fact.id, ev.candidate.fact.id].includes(view.fact.id),
  )
  if (proof) emit('selectEvidence', proof.id)
}
</script>

<template>
  <section class="career-timeline panel" aria-label="双方履历时间轴">
    <div class="panel-header">
      <h2>履历时间轴</h2>
      <span class="small muted">统一月份尺度 · 基准 {{ monthLabel(data.reference_month) }}</span>
    </div>
    <p class="timeline-description">
      深色区间仅表示有证据的同公司同期；缺失日期单独列出，不补全任期。同校不推断同期。
    </p>
    <div v-if="range" class="timeline-chart">
      <div class="timeline-axis">
        <span v-for="tick in ticks" :key="tick.left" :style="{ left: tick.left }">{{
          tick.label
        }}</span>
      </div>
      <section
        v-for="side in sides"
        :key="side.person.id"
        class="timeline-side"
        :aria-label="`${side.person.name}的时间轴`"
      >
        <div class="timeline-person-heading">
          <strong>{{ side.person.name }}</strong
          ><span>{{ side.person.id }}</span>
        </div>
        <div v-if="!side.rows.length" class="timeline-no-rows">暂无可绘制的完整时间区间</div>
        <div
          v-for="row in side.rows"
          :key="row.view.fact.id"
          class="career-row"
          :class="{ highlighted: factSelected(row.view) }"
          :data-testid="`timeline-${row.view.fact.id}`"
        >
          <div class="career-row-label">
            <strong>{{ row.view.entity.name }}</strong
            ><span
              >{{ factLabel(row.view) }}
              <b v-if="row.common">{{
                row.view.fact.type === 'major'
                  ? '同专业'
                  : row.view.fact.type === 'education'
                    ? '同校'
                    : '共同公司'
              }}</b></span
            >
          </div>
          <div class="career-track">
            <button
              class="career-bar"
              :class="{
                school: row.view.fact.type !== 'employment',
                current: row.view.fact.is_current,
              }"
              :style="barStyle(row)"
              :aria-label="`${side.person.name} ${row.view.entity.name} ${monthLabel(row.start)}至${monthLabel(row.end)}`"
              @click="selectFact(row.view)"
            >
              <span
                v-for="proof in row.overlaps"
                :key="proof.id"
                class="overlap-range"
                :style="overlapStyle(row, proof)"
                :title="`${monthLabel(proof.overlap_start)}—${monthLabel(proof.overlap_end)}，${proof.overlap_months}个月`"
                data-testid="timeline-overlap"
              /></button
            ><span class="career-period"
              >{{ monthLabel(row.start) }} —
              {{
                row.view.fact.is_current
                  ? `当前任职（截至 ${monthLabel(row.end)}）`
                  : monthLabel(row.end)
              }}</span
            >
          </div>
        </div>
      </section>
    </div>
    <div v-else class="timeline-no-rows">
      双方暂无完整时间区间；可在下方查看原始日期与共同经历证据。
    </div>
    <div class="undated-section">
      <h3>时间信息不完整的经历</h3>
      <div v-if="sides.every((side) => !side.undated.length)" class="muted small">
        双方经历均有可绘制的时间区间。
      </div>
      <div class="undated-grid">
        <section v-for="side in sides" :key="side.person.id">
          <article
            v-for="group in experienceGroups(side.undated)"
            :key="group.id"
            class="undated-fact"
            :class="{ highlighted: group.views.some(factSelected) }"
            :data-testid="`undated-${group.views[0].fact.id}`"
          >
            <div v-for="view in group.views" :key="view.fact.id">
              <strong>{{ side.person.name }} · {{ view.entity.name }}</strong
              ><span>{{ factLabel(view) }}</span>
              <span
                >{{ monthLabel(view.fact.start_month) }} —
                {{ monthLabel(view.fact.end_month) }}</span
              >
              <details class="source-details">
                <summary>来源详情</summary>
                <code>{{ view.fact.source_record_id }}</code
                ><code>{{ view.fact.id }}</code>
              </details>
            </div>
          </article>
        </section>
      </div>
    </div>
  </section>
</template>
