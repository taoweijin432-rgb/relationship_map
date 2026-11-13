<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Sort, Search } from '@element-plus/icons-vue'
import { factLabel, monthLabel, type GraphNode } from '../api/client'
import { useComparison } from '../features/comparison/useComparison'
import ExperienceList from './ExperienceList.vue'
import CareerTimeline from './CareerTimeline.vue'

const props = defineProps<{ referenceId: string; candidateId: string }>()
defineEmits<{ paths: [referenceId: string, candidateId: string]; topic: [entity: GraphNode] }>()
const tab = ref('evidence')
const {
  referenceId: left,
  candidateId: right,
  choices,
  result,
  dirty,
  loading,
  error,
  suggestionError,
  compare,
  suggest,
  swap,
} = useComparison(props.referenceId, props.candidateId)
const selectedEvidenceId = ref('')
watch(result, (value) => {
  selectedEvidenceId.value = value?.evidence[0]?.id ?? ''
})
const selected = computed(() =>
  result.value?.evidence.find((ev) => ev.id === selectedEvidenceId.value),
)
const commonCompanies = computed(
  () =>
    new Set(
      result.value?.evidence
        .filter((ev) => ev.entity.type === 'organization')
        .map((ev) => ev.entity.id),
    ).size,
)
const commonSchools = computed(
  () =>
    new Set(
      result.value?.evidence
        .filter((ev) => ev.relation_type === 'same_school')
        .map((ev) => ev.entity.id),
    ).size,
)
const commonMajors = computed(
  () =>
    new Set(
      result.value?.evidence
        .filter((proof) => proof.relation_type === 'same_major')
        .map((proof) => proof.entity.id),
    ).size,
)
const overlapCount = computed(
  () =>
    result.value?.evidence.filter((ev) => ev.relation_type === 'same_company_overlap').length ?? 0,
)
</script>

