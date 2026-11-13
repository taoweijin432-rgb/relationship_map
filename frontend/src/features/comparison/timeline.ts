import type { ComparisonResponse, FactView, Evidence, Person } from '../../api/client'

export interface TimelineRow {
  view: FactView
  person: Person
  start: number
  end: number
  common: boolean
  overlaps: Evidence[]
}

export interface TimelineSide {
  person: Person
  rows: TimelineRow[]
  undated: FactView[]
}

export function monthIndex(month: number): number {
  return Math.floor(month / 100) * 12 + (month % 100) - 1
}

export function indexMonth(index: number): number {
  return Math.floor(index / 12) * 100 + (index % 12) + 1
}

export function timelineSides(result: ComparisonResponse): TimelineSide[] {
  return (
    [
      [result.reference, result.reference_facts],
      [result.candidate, result.candidate_facts],
    ] as [Person, FactView[]][]
  ).map(([person, views]) => {
    const rows: TimelineRow[] = []
    const undated: FactView[] = []
    for (const view of views) {
      const start = view.fact.start_month
      const end = view.fact.is_current ? result.reference_month : view.fact.end_month
      if (start == null || end == null || start > end) {
        undated.push(view)
        continue
      }
      const proofs = result.evidence.filter((proof) =>
        [proof.reference.fact.id, proof.candidate.fact.id].includes(view.fact.id),
      )
      rows.push({
        view,
        person,
        start,
        end,
        common: proofs.length > 0,
        overlaps: proofs.filter((proof) => proof.relation_type === 'same_company_overlap'),
      })
    }
    rows.sort((a, b) => a.start - b.start || a.view.fact.id.localeCompare(b.view.fact.id))
    return { person, rows, undated }
  })
}
