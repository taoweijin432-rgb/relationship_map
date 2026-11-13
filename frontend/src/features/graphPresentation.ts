import type { EvidenceResponse, GraphData } from '../api/client'

type Point = { x: number; y: number }

// 只选用接口返回的证据，避免共享实体在画布上形成未经业务规则核验的捷径。
export function connectionEdgeIds(proof: EvidenceResponse | null, selectedEdgeId: string) {
  const groups = proof?.connection?.segments.map((segment) => segment.evidence) ?? [
    proof?.items ?? [],
  ]
  return groups.flatMap((items) => {
    const selected =
      items.find((item) =>
        [item.reference.fact.id, item.candidate.fact.id].some(
          (id) => `edge:${id}` === selectedEdgeId,
        ),
      ) ?? items[0]
    return selected
      ? [`edge:${selected.reference.fact.id}`, `edge:${selected.candidate.fact.id}`]
      : []
  })
}

export function graphPositions(
  data: GraphData,
  width: number,
  height: number,
  layout: 'radial' | 'chain',
  personPaths: string[][] = [],
): Map<string, Point> {
  if (layout === 'chain')
    return new Map(
      data.nodes.map((node, index) => [node.id, { x: 60 + index * 180, y: height / 2 }]),
    )

  const nodes = new Map(data.nodes.map((node) => [node.id, node]))
  const neighbors = new Map(data.nodes.map((node) => [node.id, new Set<string>()]))
  for (const edge of data.edges) {
    if (!nodes.has(edge.source) || !nodes.has(edge.target)) continue
    neighbors.get(edge.source)?.add(edge.target)
    neighbors.get(edge.target)?.add(edge.source)
  }
  const personDepth = new Map<string, number>()
  for (const path of personPaths)
    path.forEach((id, index) =>
      personDepth.set(id, Math.min(personDepth.get(id) ?? Infinity, index * 2)),
    )

  const remaining = new Set(nodes.keys())
  const components: { positions: Map<string, Point>; radius: number }[] = []
  const seeds = [...data.nodes].sort((a, b) => Number(b.is_reference) - Number(a.is_reference))
  for (const seed of seeds) {
    if (!remaining.has(seed.id)) continue
    const queue = [seed.id]
    const depth = new Map([[seed.id, 0]])
    remaining.delete(seed.id)
    for (const id of queue) {
      for (const neighbor of [...(neighbors.get(id) ?? [])].sort()) {
        if (!remaining.delete(neighbor)) continue
        depth.set(neighbor, (depth.get(id) ?? 0) + 1)
        queue.push(neighbor)
      }
    }
    // 人物层级采用已返回的连接摘要，展开后的新人物以画布最短距离补充。
    if (seed.is_reference) {
      for (const id of queue) {
        if (personDepth.has(id)) depth.set(id, personDepth.get(id) ?? 0)
      }
      for (const id of queue) {
        if (nodes.get(id)?.type === 'person') continue
        const levels = [...(neighbors.get(id) ?? [])].map((neighbor) => depth.get(neighbor) ?? 0)
        depth.set(id, Math.min(...levels) + 1)
      }
    }
    const layers = new Map<number, string[]>()
    for (const id of queue) {
      const level = depth.get(id) ?? 0
      const layer = layers.get(level) ?? []
      layer.push(id)
      layers.set(level, layer)
    }
    const positions = new Map<string, Point>()
    let radius = 0
    for (const [level, layer] of [...layers].sort(([a], [b]) => a - b)) {
      // 同层按遍历分支连续排列，弧长和层间距同时为多行标签留出空间。
      radius = level === 0 ? 0 : Math.max(radius + 150, (layer.length * 120) / (2 * Math.PI))
      layer.forEach((id, index) => {
        const angle = (index / layer.length) * Math.PI * 2 - Math.PI / 2
        positions.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius })
      })
    }
    components.push({ positions, radius })
  }

  const positions = new Map<string, Point>()
  const columns = Math.max(
    1,
    Math.min(components.length, Math.ceil(Math.sqrt((components.length * width) / height))),
  )
  const cell = Math.max(140, ...components.map((component) => component.radius * 2 + 140))
  const rows = Math.ceil(components.length / columns)
  for (const [index, component] of components.entries()) {
    const centerX = ((index % columns) + 0.5) * (cell + 80) + (width - columns * (cell + 80)) / 2
    const centerY =
      (Math.floor(index / columns) + 0.5) * (cell + 80) + (height - rows * (cell + 80)) / 2
    for (const [id, point] of component.positions)
      positions.set(id, { x: centerX + point.x, y: centerY + point.y })
  }
  return positions
}
