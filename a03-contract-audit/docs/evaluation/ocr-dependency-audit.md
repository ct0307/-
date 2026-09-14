# OCR 依赖供应链审计

审计日期：2026-09-14

## 范围与方法

本次审计基于新建的 Python 3.13.1 Windows x64 虚拟环境，而非任何旧环境的安装记录。`backend/requirements-dev.txt` 引用生产依赖并固定 `pytest==8.3.5`。由于现有 `requirements.txt` 包含 UTF-8 中文注释，而当前 Windows 默认代码页为 CP936，下载和离线安装均设置 `PYTHONUTF8=1`。

执行步骤如下：

1. 使用 `pip download -r requirements-dev.txt` 从 PyPI 取得实际依赖工件。
2. 对下载目录中的每个 wheel 或 sdist 计算 SHA-256，并与相同包名、版本和文件名的 PyPI JSON `urls[].digests.sha256` 比对。
3. 从每个 wheel 的 `METADATA` 或每个 sdist 的 `PKG-INFO` 读取包名、版本和许可证声明；缺失字段不推断。
4. 查询每个包名和版本的 PyPI JSON `vulnerabilities` 字段，记录该审计日期可公开获得的结果。

完整逐工件清单、哈希、许可证来源和漏洞记录见 `docs/evaluation/python-wheel-manifest.json`。该清单不含本机绝对路径。

## 审计结果

| 检查项 | 结果 |
|---|---|
| 下载工件 | 105 个：103 个 wheel、2 个 sdist |
| 完整性 | 105/105 个 SHA-256 与 PyPI 发布文件摘要一致；0 个不匹配、0 个受限 |
| 元数据许可证 | 105/105 个工件在其自身元数据中给出许可证字段或许可证分类；不将此结果视为法律尽调 |
| 漏洞端点 | 105/105 个 PyPI 指定版本端点查询成功；记录 144 条公开记录，分布于 8 个包 |
| 离线安装 | 使用 `--no-index --find-links` 从本次 wheelhouse 安装；`pip check` 输出 `No broken requirements found.` |

PyPI 的 `vulnerabilities` 返回可能同时包含同一问题的 GHSA 和 PYSEC 标识，以下数量是端点记录数，不代表唯一 CVE 数量或严重性评级。完整标识和链接保存在清单中。

| 包 | 版本 | 公开记录数 |
|---|---:|---:|
| cryptography | 44.0.2 | 10 |
| pdfminer.six | 20231228 | 4 |
| PyJWT | 2.10.1 | 12 |
| pypdf | 5.1.0 | 81 |
| pytest | 8.3.5 | 2 |
| python-multipart | 0.0.20 | 12 |
| starlette | 0.41.3 | 14 |
| transformers | 4.57.6 | 9 |

这些记录需要在后续依赖升级任务中按可利用性、兼容性和版本锁定策略处理；本任务不擅自升级依赖。PyPI 端点是审计时点的公开数据，不能替代持续 SCA、许可证合规审查或发布前镜像扫描。

## 前端锁文件审计

在未修改 `package.json` 或 `package-lock.json` 的前提下执行 `npm.cmd ci`，随后执行 `npm.cmd audit --json`。该命令返回退出码 1，摘要为 3 个高危记录、0 个严重记录、0 个中危记录和 0 个低危记录。该结果作为既有前端依赖基线记录；本任务不执行 `npm audit fix` 或任何依赖升级。

## OCR 重点依赖

| 包 | 版本 | 下载文件 | SHA-256 | 元数据许可证 | PyPI 指定版本公开记录 |
|---|---:|---|---|---|---:|
| RapidOCR | 3.9.2 | `rapidocr-3.9.2-py3-none-any.whl` | `04d6b8d151f823d930bd91910555f57bea897c0c44fa6794267b94cf9c1ef9a0` | `License-Expression: Apache-2.0` | 0 |
| ONNX Runtime | 1.28.0 | `onnxruntime-1.28.0-cp313-cp313-win_amd64.whl` | `1a1a19175464665c9b8d50bc916f216cc0b569110045b7bbca8f9f290b186f58` | `License: MIT License` | 0 |

两项重点 wheel 的本地 SHA-256 均与 PyPI 对应发布文件摘要一致。运行时通过 `importlib.metadata` 验证 `rapidocr=3.9.2`，并直接导入验证 `onnxruntime=1.28.0`。

## 真实 OCR 验证

在新环境中执行：

```text
python -m pytest tests/test_ocr_real_integration.py tests/test_ocr_process.py -q -rs
6 passed, 5 warnings in 4.80s
```

集成用例实际加载 RapidOCR/ONNX Runtime，并对内存生成的扫描 PNG 与单页扫描 PDF 运行识别。结果未跳过；5 条警告为 PyMuPDF 相关 SWIG 类型的弃用警告。该烟雾测试仅证明本环境中的引擎导入、模型加载、图片 OCR 和 PDF OCR 调用链可用，不证明真实合同集上的 OCR 准确率或题目指标达标。
