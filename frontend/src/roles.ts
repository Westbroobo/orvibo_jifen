// 系统内置身份只在服务端参与权限判断，界面统一按管理员展示。
export function displayRoleName(id: string, name?: string): string {
  if (id === 'owner') return '管理员'
  return name || ({ admin: '管理员', operator: '操作员', none: '普通员工' }[id] ?? id)
}
