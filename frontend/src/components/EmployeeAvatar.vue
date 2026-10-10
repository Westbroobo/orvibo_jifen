<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(defineProps<{ src?: string | null; name: string; size?: 'normal' | 'small' | 'tiny' }>(), { size: 'normal' })
const failed = ref(false)
watch(() => props.src, () => { failed.value = false })
</script>

<template>
  <span class="employee-avatar" :class="`employee-avatar-${size}`">
    <img v-if="src && !failed" :src="src" :alt="`${name}的头像`" loading="lazy" referrerpolicy="no-referrer" @error="failed = true">
    <svg v-else viewBox="0 0 24 24" fill="none" role="img" :aria-label="`${name}暂无头像`">
      <circle cx="12" cy="8" r="3.5" stroke="currentColor" stroke-width="1.5" />
      <path d="M5 20v-2a7 7 0 0 1 14 0v2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
    </svg>
  </span>
</template>

<style scoped>
.employee-avatar{display:inline-flex;align-items:center;justify-content:center;flex:none;vertical-align:middle;width:36px;height:36px;border-radius:6px;overflow:hidden;background:var(--surface-2);color:var(--faint);border:1px solid var(--line)}
.employee-avatar-small{width:28px;height:28px}.employee-avatar-tiny{width:22px;height:22px;border-radius:4px}
img{display:block;width:100%;height:100%;object-fit:cover}svg{width:72%;height:72%}
</style>
