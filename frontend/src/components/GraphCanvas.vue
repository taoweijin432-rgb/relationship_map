<script setup lang="ts">
import {
  Graph,
  GraphEvent,
  NodeEvent,
  EdgeEvent,
  type EdgeData,
  type IElementEvent,
} from '@antv/g6'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  factLabel,
  factPeriod,
  type GraphData,
  type GraphEdge,
  type GraphNode,
} from '../api/client'
import { useGraphEdgePreview } from '../features/useGraphEdgePreview'
import { graphPositions } from '../features/graphPresentation'

const props = withDefaults(
  defineProps<{
    data: GraphData
    selectedId: string
    layout?: 'radial' | 'chain'
    highlightedEdgeIds?: string[]
    focusEdgeIds?: string[]
    personPaths?: string[][]
    dataVersion?: string
    referenceMonth?: number
  }>(),
  { layout: 'radial', highlightedEdgeIds: () => [], focusEdgeIds: () => [], personPaths: () => [] },
)
const emit = defineEmits<{ nodeClick: [id: string]; edgeClick: [id: string] }>()
const host = ref<HTMLDivElement>()
const graph = shallowRef<Graph>()
const error = ref('')
const renderingBusy = ref(false)
const showLabels = ref(false)
const focusEnabled = ref(false)
const hoveredNodeId = ref('')
const zoomedOut = ref(false)
const tooltipPosition = ref({ left: 8, top: 8 })
const preview = useGraphEdgePreview(
  () => props.data,
  () => props.dataVersion,
  () => props.referenceMonth,
)
const hoveredEdge = computed(() =>
  props.data.edges.find((edge) => edge.id === preview.hoveredId.value),
)
const nodeLabel = (id: string) => props.data.nodes.find((node) => node.id === id)?.label ?? id
const focusedEdges = computed(() => {
  if (!focusEnabled.value || props.layout === 'chain') return new Set<string>()
  const requested = new Set([...props.focusEdgeIds, ...props.highlightedEdgeIds])
  return new Set(props.data.edges.filter((edge) => requested.has(edge.id)).map((edge) => edge.id))
})
const focusedNodes = computed(
  () =>
    new Set([
      props.selectedId,
      ...props.data.edges
        .filter((edge) => focusedEdges.value.has(edge.id))
        .flatMap((edge) => [edge.source, edge.target]),
    ]),
)
let observer: ResizeObserver | undefined
let revision = 0
let rendering = Promise.resolve()
let touchClick: ReturnType<typeof setTimeout> | undefined
let labelZoom = 1
let viewportReady = false

function nodeStyle(node: GraphNode) {
  const zoom = labelZoom
  const inFocus = focusedEdges.value.size > 0 && focusedNodes.value.has(node.id)
  const active =
    node.is_reference ||
    node.id === props.selectedId ||
    hoveredNodeId.value === node.id ||
    (focusedEdges.value.size > 0 && focusedNodes.value.has(node.id))
  return {
    size: Math.max(
      node.is_reference ? 52 : node.type === 'person' ? 34 : 28,
      (node.is_reference ? 26 : active ? 18 : node.type === 'person' ? 8 : 6) / zoom,
    ),
    lineWidth: (node.id === props.selectedId ? 3 : 1) / zoom,
    label: hoveredNodeId.value === node.id || (node.type === 'person' && (active || zoom >= 0.3)),
    labelFontSize: 12 / zoom,
    labelPlacement: inFocus ? ('right' as const) : ('bottom' as const),
    labelWordWrapWidth: 80 / zoom,
    labelMaxLines: hoveredNodeId.value === node.id ? 3 : 1,
    labelOffsetX: inFocus ? 6 / zoom : 0,
    labelOffsetY: inFocus ? 0 : 5 / zoom,
  }
}

function dispatchClick(event: IElementEvent, action: () => void) {
  preview.hide()
  if (event.pointerType !== 'touch') {
    action()
    return
  }
  // 等兼容鼠标事件结束后再打开抽屉，避免同一次触摸穿透到新遮罩。
  clearTimeout(touchClick)
  touchClick = setTimeout(action, 0)
}

