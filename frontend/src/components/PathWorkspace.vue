<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { Search, Sort, Aim } from '@element-plus/icons-vue'
import { factLabel, monthLabel, type PathSegment } from '../api/client'
import { usePaths } from '../features/paths/usePaths'
import { pathLimitLabels, selectedPathGraph } from '../features/paths/view'
import { entityOptionLabel } from '../features/entityLabels'

const props = defineProps<{ referenceId: string; candidateId: string; allowMajor?: boolean }>()
const emit = defineEmits<{ compare: [referenceId: string, candidateId: string] }>()
const {
  referenceId: left,
  candidateId: right,
  choices,
  suggestionError,
  suggest,
  swap,
  filters,
  limits,
  companies,
  result,
  dirty,
  loading,
  error,
  entityError,
  cancelled,
  search,
  cancel,
  suggestCompanies,
} = usePaths(props.referenceId, props.candidateId)
const advancedCount = computed(
  () =>
    filters.company.length +
    Number(!!filters.source) +
    Number(!!filters.start) +
    Number(!!filters.end) +
    Number(filters.minMonths != null) +
    Number(limits.candidates !== 200) +
    Number(limits.paths !== 10),
)
const advancedDetails = ref<HTMLDetailsElement>()
function adjustRange() {
  if (advancedDetails.value) {
    advancedDetails.value.open = true
    advancedDetails.value.scrollIntoView({ block: 'center', behavior: 'smooth' })
    advancedDetails.value.querySelector<HTMLElement>('summary')?.focus()
  }
}
const selectedKey = ref('')
const segmentIndex = ref(0)
const chosenEvidence = ref<Record<string, string>>({})
const selectedPerson = ref('')
const canvas = ref<{ fit: () => void }>()
const GraphCanvas = defineAsyncComponent(() => import('./GraphCanvas.vue'))

watch(result, (data) => {
  selectedKey.value = data?.direct ? 'direct' : (data?.paths[0]?.id ?? '')
  chosenEvidence.value = {}
  selectedPerson.value = data?.reference.id ?? ''
})
watch(selectedKey, () => {
  segmentIndex.value = 0
})
const segments = computed<PathSegment[]>(() =>
  selectedKey.value === 'direct'
    ? result.value?.direct
      ? [result.value.direct]
      : []
    : (result.value?.paths.find((path) => path.id === selectedKey.value)?.segments ?? []),
)
const currentSegment = computed(() => segments.value[segmentIndex.value])
const currentProof = computed(
  () =>
    currentSegment.value?.evidence.find(
      (proof) => proof.id === chosenEvidence.value[currentSegment.value?.id ?? ''],
    ) ?? currentSegment.value?.evidence[0],
)
const graph = computed(() => selectedPathGraph(segments.value, chosenEvidence.value))
const highlight = computed(() => [
  `leg:${segmentIndex.value}:left`,
  `leg:${segmentIndex.value}:right`,
])
const participants = computed(() =>
  segments.value.length
    ? [segments.value[0].from_person, ...segments.value.map((segment) => segment.to_person)]
    : [],
)
const person = computed(() => participants.value.find((value) => value.id === selectedPerson.value))
function selectNode(id: string) {
  if (id.startsWith('path-entity:')) segmentIndex.value = Number(id.split(':')[1])
  else selectedPerson.value = id
}
function selectEdge(id: string) {
  segmentIndex.value = Number(id.split(':')[1])
}
function selectProof(id: string) {
  const segment = currentSegment.value
  if (segment) chosenEvidence.value[segment.id] = id
}
</script>

