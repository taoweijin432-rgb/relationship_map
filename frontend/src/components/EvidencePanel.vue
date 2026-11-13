<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import ExperienceList from './ExperienceList.vue'
import ConnectionDetails from './ConnectionDetails.vue'
import { experienceGroups } from '../features/experienceGroups'
import { ArrowRight, Document, Connection } from '@element-plus/icons-vue'
import {
  factLabel,
  factPeriod,
  monthLabel,
  type FactsResponse,
  type MetaResponse,
  type EvidenceResponse,
  type GraphNode,
  type GraphEdge,
} from '../api/client'

const props = defineProps<{
  dataMode?: MetaResponse['data_mode']
  canCompare: boolean
  detail: FactsResponse | null
  evidence: EvidenceResponse | null
  loading: boolean
  error: string
  entity: GraphNode | null
  highlightedEntityId: string
  selectedEdge?: GraphEdge | null
}>()
defineEmits<{
  center: [person: FactsResponse['person']]
  entitySearch: [entity: GraphNode]
  entityTopic: [entity: GraphNode]
  retry: []
  compare: []
}>()
const tab = ref('evidence')
const scrollBody = ref<HTMLElement>()
const selectedFact = computed(() =>
  props.detail?.items.find((view) => view.fact.id === props.selectedEdge?.fact_id),
)
const groupCount = computed(() => experienceGroups(props.detail?.items ?? []).length)
watch([() => props.detail?.person.id, () => props.selectedEdge?.id], async () => {
  tab.value =
    (props.evidence?.connection?.hop_count ?? 1) > 1
      ? 'connection'
      : props.evidence
        ? 'evidence'
        : 'facts'
  await nextTick()
  scrollBody.value?.scrollTo({ top: 0 })
})
const proofs = computed(() =>
  (props.evidence?.items ?? []).filter(
    (ev) =>
      (!props.highlightedEntityId || ev.entity.id === props.highlightedEntityId) &&
      (!props.selectedEdge ||
        ev.reference.fact.id === props.selectedEdge.fact_id ||
        ev.candidate.fact.id === props.selectedEdge.fact_id),
  ),
)
</script>

