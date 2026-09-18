# 证据驱动审计收尾计划

## 目标

完成当前分支的代码验收，明确哪些项已验证、哪些项仍需真实业务环境实测。

## 阶段

- [completed] 1. 核对当前改动、测试和报告兼容性
- [completed] 2. 补充前端证据轨迹测试
- [completed] 3. 运行后端迁移测试和完整质量门禁
- [completed] 4. 检查前端协作/报告证据展示覆盖范围
- [completed] 5. 完成 diff、状态和剩余实测边界验收

## 验收清单

- 后端测试与迁移测试有新鲜通过证据
- 前端类型检查、构建和证据轨迹测试有新鲜通过证据
- `evaluation/report.py` 不会误读或遗漏 `audit-ablation` 流
- 质量门禁结果、工作树状态和真实实测边界已记录

## 本轮验收结果

- 完整质量门禁退出码为 0：evaluation 100 passed，backend 1374 passed，frontend 105 passed、38 skipped，type-check passed，build passed。
- 本分支作为主线保留证据驱动审查能力；参考分支的失败安全、稳定错误码、重试边界和性能评测能力作为互补项，不直接重复 cherry-pick。
- 真实专家金标、真实模型精排、PostgreSQL、GPU/OpenClaw、能耗和完整真实业务流程仍标记为“代码就绪待实测”。