<template>
  <div class="comparison-workspace" data-testid="comparison-workspace">
    <section class="comparison-controls panel" aria-label="选择对比人物">
      <div>
        <label>人物 A</label
        ><el-select
          v-model="left"
          filterable
          remote
          :remote-method="suggest"
          placeholder="搜索姓名或业务编号"
          aria-label="对比人物A"
          data-testid="compare-left"
          ><el-option
            v-for="person in choices"
            :key="person.id"
            :value="person.id"
            :label="`${person.name} · ${person.id}`"
        /></el-select>
      </div>
      <el-button circle :icon="Sort" aria-label="交换对比人物" @click="swap" />
      <div>
        <label>人物 B</label
        ><el-select
          v-model="right"
          filterable
          remote
          :remote-method="suggest"
          placeholder="搜索姓名或业务编号"
          aria-label="对比人物B"
          data-testid="compare-right"
          ><el-option
            v-for="person in choices"
            :key="person.id"
            :value="person.id"
            :label="`${person.name} · ${person.id}`"
        /></el-select>
      </div>
      <el-button type="primary" :icon="Search" :loading="loading" @click="compare"
        >查看关系</el-button
      >
    </section>
    <p v-if="result && dirty" class="pending-changes" role="status">
      人物已修改，点击「查看关系」更新结果。
    </p>
    <el-alert
      v-if="suggestionError"
      :title="`人物选项加载失败：${suggestionError}`"
      type="error"
      :closable="false"
    />
    <div v-if="error" class="comparison-error">
      <el-alert :title="error" type="error" :closable="false" /><el-button @click="compare"
        >重试对比</el-button
      >
    </div>
    <section v-if="loading" class="panel comparison-loading">
      <el-skeleton :rows="8" animated />
    </section>
    <template v-else-if="result">
      <div class="comparison-persons">
        <article
          v-for="(person, index) in [result.reference, result.candidate]"
          :key="person.id"
          class="comparison-person panel"
          :data-testid="`compare-person-${index}`"
        >
          <span class="avatar large">{{ person.name.slice(-2) }}</span>
          <div>
            <span class="eyebrow">人物 {{ index === 0 ? 'A' : 'B' }}</span>
            <h2>{{ person.name }}</h2>
            <p>{{ person.headline }}</p>
            <span class="small muted">{{ person.city }} · {{ person.id }}</span>
          </div>
          <div class="person-tags">
            <span
              v-for="source in person.sources"
              :key="source"
              class="source-tag"
              :class="source"
              >{{ source === 'expert' ? '专家库' : '简历库' }}</span
            >
          </div>
        </article>
      </div>
      <div class="comparison-stats">
        <span
          >共同公司 <strong>{{ commonCompanies }}</strong></span
        ><span
          >共同学校 <strong>{{ commonSchools }}</strong></span
        ><span
          >共同专业 <strong>{{ commonMajors }}</strong></span
        ><span
          >同期证据 <strong>{{ overlapCount }}</strong></span
        ><small>{{ result.data_version }} · 不将多条证据的重叠月份相加</small>
      </div>
      <div class="pair-tabs" role="group" aria-label="两人关系内容">
        <button
          :class="{ active: tab === 'evidence' }"
          :aria-pressed="tab === 'evidence'"
          @click="tab = 'evidence'"
        >
          共同经历
        </button>
        <button
          :class="{ active: tab === 'timeline' }"
          :aria-pressed="tab === 'timeline'"
          @click="tab = 'timeline'"
        >
          时间轴
        </button>
        <button
          :class="{ active: tab === 'facts' }"
          :aria-pressed="tab === 'facts'"
          @click="tab = 'facts'"
        >
          完整履历
        </button>
        <button
          :disabled="dirty || loading"
          @click="$emit('paths', result.reference.id, result.candidate.id)"
        >
          经过谁连接
        </button>
      </div>
      <div v-if="tab === 'facts'" class="comparison-persons">
        <section class="panel detail-body">
          <h2>{{ result.reference.name }}</h2>
          <ExperienceList :views="result.reference_facts" @topic="$emit('topic', $event)" />
        </section>
        <section class="panel detail-body">
          <h2>{{ result.candidate.name }}</h2>
          <ExperienceList :views="result.candidate_facts" @topic="$emit('topic', $event)" />
        </section>
      </div>
      <CareerTimeline
        v-if="tab === 'timeline'"
        :data="result"
        :selected-evidence-id="selectedEvidenceId"
        @select-evidence="(id) => (selectedEvidenceId = id)"
      />
      <section
        v-if="tab === 'evidence'"
        class="comparison-evidence panel"
        aria-label="双方共同经历证据"
      >
        <div class="panel-header">
          <h2>共同经历与来源证据</h2>
          <span class="small muted">{{ result.evidence.length }} 条证据</span>
        </div>
        <div
          v-if="!result.evidence.length"
          class="empty-state"
          data-testid="comparison-no-evidence"
        >
          <strong>没有共同经历证据</strong
          ><span>仅说明当前数据未提供共同经历，不推断两人的实际关系。</span>
        </div>
        <div v-else class="comparison-proof-grid">
          <div class="comparison-proof-choices">
            <button
              v-for="proof in result.evidence"
              :key="proof.id"
              :class="{ selected: selectedEvidenceId === proof.id }"
              :aria-pressed="selectedEvidenceId === proof.id"
              @click="selectedEvidenceId = proof.id"
              data-testid="comparison-proof"
            >
              <span class="proof-label">{{ proof.label }}</span
              ><strong>{{ proof.entity.name }}</strong
              ><span v-if="proof.overlap_months"
                >{{ monthLabel(proof.overlap_start) }} — {{ monthLabel(proof.overlap_end) }} ·
                {{ proof.overlap_months }} 个月</span
              ><span v-else>查看双方经历及来源</span>
            </button>
          </div>
          <article
            v-if="selected"
            class="comparison-proof-detail"
            data-testid="comparison-proof-detail"
          >
            <h3>{{ selected.entity.name }} · {{ selected.label }}</h3>
            <p>{{ selected.explanation }}</p>
            <div class="comparison-fact-pair">
              <div
                v-for="(view, index) in [selected.reference, selected.candidate]"
                :key="view.fact.id"
              >
                <strong>{{ index === 0 ? result.reference.name : result.candidate.name }}</strong
                ><span>{{ factLabel(view) }}</span
                ><span
                  >{{ monthLabel(view.fact.start_month) }} —
                  {{ view.fact.is_current ? '当前任职' : monthLabel(view.fact.end_month) }}</span
                ><small>{{ view.fact.source_system === 'expert' ? '专家库' : '简历库' }}</small
                ><code>{{ view.fact.id }}</code
                ><code>{{ view.fact.source_record_id }}</code>
              </div>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>