<template>
  <aside class="evidence-panel panel" aria-label="证据详情">
    <div class="panel-header">
      <h2>人物与证据</h2>
      <el-icon class="muted"><Document /></el-icon>
    </div>
    <div v-if="loading" class="detail-body"><el-skeleton :rows="10" animated /></div>
    <div v-else-if="error" class="detail-body">
      <el-alert :title="error" type="error" :closable="false" /><el-button
        class="mt"
        @click="$emit('retry')"
        >重新加载详情</el-button
      >
    </div>
    <div v-else-if="entity" class="detail-body">
      <div class="entity-symbol">
        {{ entity.type === 'major' ? '专' : entity.type === 'organization' ? '企' : '学' }}
      </div>
      <h3>{{ entity.label }}</h3>
      <p class="muted">
        {{
          entity.type === 'major'
            ? '标准专业实体'
            : entity.type === 'organization'
              ? '标准公司实体'
              : '标准学校实体'
        }}
      </p>
      <p class="detail-note">
        当前图展示本页人物与此实体的经历关联。可切换到实体入口，查看完整筛选结果。
      </p>
      <el-button type="primary" @click="$emit('entitySearch', entity)"
        >通过此实体找人 <el-icon><ArrowRight /></el-icon
      ></el-button>
      <el-button class="mt" @click="$emit('entityTopic', entity)">查看实体专题</el-button>
    </div>
    <div
      v-else-if="detail"
      ref="scrollBody"
      class="detail-scroll"
      role="region"
      aria-label="人物与证据内容"
      tabindex="0"
    >
      <section v-if="selectedEdge" class="selected-edge-detail" data-testid="selected-edge-detail">
        <span class="proof-label">选中连线 · {{ selectedEdge.label }}</span>
        <template v-if="selectedFact">
          <h3>{{ detail.person.name }} → {{ selectedFact.entity.name }}</h3>
          <p>{{ factLabel(selectedFact) }}</p>
          <p>{{ factPeriod(selectedFact) }}</p>
          <details class="source-details">
            <summary>这条连线的来源</summary>
            <p>{{ selectedFact.fact.source_system === 'expert' ? '专家库' : '简历库' }}</p>
            <code>{{ selectedFact.fact.source_record_id }}</code>
            <code>{{ selectedFact.fact.id }}</code>
          </details>
        </template>
        <p v-else>当前有效履历中未找到这条连线，请重新查询。</p>
      </section>
      <div class="detail-person">
        <span class="avatar large">{{ detail.person.name.slice(-2) }}</span>
        <h3>{{ detail.person.name }}</h3>
        <p>{{ detail.person.headline }}</p>
        <details class="person-identifiers">
          <summary>人物编号与来源</summary>
          <p v-if="detail.person.serial_number">业务编号 {{ detail.person.serial_number }}</p>
          <p>{{ detail.person.city }} · {{ detail.person.id }}</p>
        </details>
        <div class="person-tags">
          <span
            v-for="source in detail.person.sources"
            :key="source"
            class="source-tag"
            :class="source"
            >{{ source === 'expert' ? '专家库' : '简历库' }}</span
          >
        </div>
        <el-button plain type="primary" size="small" @click="$emit('center', detail.person)"
          ><el-icon><Connection /></el-icon>以此人为中心查询</el-button
        >
        <div v-if="canCompare" class="compare-detail-action">
          <el-button type="primary" plain size="small" @click="$emit('compare')"
            >与参考人物对比</el-button
          >
        </div>
      </div>
      <div class="detail-tabs" role="tablist" aria-label="详情内容">
        <button
          v-if="evidence?.connection"
          role="tab"
          :aria-selected="tab === 'connection'"
          :class="{ active: tab === 'connection' }"
          @click="tab = 'connection'"
        >
          连接链
        </button>
        <button
          v-if="evidence"
          role="tab"
          :aria-selected="tab === 'evidence'"
          :class="{ active: tab === 'evidence' }"
          @click="tab = 'evidence'"
        >
          共同经历 <span>{{ proofs.length }}</span>
        </button>
        <button
          role="tab"
          :aria-selected="tab === 'facts'"
          :class="{ active: tab === 'facts' }"
          @click="tab = 'facts'"
        >
          人物经历 <span>{{ groupCount }}</span>
        </button>
      </div>
      <ConnectionDetails
        v-if="tab === 'connection' && evidence?.connection"
        :key="evidence.connection.person_ids.join('|')"
        :connection="evidence.connection"
        :data-version="evidence.data_version"
        :reference-month="evidence.reference_month"
        :highlighted-fact-id="selectedEdge?.fact_id"
        @topic="$emit('entityTopic', $event)"
      />
      <div class="proof-list" v-else-if="tab === 'evidence' && evidence">
        <p class="proof-context">
          与 <strong>{{ evidence.reference.name }}</strong> 的共同经历
        </p>
        <div v-if="!proofs.length" class="detail-note">这两个人物没有可核实的共同经历证据。</div>
        <article
          v-for="proof in proofs"
          :key="proof.id"
          class="proof-card"
          data-testid="evidence-card"
        >
          <div class="proof-label">{{ proof.label }}</div>
          <h4>{{ proof.entity.name }}</h4>
          <div v-if="proof.overlap_months" class="overlap-chip">
            {{ monthLabel(proof.overlap_start) }} — {{ monthLabel(proof.overlap_end) }}
            <strong>{{ proof.overlap_months }} 个月</strong>
          </div>
          <div
            v-for="(view, index) in [proof.reference, proof.candidate]"
            :key="view.fact.id"
            class="evidence-fact"
          >
            <span class="timeline-dot" /><strong>{{
              index === 0 ? evidence.reference.name : detail.person.name
            }}</strong>
            <span>{{ factLabel(view) }}</span>
            <small
              >{{ monthLabel(view.fact.start_month) }} —
              {{ view.fact.is_current ? '当前任职' : monthLabel(view.fact.end_month) }}</small
            >
            <details class="source-details">
              <summary>来源详情</summary>
              <small class="source-record"
                >{{ view.fact.source_system === 'expert' ? '专家库' : '简历库' }} ·
                {{ view.fact.source_record_id }} · {{ view.fact.id }}</small
              >
            </details>
          </div>
          <p class="explanation">{{ proof.explanation }}</p>
        </article>
      </div>
      <div v-else class="proof-list">
        <ExperienceList
          :views="detail.items"
          :highlighted-fact-id="selectedEdge?.fact_id"
          @topic="$emit('entityTopic', $event)"
        />
        <p v-if="!detail.items.length" class="detail-note">该人物暂无有效经历。</p>
      </div>
    </div>
    <div v-else class="empty-state">
      <el-icon :size="30"><Document /></el-icon><strong>每条连接，都有依据</strong
      ><span>选择人物或关系，查看来源经历</span>
    </div>
    <div class="evidence-footer">
      {{
        (dataMode ?? detail?.data_mode) === 'real'
          ? '人物与经历来自真实数据快照'
          : '全部人物与经历均为虚构样例'
      }}
    </div>
  </aside>
</template>
