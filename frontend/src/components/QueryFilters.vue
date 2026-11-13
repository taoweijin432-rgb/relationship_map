<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import type { useWorkbench } from '../features/useWorkbench'
import { backgroundFilters } from '../features/queryState'
import { entityOptionLabel } from '../features/entityLabels'
const props = defineProps<{ workbench: ReturnType<typeof useWorkbench> }>()
const {
  mode,
  referenceId,
  personFilters,
  activeEntityFilters,
  topicKind,
  topicId,
  options,
  meta,
  hasMaterializedRelations,
  loading,
  suggestPeople,
  suggestEntities,
  runQuery,
  resetQuery,
} = props.workbench
const advanced = ref(false)
const advancedCount = computed(() => {
  if (mode.value === 'person')
    return (
      personFilters.company.length +
      Number(!!personFilters.source) +
      Number(!!personFilters.start) +
      Number(!!personFilters.end) +
      Number(personFilters.minMonths != null)
    )
  const f = activeEntityFilters.value
  return f.major.length + Number(!!f.source) + Number(!!f.start) + Number(!!f.end)
})
function changeTopicKind() {
  topicId.value = ''
  Object.assign(activeEntityFilters.value, backgroundFilters())
}
</script>
<template>
  <el-form label-position="top" class="query-form panel" @submit.prevent="runQuery()">
    <el-form-item v-if="mode === 'person'" label="你想查谁？">
      <el-select
        v-model="referenceId"
        filterable
        remote
        :remote-method="suggestPeople"
        placeholder="搜索姓名或业务编号"
        aria-label="参考人物"
        data-testid="reference-select"
      >
        <el-option
          v-for="person in options.people"
          :key="person.id"
          :value="person.id"
          :label="`${person.name} · ${person.id}`"
          ><span>{{ person.name }}</span
          ><span class="option-meta"
            >{{ person.headline }} ·
            {{
              person.sources.map((source) => (source === 'expert' ? '专家库' : '简历库')).join('/')
            }}
            · {{ person.serial_number || person.id }}</span
          ></el-option
        >
      </el-select>
    </el-form-item>
    <el-form-item v-if="mode === 'person'" label="最多关联跳数">
      <el-select
        v-model="personFilters.maxHops"
        aria-label="最多关联跳数"
        data-testid="max-hops-select"
        :disabled="(meta?.max_relation_hops ?? 1) === 1"
      >
        <el-option
          v-for="hops in meta?.max_relation_hops ?? 1"
          :key="hops"
          :value="hops"
          :label="hops === 1 ? '1 跳 · 直接关联' : `${hops} 跳以内`"
        />
      </el-select>
    </el-form-item>
    <el-form-item v-if="mode === 'person'" label="关系类型">
      <el-select
        v-model="personFilters.relation"
        :empty-values="[null, undefined]"
        aria-label="关系类型"
        data-testid="relation-select"
      >
        <el-option label="全部共同经历" value="" /><el-option
          label="同公司同期"
          value="same_company_overlap"
        /><el-option label="曾任职同一公司" value="same_company" /><el-option
          label="同校"
          value="same_school"
        />
        <el-option v-if="hasMaterializedRelations" label="同专业" value="same_major" />
      </el-select>
      <el-checkbox
        v-if="personFilters.relation === 'same_major'"
        v-model="personFilters.sameSchoolRequired"
        data-testid="same-school-required"
        >要求同校</el-checkbox
      >
    </el-form-item>
    <template v-if="mode === 'topic'">
      <el-form-item label="专题类型"
        ><el-select
          v-model="topicKind"
          aria-label="专题类型"
          data-testid="topic-kind"
          @change="changeTopicKind"
        >
          <el-option label="公司" value="organization" /><el-option
            label="学校"
            value="school"
          /><el-option v-if="hasMaterializedRelations" label="专业" value="major" /> </el-select
      ></el-form-item>
      <el-form-item label="标准实体"
        ><el-select
          v-model="topicId"
          filterable
          remote
          :remote-method="(q: string) => suggestEntities(topicKind, q)"
          :placeholder="hasMaterializedRelations ? '搜索标准名称' : '搜索标准名或别名'"
          aria-label="专题实体"
          data-testid="topic-select"
        >
          <el-option
            v-for="entity in options[topicKind]"
            :key="entity.id"
            :value="entity.id"
            :label="entityOptionLabel(entity, options[topicKind])"
          /> </el-select
      ></el-form-item>
    </template>
    <template v-if="mode !== 'person'">
      <el-form-item v-if="mode !== 'topic' || topicKind !== 'organization'" label="任职公司"
        ><el-select
          v-model="activeEntityFilters.company"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="2"
          clearable
          filterable
          remote
          :remote-method="(q: string) => suggestEntities('organization', q)"
          placeholder="不限公司"
          aria-label="任职公司"
          data-testid="company-select"
          ><el-option
            v-for="entity in options.organization"
            :key="entity.id"
            :value="entity.id"
            :label="entityOptionLabel(entity, options.organization)" /></el-select
      ></el-form-item>
      <el-form-item v-if="mode !== 'topic' || topicKind !== 'school'" label="学校"
        ><el-select
          v-model="activeEntityFilters.school"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="2"
          clearable
          filterable
          remote
          :remote-method="(q: string) => suggestEntities('school', q)"
          placeholder="不限学校"
          aria-label="学校"
          data-testid="school-select"
          ><el-option
            v-for="entity in options.school"
            :key="entity.id"
            :value="entity.id"
            :label="entityOptionLabel(entity, options.school)" /></el-select
      ></el-form-item>
      <el-form-item v-if="hasMaterializedRelations" label="任职职位（原文）">
        <el-select
          v-model="activeEntityFilters.positions"
          multiple
          filterable
          allow-create
          default-first-option
          clearable
          :reserve-keyword="false"
          placeholder="输入完整职位后按回车"
          aria-label="原始任职职位"
          data-testid="position-titles"
        />
        <span class="small muted">按同条工作经历的原始职位精确匹配，多个职位取其一。</span>
      </el-form-item>
      <el-form-item v-else label="任职职位"
        ><el-select
          v-model="activeEntityFilters.role"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="2"
          clearable
          filterable
          remote
          :remote-method="(q: string) => suggestEntities('role', q)"
          placeholder="不限职位"
          aria-label="任职职位"
          data-testid="role-select"
          ><el-option
            v-for="entity in options.role"
            :key="entity.id"
            :value="entity.id"
            :label="entityOptionLabel(entity, options.role)" /></el-select
      ></el-form-item>
    </template>
    <div class="filter-actions">
      <el-button
        type="primary"
        class="query-button"
        :icon="Search"
        :loading="loading"
        :disabled="!meta || (mode === 'person' && !referenceId)"
        native-type="submit"
      >
        {{ mode === 'person' ? '查关联人物' : '查询人物' }}
      </el-button>
      <el-button @click="resetQuery">重置</el-button>
      <el-button
        :aria-expanded="advanced"
        aria-controls="advanced-filters"
        @click="advanced = !advanced"
      >
        更多筛选<span v-if="advancedCount">（{{ advancedCount }}）</span>
      </el-button>
    </div>
    <div id="advanced-filters" v-show="advanced" class="advanced-filters">
      <template
        v-if="
          mode === 'person' &&
          ['same_company', 'same_company_overlap'].includes(personFilters.relation)
        "
      >
        <el-form-item label="共同任职公司"
          ><el-select
            v-model="personFilters.company"
            multiple
            collapse-tags
            clearable
            filterable
            remote
            :remote-method="(q: string) => suggestEntities('organization', q)"
            placeholder="不限共同公司"
            aria-label="共同任职公司"
            data-testid="relation-company-select"
          >
            <el-option
              v-for="entity in options.organization"
              :key="entity.id"
              :value="entity.id"
              :label="entityOptionLabel(entity, options.organization)"
            /> </el-select
        ></el-form-item>
        <template v-if="personFilters.relation === 'same_company_overlap'">
          <el-form-item label="共同任职时间窗"
            ><div class="month-range">
              <el-date-picker
                v-model="personFilters.start"
                type="month"
                format="YYYY-MM"
                value-format="YYYYMM"
                placeholder="起始月（可选）"
                aria-label="共同任职开始月"
              />
              <el-date-picker
                v-model="personFilters.end"
                type="month"
                format="YYYY-MM"
                value-format="YYYYMM"
                placeholder="结束月（可选）"
                aria-label="共同任职结束月"
              /></div
          ></el-form-item>
          <el-form-item label="最短共同任职月数"
            ><el-input-number
              v-model="personFilters.minMonths"
              :min="1"
              :max="2412"
              :precision="0"
              controls-position="right"
              placeholder="不限"
              aria-label="最短共同任职月数"
              data-testid="minimum-months"
          /></el-form-item>
          <p class="multi-filter-note">
            在所选时间窗内按单条经历对计算，不累加重复或多次任职的月份。
          </p>
        </template>
      </template>
      <template v-if="mode !== 'person'">
        <el-form-item
          v-if="hasMaterializedRelations && (mode !== 'topic' || topicKind !== 'major')"
          label="专业"
        >
          <el-select
            v-model="activeEntityFilters.major"
            multiple
            clearable
            filterable
            remote
            :remote-method="(q: string) => suggestEntities('major', q)"
            placeholder="不限专业"
            aria-label="专业"
            data-testid="major-select"
          >
            <el-option
              v-for="entity in options.major"
              :key="entity.id"
              :value="entity.id"
              :label="entityOptionLabel(entity, options.major)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="任职时间范围"
          ><div class="month-range">
            <el-date-picker
              v-model="activeEntityFilters.start"
              type="month"
              value-format="YYYYMM"
              placeholder="起始月"
              aria-label="任职开始月"
            /><el-date-picker
              v-model="activeEntityFilters.end"
              type="month"
              value-format="YYYYMM"
              placeholder="结束月"
              aria-label="任职结束月"
            /></div
        ></el-form-item>
      </template>
      <el-form-item label="人物来源">
        <el-select
          v-if="mode === 'person'"
          v-model="personFilters.source"
          :empty-values="[null, undefined]"
          aria-label="人物来源"
          data-testid="source-select"
          ><el-option label="专家库与简历库" value="" /><el-option
            label="仅专家库"
            value="expert" /><el-option label="仅简历库" value="resume"
        /></el-select>
        <el-select
          v-else
          v-model="activeEntityFilters.source"
          :empty-values="[null, undefined]"
          aria-label="人物来源"
          data-testid="source-select"
          ><el-option label="专家库与简历库" value="" /><el-option
            label="仅专家库"
            value="expert" /><el-option label="仅简历库" value="resume"
        /></el-select>
      </el-form-item>
    </div>
  </el-form>
</template>