function edgeStyle(edge: GraphEdge): NonNullable<EdgeData['style']> {
  const selected = props.highlightedEdgeIds.includes(edge.id)
  const focused = focusedEdges.value.has(edge.id)
  const hovered = preview.hoveredId.value === edge.id
  const zoom = labelZoom
  return {
    stroke: selected || focused ? '#bc8748' : '#a8bfb7',
    lineWidth: (selected || focused || hovered ? 2.5 : 1) / zoom,
    opacity: focusedEdges.value.size && !focused && !hovered ? 0.12 : 0.85,
    cursor: 'pointer',
    increasedLineWidthForHitTesting: 8,
    label: showLabels.value || selected || hovered,
    labelText: edge.label,
    labelFill: selected ? '#88591f' : '#4c665b',
    labelFontSize: 11 / zoom,
    labelAutoRotate: false,
    labelBackground: true,
    labelBackgroundFill: '#ffffff',
    labelPadding: [2 / zoom, 5 / zoom],
  }
}

function renderFailed() {
  error.value = '关系图暂时无法绘制，人物列表和证据仍可使用。'
}

function updateStyles() {
  rendering = rendering
    .then(async () => {
      const instance = graph.value
      if (!instance || instance.destroyed) return
      instance.updateEdgeData(
        props.data.edges.map((edge) => ({ id: edge.id, style: edgeStyle(edge) })),
      )
      instance.updateNodeData(
        props.data.nodes.map((node) => ({
          id: node.id,
          style: {
            ...nodeStyle(node),
            opacity: focusedEdges.value.size && !focusedNodes.value.has(node.id) ? 0.22 : 1,
          },
        })),
      )
      const state = Object.fromEntries(
        props.data.nodes.map((node) => [node.id, node.id === props.selectedId ? ['selected'] : []]),
      )
      await instance.setElementState(state, false)
      await instance.draw()
    })
    .catch(renderFailed)
}

function previewEdge(event: IElementEvent) {
  const bounds = host.value?.getBoundingClientRect()
  if (!bounds) return
  tooltipPosition.value = {
    left: Math.max(8, Math.min(event.clientX - bounds.left + 12, bounds.width - 288)),
    top: Math.max(8, Math.min(event.clientY - bounds.top + 12, bounds.height - 180)),
  }
  preview.show(event.target.id)
}

function queueRender() {
  const version = ++revision
  renderingBusy.value = true
  rendering = rendering
    .then(async () => {
      const instance = graph.value
      if (!instance || instance.destroyed || version !== revision) return
      const width = host.value?.clientWidth || 500
      const height = host.value?.clientHeight || 520
      const positions = graphPositions(props.data, width, height, props.layout, props.personPaths)
      const nodeData = props.data.nodes.map((node) => {
        const color = node.is_reference
          ? '#17665d'
          : node.type === 'person'
            ? '#e5f1ed'
            : node.type === 'organization'
              ? '#e9e4f5'
              : node.type === 'major'
                ? '#dfeaf8'
                : '#fbefd7'
        return {
          id: node.id,
          data: { label: node.label, kind: node.type },
          style: {
            ...positions.get(node.id),
            opacity: focusedEdges.value.size && !focusedNodes.value.has(node.id) ? 0.22 : 1,
            fill: color,
            stroke: node.is_reference ? '#17665d' : '#fff',
            labelText: node.label,
            labelFill: '#4b5a5c',
            labelWordWrap: true,
            labelTextOverflow: '…',
            ...nodeStyle(node),
          },
        }
      })
      instance.setData({
        nodes: nodeData,
        edges: props.data.edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          style: edgeStyle(edge),
        })),
      })
      await instance.render()
      if (!instance.destroyed) {
        viewportReady = true
        await instance.fitView()
        if (props.selectedId && instance.getNodeData().some((n) => n.id === props.selectedId)) {
          await instance.setElementState(props.selectedId, ['selected'], false)
        }
        error.value = ''
      }
    })
    .catch(renderFailed)
    .finally(() => {
      if (version === revision) renderingBusy.value = false
    })
}

watch([() => props.data, () => props.layout, () => props.personPaths], () => {
  focusEnabled.value = false
  queueRender()
})
watch(
  () => props.selectedId,
  () => {
    focusEnabled.value = true
  },
)
watch(
  [
    () => props.selectedId,
    () => props.highlightedEdgeIds,
    focusedEdges,
    showLabels,
    preview.hoveredId,
    hoveredNodeId,
  ],
  updateStyles,
)

