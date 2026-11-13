import {
  dataModeLabel,
  factLabel,
  type ExportResponse,
  type FactView,
  type GraphData,
} from '../api/client'
import type { QuerySnapshot } from './queryState'

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function csvCell(value: unknown) {
  let text = value == null ? '' : String(value)
  if (/^[\s\u0000-\u001f]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

function factColumns(view?: FactView) {
  return view
    ? [
        view.fact.id,
        view.entity.name,
        factLabel(view),
        view.fact.start_month,
        view.fact.end_month,
        view.fact.is_current ? '是' : '否',
        view.fact.source_system,
        view.fact.source_record_id,
      ]
    : Array(8).fill('')
}

export function pageCsv(data: ExportResponse): string {
  const headers = [
    '数据模式',
    '数据版本',
    '基准月份',
    '导出范围',
    '后续仍有结果',
    '查询条件',
    '参考人物ID',
    '人物ID',
    '姓名',
    '来源',
    '记录类型',
    '关系',
    '证据ID',
    '交集开始月',
    '交集结束月',
    '交集月数',
    '说明',
    ...['参考方', '候选方'].flatMap((side) =>
      ['经历ID', '实体', '职位', '开始月', '结束月', '当前任职', '来源系统', '来源记录'].map(
        (field) => `${side}${field}`,
      ),
    ),
  ]
  const rows: unknown[][] = [headers]
  rows.push([
    dataModeLabel(data.data_mode),
    data.data_version,
    data.reference_month,
    '仅当前页',
    data.has_more ? '是' : '否',
    JSON.stringify(data.filters),
    data.reference?.id,
    '',
    '',
    '',
    '导出元数据',
    '',
    '',
    '',
    '',
    '',
    '',
    ...factColumns(),
    ...factColumns(),
  ])
  for (const item of data.items) {
    const base = [
      dataModeLabel(data.data_mode),
      data.data_version,
      data.reference_month,
      '仅当前页',
      data.has_more ? '是' : '否',
      JSON.stringify(data.filters),
      data.reference?.id,
      item.person.id,
      item.person.name,
      item.person.sources.join('|'),
    ]
    for (const proof of item.evidence)
      rows.push([
        ...base,
        '筛选内共同经历证据',
        proof.label,
        proof.id,
        proof.overlap_start,
        proof.overlap_end,
        proof.overlap_months,
        proof.explanation,
        ...factColumns(proof.reference),
        ...factColumns(proof.candidate),
      ])
    // 完整有效履历单独标明，不能把它误读为每条均命中筛选或构成人物关系。
    for (const fact of item.facts)
      rows.push([
        ...base,
        '人物全部有效履历',
        '',
        '',
        '',
        '',
        '',
        '此履历不一定命中筛选条件',
        ...factColumns(),
        ...factColumns(fact),
      ])
    if (!item.facts.length && !item.evidence.length)
      rows.push([...base, '人物摘要', '', '', '', '', '', '', ...factColumns(), ...factColumns()])
    if (item.connection_detail && item.connection_detail.hop_count > 1) {
      item.connection_detail.segments.forEach((segment, index) => {
        for (const proof of segment.evidence)
          rows.push([
            ...base,
            '连接链分段证据',
            proof.label,
            proof.id,
            proof.overlap_start,
            proof.overlap_end,
            proof.overlap_months,
            proof.explanation,
            ...factColumns(proof.reference),
            ...factColumns(proof.candidate),
            item.connection_detail?.hop_count,
            item.connection_detail?.person_ids.join(' → '),
            index + 1,
            segment.from_person.id,
            segment.to_person.id,
          ])
      })
    }
  }
  const columnCount = headers.length
  headers.push('关联跳数', '连接人物序列', '段序号', '段起点人物ID', '段终点人物ID')
  const complete = rows.map((row, index) => {
    if (index === 0 || row.length > columnCount) return row
    const item = data.items.find((item) => item.person.id === row[7])
    return [
      ...row,
      item ? (item.connection?.hop_count ?? (data.reference ? 1 : '')) : '',
      item?.connection?.person_ids.join(' → ') ?? '',
      '',
      '',
      '',
    ]
  })
  return '\uFEFF' + complete.map((row) => row.map(csvCell).join(',')).join('\r\n')
}

export async function graphImage(
  url: string,
  query: QuerySnapshot,
  graph: GraphData,
  dataMode: ExportResponse['data_mode'] = 'mock',
): Promise<Blob> {
  const image = new Image()
  image.src = url
  await image.decode()
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(image.naturalWidth, 900)
  canvas.height = image.naturalHeight + 130
  const context = canvas.getContext('2d')
  if (!context) throw new Error('浏览器无法生成图图片')
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.fillStyle = '#23594d'
  context.font = '18px sans-serif'
  context.fillText(`经纬 · ${dataModeLabel(dataMode)} · 局部关系图`, 24, 30)
  context.font = '12px sans-serif'
  context.fillText(
    `版本 ${query.dataVersion} | ${graph.nodes.length} 节点 / ${graph.edges.length} 关联 | ${graph.truncated ? '范围已截断' : '有界局部展示'}（可含手动展开）`,
    24,
    54,
  )
  const criteria = `${query.mode === 'person' ? `参考人物 ${query.referenceId}` : query.mode === 'topic' ? `实体专题 ${query.topicId}` : '背景筛选'} | ${JSON.stringify(query.filters)}`
  context.fillText(
    criteria.length > 110 ? criteria.slice(0, 110) + '…（完整条件见结果文件）' : criteria,
    24,
    77,
  )
  context.fillText('共同经历不证明实际认识。图片不是完整候选列表；完整候选请在列表翻页。', 24, 100)
  context.drawImage(image, (canvas.width - image.naturalWidth) / 2, 130)
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('图图片生成失败'))),
      'image/png',
    ),
  )
}
