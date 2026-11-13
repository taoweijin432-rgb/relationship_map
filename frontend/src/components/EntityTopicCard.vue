<script setup lang="ts">
import type { Entity } from '../api/client'
defineProps<{ entity: Entity; count: number | null; hasMore: boolean }>()
</script>
<template>
  <section
    class="entity-topic-card panel"
    aria-label="实体专题档案"
    data-testid="entity-topic-card"
  >
    <div class="entity-symbol">
      {{ entity.type === 'major' ? '专' : entity.type === 'organization' ? '企' : '学' }}
    </div>
    <div class="entity-topic-intro">
      <span class="eyebrow">{{
        entity.type === 'major'
          ? '专业专题'
          : entity.type === 'organization'
            ? '公司专题'
            : '学校专题'
      }}</span>
      <h2>{{ entity.name }}</h2>
      <details class="source-details">
        <summary>标识与别名</summary>
        <p>标准标识 {{ entity.id }} · 上游归一结果</p>
        <span v-for="alias in entity.aliases" :key="alias">{{ alias }}</span>
        <small v-if="!entity.aliases?.length">暂无已知别名</small>
      </details>
    </div>
    <div class="entity-topic-scope">
      <strong>{{ count ?? '—' }}</strong
      ><span>当前页人物</span
      ><small>{{
        count === null ? '等待查询成功' : hasMore ? '还有后续页面' : '已到当前条件最后一页'
      }}</small
      ><small>不代表在职人数或全局排名</small>
    </div>
  </section>
</template>
