<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Connection,
  Search,
  User,
  OfficeBuilding,
  Aim,
  Plus,
  Minus,
  FullScreen,
} from '@element-plus/icons-vue'
import PersonList from './components/PersonList.vue'
import EvidencePanel from './components/EvidencePanel.vue'
import SavedQueries from './components/SavedQueries.vue'
import EntityTopicCard from './components/EntityTopicCard.vue'
import QueryFilters from './components/QueryFilters.vue'
import { useWorkbench } from './features/useWorkbench'
import { usePageExport } from './features/usePageExport'
import { queryConditions } from './features/queryConditions'
import { connectionEdgeIds } from './features/graphPresentation'
import type { QueryMode, QuerySnapshot } from './features/queryState'
import { dataModeLabel, type GraphNode } from './api/client'

const workbench = useWorkbench()
const {
  mode,
  topic,
  appliedSnapshot,
  options,
  meta,
  hasMaterializedRelations,
  results,
  graph,
  loading,
  error,
  selectedId,
  selectedEntity,
  detail,
  evidence,
  detailError,
  detailLoading,
  expanding,
  graphMessage,
  highlightedEntityId,
  selectedEdgeId,
  pageIndex,
  reference,
  runQuery,
  initialize,
  restoreQuery,
  openTopic,
  selectPerson,
  selectNode,
  selectEdge,
  retryDetail,
  setCenter,
  searchEntity,
  changePage,
  expandSelected,
  dirty,
  actionsDisabled,
  removeCondition,
} = workbench
const GraphCanvas = defineAsyncComponent(() => import('./components/GraphCanvas.vue'))
const ComparisonWorkspace = defineAsyncComponent(
  () => import('./components/ComparisonWorkspace.vue'),
)
const PathWorkspace = defineAsyncComponent(() => import('./components/PathWorkspace.vue'))
const view = ref<'explore' | 'compare'>('explore')
const resultView = ref('people')
const pairTab = ref('evidence')
const comparisonPair = ref({ referenceId: '', candidateId: '' })
const pathPair = ref({ referenceId: '', candidateId: '' })
const canvas = ref<{
  fit: () => void
  zoom: (factor: number) => void
  exportImage: () => Promise<string>
}>()
const graphPanel = ref<HTMLElement>()
const fullscreenError = ref('')
const savedOpen = ref(false)
const restoreMessage = ref('')
const narrow = ref(false)
const drawerOpen = ref(false)
const media = window.matchMedia('(max-width: 800px)')
function resize() {
  narrow.value = media.matches
}
onMounted(() => {
  resize()
  media.addEventListener('change', resize)
})
onBeforeUnmount(() => media.removeEventListener('change', resize))
const {
  busy: exportBusy,
  message: exportMessage,
  exportFile,
} = usePageExport(
  results,
  appliedSnapshot,
  graph,
  async () => {
    if (!canvas.value) throw new Error('请先打开关系图')
    return canvas.value.exportImage()
  },
  actionsDisabled,
)
const conditions = computed(() =>
  queryConditions(results.value?.applied_filters, [
    ...options.organization,
    ...options.school,
    ...options.major,
    ...options.role,
  ]),
)
const contextName = computed(() => reference.value?.name ?? topic.value?.name ?? '按条件找到的人物')
const title = computed(() =>
  mode.value === 'person' ? '找关联的人' : mode.value === 'topic' ? '实体专题' : '按条件找人',
)
const selectedPerson = computed(
  () =>
    detail.value?.person ??
    results.value?.items.find((item) => item.person.id === selectedId.value)?.person,
)
const graphPersonPaths = computed(() =>
  (results.value?.items ?? []).flatMap((item) =>
    item.connection ? [item.connection.person_ids] : [],
  ),
)
const focusedGraphEdges = computed(() => connectionEdgeIds(evidence.value, selectedEdgeId.value))
const evidenceProps = computed(() => ({
  dataMode: meta.value?.data_mode,
  canCompare: !!reference.value && detail.value?.person.id !== reference.value.id,
  detail: detail.value,
  evidence: evidence.value,
  loading: detailLoading.value,
  error: detailError.value,
  entity: selectedEntity.value,
  highlightedEntityId: highlightedEntityId.value,
  selectedEdge: graph.value.edges.find((edge) => edge.id === selectedEdgeId.value) ?? null,
}))
function focusFilters() {
  const input = document.querySelector<HTMLInputElement>('.query-form input')
  input?.focus()
  input?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}
