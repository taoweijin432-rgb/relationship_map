import type { Entity } from '../api/client'

// 上游允许同名实体；显示标识帮助用户选对，提交值始终为实体 ID。
export function entityOptionLabel(entity: Entity, options: readonly Entity[]): string {
  return options.some((other) => other.id !== entity.id && other.name === entity.name)
    ? `${entity.name} · ${entity.id}`
    : entity.name
}
