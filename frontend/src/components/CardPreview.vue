<script setup lang="ts">
import { computed } from 'vue'
import type { CardContext, CardVariables } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ context: CardContext; variables?: CardVariables; avatarUrl?: string }>()
const plus = computed(() => props.context.delta > 0)
const values = computed<CardVariables>(() => props.variables ?? {
  department: props.context.department,
  user_name: props.context.person_name,
  reason: props.context.reason,
  score: String(props.context.delta),
  total_score: String(props.context.total),
})
</script>

<template>
  <div class="card-preview-person"><EmployeeAvatar :src="avatarUrl" :name="values.user_name" /><b>{{ values.user_name }}</b></div>
  <article class="points-card" :class="plus ? 'points-card-plus' : 'points-card-minus'" :aria-label="plus ? '加分卡片' : '扣分卡片'">
    <div class="points-card-top">
      <strong>{{ plus ? '优秀！加分' : '预警！扣分！' }}</strong>
      <span>结果论英雄<br>过程定成败</span>
    </div>
    <div class="points-card-department">{{ values.department }}</div>
    <p class="points-card-person">人员： {{ values.user_name }}</p>
    <p class="points-card-reason">原因：{{ values.reason }}</p>
    <div class="points-card-scores">
      <div><span>{{ plus ? '当前加分' : '当前减分' }}</span><strong>{{ plus ? '+ ' : '' }}{{ values.score }} 分</strong></div>
      <div><span>当前总分</span><strong>{{ values.total_score }} 分</strong></div>
    </div>
  </article>
  <p class="card-preview-meta">{{ context.month }} · 操作人：{{ context.operator_name }}<br>{{ context.time }}</p>
</template>

<style scoped>
.card-preview-person{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-size:13px}
.points-card{--card-color:#22872d;--department-color:#35a454;background:var(--card-color);color:#fff;border-radius:6px;padding:16px 20px 26px;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55;box-shadow:0 2px 8px #0000000a;overflow-wrap:anywhere}
.points-card-minus{--card-color:#ff9b20;--department-color:#e77600}
.points-card-top{display:grid;grid-template-columns:2fr 1fr;align-items:center;gap:8px;margin-bottom:14px;text-align:center;font-size:13px}
.points-card-top>strong{font-size:15px}.points-card-top>span{font-size:11px;font-weight:700;line-height:1.45}
.points-card-department{background:#fff;color:var(--department-color);padding:8px 12px;border-radius:4px;font-size:16px;font-weight:700;text-align:center;white-space:pre-wrap}
.points-card-person,.points-card-reason{color:#fff;font-size:14px;font-weight:700;text-align:center;margin:28px 8px 0;white-space:pre-wrap}
.points-card-scores{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:32px;text-align:center}.points-card-scores span{display:block;font-size:11px;font-weight:700}.points-card-scores strong{display:block;font-size:17px;margin-top:5px}
.card-preview-meta{font-size:10px;color:var(--faint);margin:14px 0 0;line-height:1.8}
@media(max-width:420px){.points-card{padding:14px 14px 22px}.points-card-top>strong{font-size:14px}.points-card-department{font-size:14px}.points-card-person,.points-card-reason{font-size:13px}}
</style>
