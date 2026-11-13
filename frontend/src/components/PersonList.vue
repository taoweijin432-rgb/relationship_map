<script setup lang="ts">
import { ArrowLeft, ArrowRight, User } from '@element-plus/icons-vue'
import type { SearchResponse } from '../api/client'

defineProps<{
  result: SearchResponse | null
  selectedId: string
  loading: boolean
  disabled?: boolean
  pageIndex: number
}>()
defineEmits<{ select: [id: string]; page: [direction: 1 | -1]; adjust: [] }>()
</script>

<template>
  <section class="person-list panel" aria-label="候选人物">
    <div class="panel-header">
      <h2>
        人物结果 <span v-if="result" class="count">{{ result.items.length }}</span>
      </h2>
      <span class="muted small">当前页</span>
    </div>
    <div class="list-scroll" :aria-busy="loading">
      <div v-if="loading" class="list-placeholder"><el-skeleton :rows="8" animated /></div>
      <div v-else-if="result && !result.items.length" class="empty-state">
        <el-icon :size="28"><User /></el-icon><strong>暂无匹配人物</strong
        ><span>试试调整关系类型或筛选条件</span
        ><el-button @click="$emit('adjust')">调整筛选</el-button>
      </div>
      <button
        v-for="item in result?.items ?? []"
        :key="item.person.id"
        class="person-row"
        :class="{ selected: selectedId === item.person.id }"
        :aria-pressed="selectedId === item.person.id"
        @click="$emit('select', item.person.id)"
        :data-testid="`person-${item.person.id}`"
      >
        <div class="person-row-top">
          <span class="avatar" :class="{ expert: item.person.sources.includes('expert') }">{{
            item.person.name.slice(-2)
          }}</span>
          <div class="person-info">
            <strong>{{ item.person.name }}</strong
            ><span
              >{{ item.person.city }}
              <span v-if="item.person.serial_number"> · {{ item.person.serial_number }}</span></span
            >
          </div>
          <el-icon class="row-arrow"><ArrowRight /></el-icon>
        </div>
        <div class="person-headline">{{ item.person.headline }}</div>
        <div class="person-tags">
          <span v-if="result?.reference" class="source-tag" data-testid="connection-hops">{{
            (item.connection?.hop_count ?? 1) === 1
              ? '直接关联'
              : `${item.connection?.hop_count} 跳关联`
          }}</span>
          <span
            v-for="source in item.person.sources"
            :key="source"
            class="source-tag"
            :class="source"
            >{{ source === 'expert' ? '专家库' : '简历库' }}</span
          >
        </div>
        <div v-if="item.relations?.length" class="relation-teaser">
          <span class="relation-dot" />{{ item.relations[0].label }} ·
          {{ item.relations[0].entity_name
          }}<span v-if="item.relations.length > 1"> +{{ item.relations.length - 1 }}</span>
        </div>
      </button>
      <div v-if="!loading && !result" class="empty-state"><span>选择条件开始探索</span></div>
    </div>
    <div class="list-pagination">
      <el-button
        circle
        :icon="ArrowLeft"
        aria-label="上一页"
        :disabled="loading || disabled || pageIndex === 0"
        @click="$emit('page', -1)"
      />
      <span>第 {{ pageIndex + 1 }} 页</span>
      <el-button
        circle
        :icon="ArrowRight"
        aria-label="下一页"
        :disabled="loading || disabled || !result?.has_more"
        @click="$emit('page', 1)"
      />
    </div>
  </section>
</template>