function choosePerson(id: string) {
  void selectPerson(id)
  drawerOpen.value = narrow.value
}
function chooseNode(id: string) {
  selectNode(id)
  drawerOpen.value = narrow.value
}
function chooseEdge(id: string) {
  selectEdge(id)
  drawerOpen.value = narrow.value
}
watch(results, () => {
  drawerOpen.value = false
})
function navigate(next: QueryMode) {
  view.value = 'explore'
  mode.value = next
  resultView.value = 'people'
  drawerOpen.value = false
}
function openComparison() {
  comparisonPair.value = { referenceId: reference.value?.id ?? '', candidateId: selectedId.value }
  if (comparisonPair.value.referenceId === comparisonPair.value.candidateId)
    comparisonPair.value.candidateId = ''
  pairTab.value = 'evidence'
  drawerOpen.value = false
  view.value = 'compare'
}
function openPaths(left: string, right: string) {
  pathPair.value = { referenceId: left, candidateId: right }
  pairTab.value = 'paths'
}
function comparePathSegment(left: string, right: string) {
  comparisonPair.value = { referenceId: left, candidateId: right }
  pairTab.value = 'evidence'
}
function showEntityTopic(node: GraphNode) {
  resultView.value = 'people'
  view.value = 'explore'
  drawerOpen.value = false
  void openTopic(node)
}
async function restoreSaved(query: QuerySnapshot) {
  view.value = 'explore'
  drawerOpen.value = false
  await restoreQuery(query)
  restoreMessage.value =
    query.dataVersion !== results.value?.data_version
      ? '数据版本已变化，已重新查询第一页。'
      : '已恢复条件并重新查询第一页。'
}
async function fullscreen() {
  fullscreenError.value = ''
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await graphPanel.value?.requestFullscreen()
  } catch {
    fullscreenError.value = '当前浏览器无法全屏，可使用放大和适应画布。'
  }
}
function exitFullscreen() {
  if (document.fullscreenElement === graphPanel.value) void fullscreen()
}
function resultCommand(command: string) {
  if (command === 'saved') savedOpen.value = true
  else if (command === 'json' || command === 'csv') void exportFile(command)
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <a class="workspace-brand" href="#" @click.prevent="navigate('person')"
        ><el-icon :size="24"><Connection /></el-icon><strong>经纬</strong
        ><span>人物关系工作台</span></a
      >
      <nav class="task-navigation" aria-label="工作空间导航">
        <button
          :class="{ active: view === 'explore' && mode === 'person' }"
          :aria-current="view === 'explore' && mode === 'person' ? 'page' : undefined"
          @click="navigate('person')"
        >
          <el-icon><User /></el-icon>找关联的人
        </button>
        <button
          :class="{ active: view === 'explore' && mode !== 'person' }"
          :aria-current="view === 'explore' && mode !== 'person' ? 'page' : undefined"
          @click="navigate('entity')"
        >
          <el-icon><OfficeBuilding /></el-icon>按条件找人
        </button>
        <button
          :class="{ active: view === 'compare' }"
          :aria-current="view === 'compare' ? 'page' : undefined"
          @click="openComparison"
        >
          <el-icon><Connection /></el-icon>查两人关系
        </button>
      </nav>
      <span class="environment-badge"
        >{{ meta ? dataModeLabel(meta.data_mode) : '正在读取数据源' }} · 本地验证</span
      >
    </header>
    <main class="main-workspace">
      <template v-if="view === 'explore'">
        <div class="workspace-heading">
          <h1>{{ title }}</h1>
          <el-button @click="savedOpen = true">常用条件</el-button>
        </div>
        <QueryFilters :workbench="workbench" />
        <div v-if="error" class="query-error">
          <el-alert :title="error" type="error" :closable="false" /><el-button
            @click="meta ? runQuery() : initialize()"
            >重新查询</el-button
          >
        </div>
        <p v-if="restoreMessage" role="status" class="saved-message">{{ restoreMessage }}</p>
        <p v-if="results && dirty" class="pending-changes" role="status">
          条件已修改，点击查询更新结果。下方为上次查询结果。
        </p>
        <EntityTopicCard
          v-if="topic"
          :entity="topic"
          :count="results?.items.length ?? null"
          :has-more="results?.has_more ?? false"
        />
        <section v-if="results" class="query-context" aria-label="已生效的查询条件">
          <div>
            <strong>{{ contextName }}</strong
            ><span>{{ conditions.length }} 项条件 · 按人物 ID 排序</span>
            <span v-if="results.reference && (results.applied_filters.max_hops ?? 1) === 1"
              >最多 1 跳</span
            >
          </div>
          <div class="condition-tags">
            <el-tag
              v-for="condition in conditions"
              :key="condition.id"
              :closable="!dirty && appliedSnapshot?.mode !== 'topic'"
              @close="removeCondition(condition.field, condition.value)"
              >{{ condition.label }}</el-tag
            >
          </div>
        </section>
        <div class="result-toolbar">
          <div class="view-switch" role="group" aria-label="结果视图">
            <button
              :aria-pressed="resultView === 'people'"
              :class="{ active: resultView === 'people' }"
              @click="resultView = 'people'"
            >
              人物与经历
            </button>
            <button
              :aria-pressed="resultView === 'graph'"
              :class="{ active: resultView === 'graph' }"
              @click="resultView = 'graph'"
            >
              关系图
            </button>
          </div>
          <el-dropdown @command="resultCommand">
            <el-button aria-label="更多结果操作">更多 ▾</el-button>
            <template #dropdown
              ><el-dropdown-menu>
                <el-dropdown-item command="saved">保存／恢复条件</el-dropdown-item>
                <el-dropdown-item command="json" :disabled="actionsDisabled || exportBusy"
                  >导出当前页 JSON</el-dropdown-item
                >
                <el-dropdown-item command="csv" :disabled="actionsDisabled || exportBusy"
                  >导出当前页 CSV</el-dropdown-item
                >
              </el-dropdown-menu></template
            >
          </el-dropdown>
        </div>
        <p
          v-if="exportMessage"
          class="export-message"
          :role="exportMessage.startsWith('导出失败') ? 'alert' : 'status'"
        >
          {{ exportMessage }}
        </p>
        <div v-if="!results && !loading" class="welcome-state panel">
          <el-icon :size="36"><Search /></el-icon>
          <h2>{{ mode === 'person' ? '先选择你想查的人' : '选择条件，找到目标人物' }}</h2>
          <p>
            {{
              mode === 'person'
                ? '搜索姓名或业务编号，再点击「查关联人物」'
                : '公司、学校、职位可组合选择'
            }}
          </p>
        </div>
        <div v-else class="workbench-grid" :class="{ 'graph-view': resultView === 'graph' }">
          <PersonList
            v-if="resultView === 'people'"
            :result="results"
            :selected-id="selectedId"
            :loading="loading"
            :disabled="actionsDisabled"
            :page-index="pageIndex"
            @select="choosePerson"
            @adjust="focusFilters"
            @page="changePage"
          />
          <section
            v-else
            ref="graphPanel"
            class="graph-panel panel"
            aria-label="人物关系图"
            @keydown.esc="exitFullscreen"
          >
            <div class="panel-header">
              <h2>
                关系图
                <span class="graph-count"
                  >{{ graph.nodes.length }} 节点 · {{ graph.edges.length }} 关联</span
                >
              </h2>
            </div>
            <div class="graph-tools">
              <el-button :icon="Plus" aria-label="放大关系图" @click="canvas?.zoom(1.25)" />
              <el-button :icon="Minus" aria-label="缩小关系图" @click="canvas?.zoom(0.8)" />
              <el-button :icon="Aim" aria-label="适应画布" @click="canvas?.fit()" />
              <el-button :icon="FullScreen" aria-label="全屏关系图" @click="fullscreen" />
              <el-button
                :disabled="actionsDisabled || expanding || exportBusy"
                @click="exportFile('png')"
                >导出图 PNG</el-button
              >
            </div>
            <div class="graph-legend">
              <span><i class="legend-person" />人物</span
              ><span><i class="legend-company" />公司</span
              ><span><i class="legend-school" />学校</span
              ><span v-if="hasMaterializedRelations"><i class="legend-major" />专业</span>
            </div>
            <GraphCanvas
              ref="canvas"
              :data="graph"
              :selected-id="selectedId"
              :data-version="results?.data_version"
              :reference-month="results?.reference_month"
              :highlighted-edge-ids="selectedEdgeId ? [selectedEdgeId] : []"
              :focus-edge-ids="focusedGraphEdges"
              :person-paths="graphPersonPaths"
              @node-click="chooseNode"
              @edge-click="chooseEdge"
            />
            <div class="graph-actions" v-if="selectedId">
              <el-button :disabled="actionsDisabled" :loading="expanding" @click="expandSelected"
                >展开关联人物</el-button
              >
              <el-button
                v-if="selectedPerson"
                :disabled="actionsDisabled"
                @click="setCenter(selectedPerson)"
                >以此人为中心查询</el-button
              >
            </div>
            <p
              v-if="graphMessage || graph.truncation_reason || fullscreenError"
              class="graph-message"
              role="status"
            >
              {{ graphMessage || graph.truncation_reason || fullscreenError }}
            </p>
            <p class="graph-bottom">局部关系图 · 完整候选请在人物列表中翻页</p>
          </section>
          <EvidencePanel
            v-if="!narrow"
            v-bind="evidenceProps"
            @compare="openComparison"
            @center="setCenter"
            @entity-search="searchEntity"
            @entity-topic="showEntityTopic"
            @retry="retryDetail"
          />
          <el-button
            v-else-if="selectedId || selectedEntity"
            class="mobile-detail-button"
            @click="drawerOpen = true"
            >查看选中人物与经历</el-button
          >
        </div>
        <el-drawer
          v-if="narrow"
          v-model="drawerOpen"
          title="人物与经历"
          size="100%"
          direction="rtl"
          destroy-on-close
        >
          <EvidencePanel
            v-bind="evidenceProps"
            @compare="openComparison"
            @center="
              (person) => {
                drawerOpen = false
                setCenter(person)
              }
            "
            @entity-search="
              (node) => {
                drawerOpen = false
                searchEntity(node)
              }
            "
            @entity-topic="showEntityTopic"
            @retry="retryDetail"
          />
        </el-drawer>
      </template>
      <template v-else>
        <div class="workspace-heading">
          <h1>查两人关系</h1>
          <el-button @click="view = 'explore'">返回找人</el-button>
        </div>
        <ComparisonWorkspace
          v-show="pairTab !== 'paths'"
          :key="`${comparisonPair.referenceId}|${comparisonPair.candidateId}`"
          :reference-id="comparisonPair.referenceId"
          :candidate-id="comparisonPair.candidateId"
          @paths="openPaths"
          @topic="showEntityTopic"
        />
        <template v-if="pairTab === 'paths'">
          <div class="pair-tabs">
            <el-button @click="pairTab = 'evidence'">共同经历</el-button><strong>经过谁连接</strong>
          </div>
          <PathWorkspace
            :key="`${pathPair.referenceId}|${pathPair.candidateId}`"
            :allow-major="hasMaterializedRelations"
            :reference-id="pathPair.referenceId"
            :candidate-id="pathPair.candidateId"
            @compare="comparePathSegment"
          />
        </template>
      </template>
      <footer class="workspace-footer">
        <span>共同经历不代表实际认识 · 同校不推断同期</span>
        <details>
          <summary>数据与版本</summary>
          <p>
            {{ meta?.person_count ?? '—' }} 名有效人物 ·
            {{ meta?.fact_count ?? '—' }} 条有效经历事实
          </p>
          <p>
            {{ meta?.data_version }} ·
            {{
              meta?.storage === 'sqlite-numeric-source'
                ? 'SQL 快照 · 图内人物关系'
                : meta?.storage === 'mysql-uuid-source'
                  ? 'MySQL 来源 · 图内人物关系'
                  : '本地原型'
            }}
            · 基准 {{ meta?.reference_month }}
          </p>
        </details>
        <el-button v-if="view === 'explore' && results" text @click="runQuery()"
          >刷新查询</el-button
        >
      </footer>
    </main>
    <el-dialog v-model="savedOpen" title="常用条件" width="min(520px, 94vw)">
      <SavedQueries :snapshot="actionsDisabled ? null : appliedSnapshot" :restore="restoreSaved" />
    </el-dialog>
  </div>
</template>
