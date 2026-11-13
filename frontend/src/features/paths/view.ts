import {
  factRelationLabel,
  type GraphData,
  type PathResponse,
  type PathSegment,
} from '../../api/client'

const REASONS: Record<PathResponse['truncation_reasons'][number], string> = {
  candidate_limit: '中间候选数量达到上限',
  path_limit: '连接链展示数量达到上限',
  fact_limit: '经历读取预算已用尽',
  pair_limit: '经历核对预算已用尽',
  evidence_limit: '部分段落只展示限定数量的证据',
  time_limit: '处理时间预算已用尽',
  sql_limit: '查询执行预算已用尽',
  graph_limit: '图候选读取预算已用尽',
}
export function pathLimitLabels(result: PathResponse): string[] {
  return result.truncation_reasons.map((reason) => REASONS[reason])
}

// 只把后端证据转换为图，实体按段落显示，重复标准实体仍保持可追溯标识。
export function selectedPathGraph(
  segments: PathSegment[],
  selected: Record<string, string>,
): GraphData {
  const nodes: GraphData['nodes'] = []
  const edges: GraphData['edges'] = []
  segments.forEach((segment, index) => {
    const proof =
      segment.evidence.find((item) => item.id === selected[segment.id]) ?? segment.evidence[0]
    if (!proof) return
    if (!index)
      nodes.push({
        id: segment.from_person.id,
        type: 'person',
        label: segment.from_person.name,
        is_reference: true,
      })
    const entityId = `path-entity:${index}:${proof.entity.id}`
    nodes.push(
      {
        id: entityId,
        type:
          proof.entity.type === 'major'
            ? 'major'
            : proof.entity.type === 'organization'
              ? 'organization'
              : 'school',
        label: proof.entity.name,
        is_reference: false,
      },
      {
        id: segment.to_person.id,
        type: 'person',
        label: segment.to_person.name,
        is_reference: false,
      },
    )
    edges.push(
      {
        id: `leg:${index}:left`,
        source: segment.from_person.id,
        target: entityId,
        label: factRelationLabel(proof.reference.fact.type),
        fact_id: proof.reference.fact.id,
      },
      {
        id: `leg:${index}:right`,
        source: entityId,
        target: segment.to_person.id,
        label: factRelationLabel(proof.candidate.fact.type),
        fact_id: proof.candidate.fact.id,
      },
    )
  })
  return { nodes, edges, truncated: false, truncation_reason: null }
}
