# ECharts Prebundle Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让多维报表在 Vite 开发环境中稳定完成四张 ECharts 图表渲染并移除加载遮罩。

**Architecture:** 保留 `BaseChart.vue` 的按需引入，在 Vite 启动阶段显式预构建所有已使用的 ECharts 子入口。使用配置契约测试锁定触发条件，并用独立 API 桩的页面测试覆盖用户可见结果。

**Tech Stack:** Vue 3、Vite 6、ECharts 6、Playwright Test、TypeScript

---

### Task 1: 建立失败回归测试

**Files:**
- Create: `frontend/tests/reports-echarts.spec.ts`

- [x] 写配置测试，断言四个 ECharts 子入口都位于 `optimizeDeps.include`。
- [x] 写页面测试，模拟报表接口并断言遮罩消失、四个 canvas 出现、无 ECharts 运行时错误。
- [x] 运行 `npm.cmd test -- tests/reports-echarts.spec.ts`，确认修复前失败原因与缺少预构建入口一致。

### Task 2: 添加最小 Vite 配置

**Files:**
- Modify: `frontend/vite.config.ts`
- Test: `frontend/tests/reports-echarts.spec.ts`

- [x] 在 `defineConfig` 顶层添加 `optimizeDeps.include`，仅列出当前使用的四个 ECharts 子入口。
- [x] 重跑目标测试，确认配置契约和页面行为通过。

### Task 3: 完整验收

**Files:**
- Verify: `frontend/vite.config.ts`
- Verify: `frontend/tests/reports-echarts.spec.ts`

- [x] 运行 `npm.cmd run type-check`。
- [x] 运行 `npm.cmd run build`。
- [x] 使用浏览器访问 `/reports`，确认页面身份、非空、无框架错误、控制台健康、遮罩退出和四张图表渲染。
- [x] 检查定向 `git diff`，确认没有修改无关文件。
