export type ResultTone = 'success' | 'warning' | 'danger' | 'neutral'
export interface ResultBadge { text: string; tone: ResultTone; pulse?: boolean }

export function notificationState(count: number, sent: Record<string, number>, recalled: Record<string, number> = {}): ResultBadge {
  if (recalled.pending || recalled.recalling) return { text: '撤回中', tone: 'warning', pulse: true }
  if (recalled.failed || recalled.review) return { text: '撤回异常', tone: 'danger' }
  if (count > 0 && (recalled.recalled ?? 0) >= count) return { text: '已撤回', tone: 'neutral' }
  if (recalled.recalled) return { text: '部分撤回', tone: 'warning' }
  if (sent.failed) return { text: '发送异常', tone: 'danger' }
  if (sent.review) return { text: '待核实', tone: 'warning' }
  if (sent.sending || sent.pending) return { text: sent.sending || sent.sent ? '发送中' : '待发送', tone: 'warning', pulse: true }
  if (count > 0 && (sent.sent ?? 0) >= count) return { text: '已发送', tone: 'success' }
  return { text: count ? '待发送' : '无通知', tone: 'neutral' }
}

export function notificationNotes(sent: Record<string, number>, recalled: Record<string, number> = {}): ResultBadge[] {
  const notes: ResultBadge[] = []
  if (sent.failed) notes.push({ text: `发送失败 ${sent.failed}`, tone: 'danger' })
  if (sent.review) notes.push({ text: `发送待核实 ${sent.review}`, tone: 'warning' })
  if (sent.pending || sent.sending) notes.push({ text: `待完成 ${(sent.pending ?? 0) + (sent.sending ?? 0)}`, tone: 'neutral' })
  if (recalled.pending || recalled.recalling) notes.push({ text: `撤回处理中 ${(recalled.pending ?? 0) + (recalled.recalling ?? 0)}`, tone: 'warning' })
  if (recalled.failed) notes.push({ text: `撤回失败 ${recalled.failed}`, tone: 'danger' })
  if (recalled.review) notes.push({ text: `撤回待核实 ${recalled.review}`, tone: 'warning' })
  return notes
}

const beijingTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})
export function recordTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return { date: '—', time: '—' }
  const parts = Object.fromEntries(beijingTime.formatToParts(date).map(part => [part.type, part.value]))
  return { date: `${parts.year}/${parts.month}/${parts.day}`, time: `${parts.hour}:${parts.minute}:${parts.second}` }
}
