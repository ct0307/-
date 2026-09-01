# Enterprise Legal Review Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将契鉴前端升级为可信、高密度、可追溯的企业法务审阅台，同时保持现有业务行为和接口不变。

**Architecture:** 先通过全局设计令牌和 Element Plus 覆盖建立统一视觉基础，再重排审查页和风险抽屉，最后用共享令牌收敛其他业务页面。所有修改保留现有 Pinia 状态和 API 调用，仅调整模板中已有数据的呈现方式及样式。

**Tech Stack:** Vue 3、TypeScript、Vite、Pinia、Element Plus、SCSS、ECharts、Playwright

---

### Task 1: 设计令牌与应用框架

**Files:**
- Modify: `frontend/src/styles/tokens.scss`
- Modify: `frontend/src/styles/element-overrides.scss`
- Modify: `frontend/src/styles/index.scss`
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/components/layout/AppHeader.vue`
- Modify: `frontend/src/components/layout/AppSidebar.vue`
- Modify: `frontend/src/components/layout/OpenClawBadge.vue`
- Modify: `frontend/src/components/layout/UserSwitcher.vue`

- [ ] 将页面、表面、文字和语义色替换为设计规格中的精确值。
- [ ] 将普通卡片改为边线表面，收紧顶栏与内容区间距。
- [ ] 减少侧栏底部独立卡片感，保持响应式和键盘行为。
- [ ] 运行 `npm run type-check`，预期退出码 0。

### Task 2: 核心审查工作台

**Files:**
- Modify: `frontend/src/views/AuditView.vue`
- Modify: `frontend/src/components/audit/RiskReviewDrawer.vue`
- Modify: `frontend/tests/enterprise-ui.spec.ts`
- Modify: `frontend/tests/ocr-quality-e2e.spec.ts`

- [ ] 把审查页双栏调整为 360px 配置轨和连续结果工作面。
- [ ] 为风险列表加入证据状态，并保持现有排序和点击复核逻辑。
- [ ] 在抽屉中增加无可靠来源警告及证据链视觉轨道。
- [ ] 覆盖空状态、人工复核、错误状态和移动端布局。
- [ ] 运行相关 Playwright 测试，预期全部通过或按既有条件跳过。

### Task 3: 其他业务页面统一

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`
- Modify: `frontend/src/views/ReportsView.vue`
- Modify: `frontend/src/views/KnowledgeView.vue`
- Modify: `frontend/src/views/RulesView.vue`
- Modify: `frontend/src/views/HistoryView.vue`
- Modify: `frontend/src/views/RectifyView.vue`
- Modify: `frontend/src/views/AdminView.vue`
- Modify: `frontend/src/views/CollaborationView.vue`

- [ ] 统一工具栏、KPI、数据面板、表格、列表和空状态。
- [ ] 减少阴影和卡片嵌套，保留页面已有数据与交互。
- [ ] 统一风险颜色、数字排版和移动端断点。
- [ ] 运行 `npm run type-check`，预期退出码 0。

### Task 4: 完整验证与视觉修正

**Files:**
- Verify only; screenshots remain outside repository.

- [ ] 运行 `npm run type-check`，预期退出码 0。
- [ ] 运行 `npm run build`，预期退出码 0。
- [ ] 运行 `npm test`，预期 0 failed。
- [ ] 浏览器验证 1440x900、1920x1080、390x844 页面身份、非空、Console、交互与横向溢出。
- [ ] 使用 `view_image` 对比基线与最终截图，记录至少六项差异并修复可见问题。
- [ ] 运行 `git diff --check`，预期无输出。