onMounted(() => {
  if (!host.value) return
  graph.value = new Graph({
    container: host.value,
    animation: false,
    padding: 50,
    zoomRange: [0.05, 3],
    node: { type: 'circle', state: { selected: { stroke: '#d48c3d' } } },
    transforms: [{ type: 'process-parallel-edges', mode: 'bundle', distance: 56 }],
    behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
  })
  graph.value.on(NodeEvent.CLICK, (event: IElementEvent) => {
    focusEnabled.value = true
    dispatchClick(event, () => emit('nodeClick', event.target.id))
  })
  graph.value.on(EdgeEvent.CLICK, (event: IElementEvent) => {
    focusEnabled.value = true
    dispatchClick(event, () => emit('edgeClick', event.target.id))
  })
  graph.value.on(EdgeEvent.POINTER_ENTER, previewEdge)
  graph.value.on(EdgeEvent.POINTER_MOVE, previewEdge)
  graph.value.on(EdgeEvent.POINTER_LEAVE, preview.hide)
  graph.value.on(NodeEvent.POINTER_ENTER, (event: IElementEvent) => {
    hoveredNodeId.value = event.target.id
  })
  graph.value.on(NodeEvent.POINTER_LEAVE, () => {
    hoveredNodeId.value = ''
  })
  graph.value.on(GraphEvent.AFTER_TRANSFORM, () => {
    if (!viewportReady || !graph.value || graph.value.destroyed) return
    const zoom = graph.value?.getZoom() || 1
    if (Math.abs(zoom - labelZoom) < 0.001) return
    labelZoom = zoom
    zoomedOut.value = zoom < 0.3
    updateStyles()
  })
  observer = new ResizeObserver(() => {
    preview.hide()
    if (!graph.value?.destroyed) graph.value?.resize()
  })
  observer.observe(host.value)
  queueRender()
})
onBeforeUnmount(() => {
  viewportReady = false
  clearTimeout(touchClick)
  revision++
  observer?.disconnect()
  graph.value?.destroy()
})
async function exportImage() {
  await rendering
  if (!graph.value || graph.value.destroyed || error.value || !props.data.nodes.length)
    throw new Error('关系图尚未准备好')
  await graph.value.fitView()
  await rendering
  return graph.value.toDataURL({ type: 'image/png', mode: 'viewport' })
}
defineExpose({
  fit: () => graph.value?.fitView(),
  zoom: (factor: number) => graph.value?.zoomBy(factor, false),
  exportImage,
})
</script>

<template>
  <div
    class="graph-surface"
    data-testid="graph-canvas"
    :aria-busy="renderingBusy"
    :data-edge-labels="showLabels ? 'visible' : 'on-demand'"
    :data-layout="layout === 'chain' ? 'chain' : 'layered'"
    :data-focused-edges="focusedEdges.size"
    @pointerleave="preview.hide"
  >
    <div ref="host" class="graph-host" />
    <div v-if="data.edges.length" class="graph-label-toggle">
      <span v-if="zoomedOut" class="graph-zoom-hint">放大查看人物姓名</span>
      <el-button v-if="focusedEdges.size" text size="small" @click="focusEnabled = false"
        >查看全部关系</el-button
      >
      <el-checkbox v-model="showLabels">显示全部关系文字</el-checkbox>
    </div>
    <div
      v-if="hoveredEdge && !error"
      class="graph-edge-tooltip"
      role="tooltip"
      :data-edge-id="hoveredEdge.id"
      :style="{ left: `${tooltipPosition.left}px`, top: `${tooltipPosition.top}px` }"
    >
      <strong>{{ nodeLabel(hoveredEdge.source) }} → {{ nodeLabel(hoveredEdge.target) }}</strong>
      <span>{{ hoveredEdge.label }}</span>
      <template v-if="preview.view.value">
        <span>{{ factLabel(preview.view.value) }}</span>
        <span>{{ factPeriod(preview.view.value) }}</span>
      </template>
      <span v-else-if="preview.loading.value">正在读取经历摘要…</span>
      <span v-else-if="preview.error.value" class="graph-edge-error">{{
        preview.error.value
      }}</span>
      <small>点击连线查看具体经历与来源</small>
    </div>
    <div v-if="error" class="graph-fallback" role="alert">{{ error }}</div>
    <div v-if="!data.nodes.length" class="graph-empty">查询后在这里探索人物与共同经历</div>
  </div>
</template>
