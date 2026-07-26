# OCR 依赖供应链审计

审计日期：2026-07-26

## 审计结论

| 优先级 | 检查项 | 结论 |
|---|---|---|
| P1 | 官方来源与完整性 | 两个 wheel 均来自 PyPI 官方文件源，文件大小和 SHA256 与 PyPI 元数据一致 |
| P1 | 许可证 | RapidOCR 元数据声明 `Apache-2.0`；ONNX Runtime 声明 `MIT` 并在 wheel 内附许可证和第三方声明 |
| P1 | 已知漏洞 | 本次解析的 22 个固定版本在 PyPI 指定版本漏洞记录中均为 0 |
| P1 | 运行兼容性 | Python 3.13.1 / Windows x64 下，真实 RapidOCR + ONNX Runtime 图片及扫描 PDF 冒烟通过 |
| P2 | 生产镜像 | `python:3.11-slim` 补充 OpenCV 所需 `libgl1`、`libglib2.0-0`；仍需 Docker 环境构建验收 |

PyPI 漏洞记录是审计时点的公开数据，不等于完整的软件成分分析或未来无漏洞。生产发布仍应在 CI 中执行持续 SCA 和镜像扫描。

## 直接依赖证据

| 包 | 版本 | wheel | SHA256 | 许可证证据 |
|---|---:|---|---|---|
| RapidOCR | 3.9.2 | `rapidocr-3.9.2-py3-none-any.whl` | `04d6b8d151f823d930bd91910555f57bea897c0c44fa6794267b94cf9c1ef9a0` | wheel `METADATA`：`License-Expression: Apache-2.0`；wheel 未附独立 LICENSE 文件 |
| ONNX Runtime | 1.28.0 | `onnxruntime-1.28.0-cp313-cp313-win_amd64.whl` | `1a1a19175464665c9b8d50bc916f216cc0b569110045b7bbca8f9f290b186f58` | wheel `METADATA`：`License: MIT License`；包含 `onnxruntime/LICENSE` 和 `ThirdPartyNotices.txt` |

## 传递依赖快照

以下版本来自隔离目录的 pip 安装报告，并逐项查询 PyPI 指定版本漏洞记录：

| 包 | 版本 | PyPI 已登记漏洞数 |
|---|---:|---:|
| antlr4-python3-runtime | 4.9.3 | 0 |
| certifi | 2026.7.22 | 0 |
| charset-normalizer | 3.4.9 | 0 |
| colorama | 0.4.6 | 0 |
| colorlog | 6.12.0 | 0 |
| flatbuffers | 25.12.19 | 0 |
| idna | 3.18 | 0 |
| numpy | 2.5.1 | 0 |
| omegaconf | 2.3.1 | 0 |
| opencv-python | 5.0.0.93 | 0 |
| packaging | 26.2 | 0 |
| Pillow | 12.3.0 | 0 |
| protobuf | 7.35.1 | 0 |
| pyclipper | 1.4.0 | 0 |
| PyYAML | 6.0.3 | 0 |
| requests | 2.34.2 | 0 |
| Shapely | 2.1.2 | 0 |
| six | 1.17.0 | 0 |
| tqdm | 4.69.1 | 0 |
| urllib3 | 2.7.0 | 0 |

RapidOCR 和 ONNX Runtime 两个直接依赖已在上一表单列；合计审计 22 个包。

## 真实引擎冒烟边界

本次在内存中生成中文扫描图片和单页扫描 PDF，RapidOCR 识别出“甲方：浙江测试公司”和“合同金额：人民币壹万元”，图片与 PDF 调用链均返回非空文本和置信度。仓库中的 `tests/test_ocr_real_integration.py` 提供可重复的真实引擎集成烟雾测试。

该证据只证明引擎安装、模型加载、图片识别和 PDF 编排可用，不证明赛题要求的字符准确率或合同要素准确率。准确率结论仍必须使用冻结扫描件真值集。
