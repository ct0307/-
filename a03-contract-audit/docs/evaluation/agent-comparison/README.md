# 单 Agent 与法财双 Agent 对照

协议见protocol.md，三项创新表述见innovation-final.md。当前使用gpt-6.1-sol，20份合成测试合同、6份开发合同，三组各重复3次。原始文件保持不变。

## 本机复现

在backend目录执行，使用已安装的虚拟环境，不安装新依赖：

```powershell
.\.venv\Scripts\python.exe -m evaluation.agent_comparison prepare --source 'C:/Users/chentao/Desktop/测试合同' --out '../outputs/agent-comparison-new'
.\.venv\Scripts\python.exe -m evaluation.agent_comparison run --dataset '../outputs/agent-comparison-new' --out '../outputs/agent-comparison-new-run'
```

第二条默认只验证输入，不调用模型。真正调用需加--execute；若未在.env设置出站白名单，只有已取得具体目的地授权后才能加--authorize-configured-endpoint，它只影响当前进程。不得把密钥写入脚本、提示词或报告。

本次授权只对应当前配置中的yorhamc.com；未来改变目的地须重新授权。已经冻结的目录不能覆盖，需换新输出名。

## 人工复核与评分

1. 从outputs/agent-comparison-20261031-v2/review-template.json复制独立的法务和财务标注文件，各自阅读全文。risks为null表示未标注，空数组必须经过人工确认，不能由程序直接填空冒充无风险。每条风险填写risk_id、category（legal/finance）、quote、issue、severity、basis。
2. 保留两份独立标注及裁决文件。至少两名真实复核人员完成后，在合并标注中填reviewers和review_status=agreed；分歧由独立第三人裁决后填adjudicated及adjudicator。不要用AI名字或编造人名代替。
3. 模型运行目录中的blind-review.json交给复核人。private-unblind-map.json仅由实验管理员保管。按原数组从0开始编号，judgments中每项填finding_index、gold_risk_id（误报填null）、duplicate_of（非重复填null）及理由。所有输出均须评，不只挑有效项。
4. 完成后调用评分：

```powershell
.\.venv\Scripts\python.exe -m evaluation.agent_comparison_score --run '../outputs/agent-comparison-20261031-gpt61-run' --gold '<已复核的完整标注.json>' --review '<已完成的盲评.json>'
```

评分会拒绝未复核、缺组、缺轮次、缺合同及缺预测裁决的输入。它只能校验结构，不能证明签名真实或法律判断正确。探索运行后标注只能形成事后内部评估；正式效果验证需先冻结独立标签再重跑。未评分前各项风险质量均为未测量。

## AI模拟角色复核（用户追加授权）

用户要求由助手分别代入法务、财务完成辅助复核。执行协议见[ai-review-protocol.md](ai-review-protocol.md)，结果保存在outputs/agent-comparison-20261031-ai-review，不覆盖原实验与人工模板。

```powershell
# 以下命令默认只检查输入，不出站；实际调用需已有目的地授权并显式加两个执行参数。
.\.venv\Scripts\python.exe -m evaluation.agent_comparison_ai_review --dataset '../outputs/agent-comparison-20261031-v2' --original-run '../outputs/agent-comparison-20261031-gpt61-run' --out '../outputs/agent-comparison-20261031-ai-review' --phase references
.\.venv\Scripts\python.exe -m evaluation.agent_comparison_ai_review --dataset '../outputs/agent-comparison-20261031-v2' --original-run '../outputs/agent-comparison-20261031-gpt61-run' --out '../outputs/agent-comparison-20261031-ai-review' --phase judgments
```

`references`先执行40套独立角色标注和20次合并，冻结ai-reference-v1.json，再执行`judgments`。只在已获授权时加`--execute --authorize-configured-endpoint`。已保存任务复用原记录，输入或模型变化会拒绝续跑；不要编辑输出冒充新任务成功。

裁决采用纯字母预测ID以免数字摘要误触敏感规则。早期judgments目录保留原尝试，当前judgments-v2为最终裁决；4份成功记录经可逆编号转换复用，provenance及源散列可追溯，不重复请求模型。一次进程中断最多有3个在途请求状态及用量未知，不能据已返回Token估算完整费用。

完成后生成两份Word及两份逐条CSV：

```powershell
.\.venv\Scripts\python.exe -m evaluation.agent_comparison_ai_report --dataset '../outputs/agent-comparison-20261031-v2' --original-run '../outputs/agent-comparison-20261031-gpt61-run' --review '../outputs/agent-comparison-20261031-ai-review'
```

AI参考不是人工金标，AI裁决不是专家结论。标注与裁决使用同一被测模型，存在自评偏差。AI参考覆盖率仅用于内部排查，不改写原实验的人工Precision/Recall/F1，也不能将role-annotations或ai-blind-review伪装成人工评分输入。