<template>
  <div class="path-workspace" data-testid="path-workspace">
    <section class="comparison-controls panel" aria-label="选择路径端点">
      <div>
        <label>人物 A</label
        ><el-select
          v-model="left"
          filterable
          remote
          :remote-method="suggest"
          placeholder="搜索姓名或业务编号"
          aria-label="路径人物A"
          data-testid="path-left"
        >
          <el-option
            v-for="person in choices"
            :key="person.id"
            :value="person.id"
            :label="`${person.name} · ${person.id}`"
          />
        </el-select>
      </div>
      <el-button circle :icon="Sort" aria-label="交换路径端点" @click="swap" />
      <div>
        <label>人物 B</label
        ><el-select
          v-model="right"
          filterable
          remote
          :remote-method="suggest"
          placeholder="搜索姓名或业务编号"
          aria-label="路径人物B"
          data-testid="path-right"
        >
          <el-option
            v-for="person in choices"
            :key="person.id"
            :value="person.id"
            :label="`${person.name} · ${person.id}`"
          />
        </el-select>
      </div>
      <el-button type="primary" :icon="Search" :loading="loading" @click="search"
        >搜索连接链</el-button
      >
      <el-button v-if="loading" @click="cancel">取消搜索</el-button>
    </section>
    <p v-if="result && dirty" class="pending-changes" role="status">
      条件已修改，点击「搜索连接链」更新结果。
    </p>
    <section class="path-rule-primary panel" aria-label="连接关系类型">
      <div>
        <label>每一段允许的关系</label
        ><el-select
          v-model="filters.relation"
          :empty-values="[null, undefined]"
          aria-label="路径关系类型"
          data-testid="path-relation"
        >
          <el-option label="同公司同期" value="same_company_overlap" /><el-option
            label="曾任职同一公司"
            value="same_company"
          /><el-option label="同校" value="same_school" /><el-option
            v-if="allowMajor"
            label="同专业"
            value="same_major"
          /><el-option label="全部共同经历（可混合）" value="" />
        </el-select>
      </div>
      <el-checkbox
        v-if="filters.relation === 'same_major'"
        v-model="filters.sameSchoolRequired"
        data-testid="path-same-school-required"
        >每段要求同校</el-checkbox
      >
    </section>
    <details ref="advancedDetails" class="path-advanced">
      <summary>
        更多筛选<span v-if="advancedCount">（{{ advancedCount }}）</span>
      </summary>
      <section class="path-filters panel" aria-label="连接链规则">
        <div>
          <label>中间人物来源</label
          ><el-select
            v-model="filters.source"
            :empty-values="[null, undefined]"
            aria-label="中间人物来源"
            data-testid="path-source"
          >
            <el-option label="专家库与简历库" value="" /><el-option
              label="仅专家库"
              value="expert"
            /><el-option label="仅简历库" value="resume" />
          </el-select>
        </div>
        <div v-if="['same_company', 'same_company_overlap'].includes(filters.relation)">
          <label>每段共同公司</label
          ><el-select
            v-model="filters.company"
            multiple
            collapse-tags
            clearable
            filterable
            remote
            :remote-method="suggestCompanies"
            aria-label="路径共同公司"
            placeholder="不限公司"
            data-testid="path-company"
          >
            <el-option
              v-for="company in companies"
              :key="company.id"
              :value="company.id"
              :label="entityOptionLabel(company, companies)"
            />
          </el-select>
        </div>
        <template v-if="filters.relation === 'same_company_overlap'">
          <div>
            <label>同期窗口起始月</label
            ><el-date-picker
              v-model="filters.start"
              type="month"
              format="YYYY-MM"
              value-format="YYYYMM"
              aria-label="路径同期开始月"
              placeholder="不限"
            />
          </div>
          <div>
            <label>同期窗口结束月</label
            ><el-date-picker
              v-model="filters.end"
              type="month"
              format="YYYY-MM"
              value-format="YYYYMM"
              aria-label="路径同期结束月"
              placeholder="不限"
            />
          </div>
          <div>
            <label>每段最短同期月数</label
            ><el-input-number
              v-model="filters.minMonths"
              :min="1"
              :max="2412"
              :precision="0"
              controls-position="right"
              aria-label="路径最短同期月数"
            />
          </div>
        </template>
        <details class="path-budget-controls">
          <summary>搜索范围：最多一位中间人物</summary>
          <div>
            <label>最多核查中间候选</label
            ><el-input-number
              v-model="limits.candidates"
              :min="1"
              :max="500"
              :precision="0"
              controls-position="right"
              aria-label="中间候选上限"
            />
          </div>
          <div>
            <label>最多展示间接连接链</label
            ><el-input-number
              v-model="limits.paths"
              :min="1"
              :max="20"
              :precision="0"
              controls-position="right"
              aria-label="间接连接链上限"
            />
          </div>
          <p>默认处理预算 1.5 秒；超限会明确标记。按中间人物 ID 排序，不代表推荐顺序。</p>
        </details>
        <p class="path-rule-note">
          每一段分别核实，同期区间可以不同；不推断三人同时共事。同校不推断同期，职位不作为连接节点。
        </p>
      </section>
    </details>
    <el-alert
      v-if="suggestionError || entityError"
      :title="suggestionError || entityError"
      type="error"
      :closable="false"
    />
    <div v-if="error" class="comparison-error">
      <el-alert :title="error" type="error" :closable="false" /><el-button @click="search"
        >重试路径查询</el-button
      >
    </div>
    <p v-if="cancelled" class="path-status" role="status">
      搜索已取消，可重新搜索；未据此判断两人的关系。
    </p>
    <section v-if="loading" class="panel comparison-loading">
      <el-skeleton :rows="8" animated />
    </section>
    <template v-else-if="result">
      <div
        class="path-result-status"
        :class="{ limited: result.truncated }"
        role="status"
        data-testid="path-status"
      >
        <strong>{{ result.message }}</strong>
        <el-button v-if="result.truncated" @click="adjustRange">调整搜索范围</el-button>
        <details class="source-details">
          <summary>查询范围与来源</summary>
          <small v-if="result.scope.require_same_school">同专业 · 每段要求同校</small>
          <small data-testid="path-query-backend">{{
            result.query_backend === 'nebula'
              ? '图内路径计算 · SQL 来源证据'
              : result.query_backend === 'nebula_sql'
                ? '图辅助查询 · 经历证据已核对'
                : 'SQL 查询与经历证据核对'
          }}</small>
          <span
            >{{ result.reference.name }}（{{ result.reference.id }}） →
            {{ result.candidate.name }}（{{ result.candidate.id }}）</span
          >
          <small
            >{{ result.query_backend === 'nebula' ? '图内候选范围' : '已核查' }}
            {{
              result.query_backend === 'nebula'
                ? result.stats.graph_candidates
                : result.stats.candidates_examined
            }}
            位中间候选 · {{ result.paths.length }} 条间接连接链 · {{ result.data_version }}</small
          >
        </details>
        <small v-for="reason in pathLimitLabels(result)" :key="reason">{{ reason }}</small>
      </div>
      <div
        v-if="!result.direct && !result.paths.length"
        class="empty-state panel"
        data-testid="path-empty"
      >
        <strong>{{
          result.status === 'limited' ? '搜索范围受限' : '所选范围内未发现连接链'
        }}</strong>
        <span
          >{{
            result.direct_checked ? '直接关系已按所选规则核对。' : '直接关系尚未完成核对。'
          }}可以调整规则或搜索范围后重试。</span
        >
      </div>
      <div v-else class="path-grid">
        <section class="panel path-list" aria-label="连接链列表">
          <div class="panel-header"><h2>已核实连接链</h2></div>
          <button
            v-if="result.direct"
            class="path-choice"
            :class="{ selected: selectedKey === 'direct' }"
            :aria-pressed="selectedKey === 'direct'"
            @click="selectedKey = 'direct'"
            data-testid="path-direct"
          >
            <span class="proof-label">直接共同经历</span
            ><strong>{{ result.reference.name }} → {{ result.candidate.name }}</strong
            ><small>{{ result.direct.evidence.length }} 条已展示证据</small>
          </button>
          <button
            v-for="path in result.paths"
            :key="path.id"
            class="path-choice"
            :class="{ selected: selectedKey === path.id }"
            :aria-pressed="selectedKey === path.id"
            @click="selectedKey = path.id"
            :data-testid="`path-via-${path.intermediate.id}`"
          >
            <span class="proof-label">经一位中间人物</span
            ><strong
              >{{ result.reference.name }} → {{ path.intermediate.name }} →
              {{ result.candidate.name }}</strong
            ><small
              >{{ path.intermediate.id }} ·
              {{
                path.intermediate.sources
                  .map((source) => (source === 'expert' ? '专家库' : '简历库'))
                  .join(' / ')
              }}</small
            >
          </button>
          <p class="path-list-note">
            {{
              result.paths.length
                ? '每位中间人物只列一条连接链，各段可分别选择证据。'
                : result.search_complete
                  ? '所选规则下未发现经一位中间人物的连接链。'
                  : '搜索受限，尚未发现可展示的间接连接链。'
            }}
          </p>
        </section>
        <section class="panel path-graph-panel" aria-label="当前连接链关系图">
          <div class="panel-header">
            <h2>当前连接链</h2>
            <el-button text :icon="Aim" aria-label="适应路径画布" @click="canvas?.fit()" />
          </div>
          <p class="path-graph-hint">橙色连线对应当前段证据；点击实体或连线可切换段落。</p>
          <GraphCanvas
            ref="canvas"
            :data="graph"
            :selected-id="selectedPerson"
            :data-version="result?.data_version"
            :reference-month="result?.reference_month"
            layout="chain"
            :highlighted-edge-ids="highlight"
            @node-click="selectNode"
            @edge-click="selectEdge"
          />
          <div v-if="person" class="path-participant">
            <strong>{{ person.name }}</strong
            ><code>{{ person.id }}</code
            ><span>{{ person.headline }}</span>
          </div>
          <div class="path-segment-tabs" aria-label="选择连接段落">
            <button
              v-for="(segment, index) in segments"
              :key="segment.id"
              :class="{ active: segmentIndex === index }"
              :aria-pressed="segmentIndex === index"
              @click="segmentIndex = index"
              :data-testid="`path-segment-${index}`"
            >
              第 {{ index + 1 }} 段 · {{ segment.from_person.name }} → {{ segment.to_person.name }}
            </button>
          </div>
        </section>
        <section
          v-if="currentSegment && currentProof"
          class="panel path-evidence"
          aria-label="连接段来源证据"
        >
          <div class="panel-header">
            <h2>第 {{ segmentIndex + 1 }} 段 · 经历证据</h2>
            <el-button
              size="small"
              @click="emit('compare', currentSegment.from_person.id, currentSegment.to_person.id)"
              >对比本段履历</el-button
            >
          </div>
          <div class="path-evidence-body">
            <label
              >本段证据
              <span v-if="currentSegment.evidence_truncated"
                >（仅展示前 {{ currentSegment.evidence.length }} 条）</span
              ></label
            >
            <el-select
              :model-value="currentProof.id"
              aria-label="本段经历证据"
              @update:model-value="selectProof"
              data-testid="path-proof-select"
            >
              <el-option
                v-for="proof in currentSegment.evidence"
                :key="proof.id"
                :value="proof.id"
                :label="`${proof.entity.name} · ${proof.label} · ${proof.reference.fact.id} / ${proof.candidate.fact.id}`"
              />
            </el-select>
            <article data-testid="path-proof-detail">
              <h3>{{ currentProof.entity.name }} · {{ currentProof.label }}</h3>
              <p>{{ currentProof.explanation }}</p>
              <p v-if="currentProof.overlap_months" class="overlap-chip">
                {{ monthLabel(currentProof.overlap_start) }} —
                {{ monthLabel(currentProof.overlap_end) }} · {{ currentProof.overlap_months }} 个月
              </p>
              <code>标准实体 {{ currentProof.entity.id }}</code>
              <div class="comparison-fact-pair">
                <div
                  v-for="(view, index) in [currentProof.reference, currentProof.candidate]"
                  :key="view.fact.id"
                >
                  <strong>{{
                    index === 0 ? currentSegment.from_person.name : currentSegment.to_person.name
                  }}</strong
                  ><span>{{ factLabel(view) }}</span>
                  <span
                    >{{ monthLabel(view.fact.start_month) }} —
                    {{
                      view.fact.is_current
                        ? `当前任职（截至 ${monthLabel(result.reference_month)}）`
                        : monthLabel(view.fact.end_month)
                    }}</span
                  >
                  <small>{{ view.fact.source_system === 'expert' ? '专家库' : '简历库' }}</small
                  ><code>{{ view.fact.id }}</code
                  ><code>{{ view.fact.source_record_id }}</code>
                </div>
              </div>
            </article>
            <p class="path-rule-note">证据仅支持本段共同经历；整条连接链不证明实际认识或可引荐。</p>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
