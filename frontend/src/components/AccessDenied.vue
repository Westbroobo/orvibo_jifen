<script setup lang="ts">
defineProps<{ checking: boolean }>()
const emit = defineEmits<{ check: [] }>()
</script>

<template>
  <main class="access-denied" aria-labelledby="access-denied-title">
    <section class="panel access-card">
      <div class="access-icon" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none"><path d="m24 5 15 6v12c0 10-9 17-15 20-6-3-15-10-15-20V11z" /><rect x="17" y="21" width="14" height="12" rx="3" /><path d="M20 21v-4a4 4 0 0 1 8 0v4M24 26v2" /></svg></div>
      <span class="access-label">访问受限</span>
      <h1 id="access-denied-title">当前账号暂无使用权限</h1>
      <p class="access-description">你已成功登录，但尚未开通员工积分系统权限，<br class="desktop-break">暂时无法使用系统或查看数据。</p>
      <div class="access-contact"><span>需要使用系统？</span><p>请联系 <strong>数据支持组</strong> 开通相关权限。</p></div>
      <button type="button" class="access-check" :disabled="checking" :aria-busy="checking" @click="emit('check')"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true" :class="{ spinning: checking }"><path d="M16.5 8a7 7 0 0 0-12-3L2 8m0-4v4h4M3.5 12a7 7 0 0 0 12 3l2.5-3m0 4v-4h-4" /></svg>{{ checking ? '正在检查…' : '重新检查权限' }}</button>
    </section>
  </main>
</template>

<style scoped>
.access-denied{display:flex;justify-content:center;padding:clamp(28px,8vh,88px) 0 32px}
.access-card{width:100%;max-width:580px;text-align:center;padding:44px 40px;box-shadow:var(--shadow-soft)}
.access-icon{display:flex;align-items:center;justify-content:center;width:76px;height:76px;margin:0 auto 22px;background:var(--accent-soft);color:var(--accent-deep);border-radius:20px}
.access-icon svg{width:42px;height:42px;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.access-label{font-size:var(--fs-xs);color:var(--muted);letter-spacing:.12em}
h1{margin:10px 0 14px;font-size:25px;line-height:1.5;overflow-wrap:anywhere}
.access-description{margin:0;color:var(--muted);font-size:var(--fs-md);line-height:1.9}
.access-contact{padding:18px 16px;margin:28px 0 24px;background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r-lg)}
.access-contact>span{font-size:var(--fs-xs);color:var(--muted)}
.access-contact p{margin:5px 0 0;font-size:var(--fs-md);line-height:1.8}
.access-contact strong{color:var(--accent-deep);font-weight:700}
.access-check{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 18px;font-family:var(--sans);background:var(--surface)}
.access-check svg{width:15px;height:15px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.spinning{animation:spin 1s linear infinite}
@media(max-width:640px){.access-denied{padding-top:24px}.access-card{padding:32px 20px}h1{font-size:22px}.access-icon{width:66px;height:66px;margin-bottom:18px}.access-contact{margin-top:24px}.desktop-break{display:none}}
</style>
