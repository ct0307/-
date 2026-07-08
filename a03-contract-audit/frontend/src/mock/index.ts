// ============================================================
// Mock 数据总开关 · 演示级全景
// 页面只调 api/*.ts，api 层据此开关决定走 mock 还是真接口。
// 后端补齐对应接口后，把开关置 false 即可，页面零改动。
// ============================================================
export const MOCK_ENABLED = {
  dashboard: false, // 后端 /dashboard/summary 已就绪 + seed 数据
  reports: false,   // 后端 /reports/summary 已就绪
  knowledge: false, // 后端 /knowledge/cards + /stats 已就绪
  rectify: false,   // 后端 /rectifications 已就绪 + seed 数据
  history: false,   // 后端 /contracts 已就绪（HistoryRow 格式）
  rules: false,     // 后端 /rules + /templates 已就绪 + seed 数据
  admin: false,     // 后端 /admin/access-matrix + /audit-logs 已就绪 + seed 数据
}

// 模拟网络延迟，让页面能真实体现 loading 态
export function sleep(ms = 300): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// 模拟错误开关（调试三态用）：置 true 时对应 mock 抛错，验证 error 态
export const SIMULATE_ERROR = {
  reports: false,
  knowledge: false,
  history: false,
}

export async function mockRespond<T>(data: T, key?: keyof typeof SIMULATE_ERROR): Promise<T> {
  await sleep()
  if (key && SIMULATE_ERROR[key]) {
    throw new Error('模拟接口错误（演示三态）')
  }
  return data
}
