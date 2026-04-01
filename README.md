# PolicyAnalyzerPro

## 项目简介

PolicyAnalyzerPro is an offline-first desktop analyzer for long-form government and policy documents on Windows. The current iteration adds routing skeletons for offline, online, and hybrid analysis while keeping the offline workflow as the default primary path.

这套项目不是通用聊天工具，而是面向内网、政务、研究场景的本地分析器。核心设计目标是：

- Offline-first by default; online and hybrid modes are optional and only attempted when explicitly selected and properly configured
- Windows 桌面环境可稳定运行，不阻塞 UI
- 支持长文本导入、清洗、分析和正式报告导出
- 在进入业务功能前先完成部署自检，尽量把环境问题前置暴露
- 利用 Python 3.13+ 运行时优化，提升性能和用户体验

## 核心能力

- **单篇分析**：提取元信息、新提法、核心议题、摘要页和文本结构分析
- **双篇比对**：输出措辞演变、删减监测、新增议题、保留议题和强化议题
- **批量分析**：对多份文档执行聚合分析并汇总主题与新提法
- **文档导入**：支持 TXT、DOCX、PDF
- **PDF 处理**：优先读取文字层；扫描版 PDF 支持 OCR 回退
- **OCR 增强**：支持页码范围选择和 OCR 结果缓存
- **结果导出**：支持 Markdown、HTML、JSON 分析报告
- **部署诊断**：支持 Markdown、HTML、PDF 诊断报告导出
- **启动前自检**：覆盖配置、依赖、模型目录、模型试加载、性能基准、OCR 管线、语言包、字体和词典
- **测试覆盖**：当前仓库包含 smoke tests 与 GUI 交互测试

## Modes

- **Offline**: keeps the existing local import, local OCR, local analysis, and local export workflow as the default path
- **Online**: reserves an online LLM invocation skeleton; when unavailable, the app shows a clear warning and falls back to offline
- **Hybrid**: reserves a local-preprocess plus online-enhancement orchestration skeleton; when unavailable, the app falls back to offline
- **Mode hints**: the main window now shows mode selection, online status, and routing hints so mode changes are never silent

## Config Extensions

The default config now includes the fields below for three-mode routing and future extensions:

- `analysis_mode`: `offline | online | hybrid`, default `offline`
- `policy_source_enabled`: enables the policy source skeleton
- `llm_provider`: placeholder provider selection for online analysis
- `cloud_fallback_enabled`: allows online or hybrid mode to attempt remote capability

## 技术栈

| 模块 | 核心技术 | 工程作用 |
|------|----------|----------|
| 前端 | PySide6 | 响应式桌面 UI，基于 Qt 的跨平台界面 |
| 后端 | Python 3.13+ | 建议 3.13 / 3.14，兼顾性能与稳定性 |
| NLP 核心 | SentenceTransformers | 中文语义高维特征提取 |
| 算法 | Jieba (TextRank), Numpy | 文本清洗、图排序提取核心议题、余弦相似度计算 |
| 文档处理 | python-docx, pypdf, PyMuPDF | 多格式文档解析与 OCR 支持 |
| 部署 | PyInstaller | 独立可执行文件打包 |

## 运行环境与依赖前提

- **操作系统**：Windows 10 或 Windows 11
- **Python 环境**：建议 Python 3.13 或 3.14，项目虚拟环境 `.venv`；当前仓库已在 Python 3.14.3 下验证通过
- **本地模型**：需提前放置离线 `SentenceTransformer / Transformers` 模型文件
- **OCR 可选能力**：如需处理扫描版 PDF，需本地安装 Tesseract 和对应语言包

项目依赖见 [requirements.txt](requirements.txt)。离线模型目录要求见 [models/README.md](models/README.md)。

## 快速开始

1. **安装依赖**

```powershell
D:\chapter1\.venv\Scripts\python.exe -m pip install -r D:\chapter1\requirements.txt
```

2. **放置本地模型**

将离线模型放到 [models/README.md](models/README.md) 说明的目录中，默认路径为：

```text
D:\chapter1\models\hfl\chinese-roberta-wwm-ext
```

3. **按需配置 OCR**

If you need scanned PDF OCR, configure `tesseract_cmd` and `ocr_languages` in [config/default_config.json](config/default_config.json). If you later want to try online or hybrid mode, configure `analysis_mode`, `llm_provider`, `cloud_fallback_enabled`, and `policy_source_enabled` in the same file.

4. **启动程序**

```powershell
D:\chapter1\.venv\Scripts\python.exe D:\chapter1\main.py
```

首次启动会先执行部署自检；如果环境未就绪，会自动进入部署向导。

## 离线模型与 OCR 说明

### 离线模型

- 模型目录、最低必需文件和放置方式见 [models/README.md](models/README.md)
- 程序使用 `local_files_only=True` 强制本地加载，不会联网回退
- 启动自检会区分“模型目录存在”“模型可以试加载”“模型热身和性能是否可接受”
- 模型加载已优化，兼容 Python 3.13+ 运行时优化

### OCR

- OCR 是可选能力，不影响 TXT、DOCX 和有文字层 PDF 的正常使用
- 有文字层的 PDF 会优先直接提取文字层，不会默认走 OCR
- 只有当 PDF 缺少稳定文字层时，才会尝试使用 `PyMuPDF + Pillow + pytesseract` 回退识别
- 如需配置 Tesseract，可参考 [docs/TESSERACT_SETUP.md](docs/TESSERACT_SETUP.md)

## 部署自检与诊断报告

启动自检当前覆盖以下检查项：

- 配置文件
- 核心依赖
- 离线模型目录完整性
- 模型试加载
- 模型热身与性能基准
- 文档导入依赖
- OCR 管线
- Tesseract 语言包
- 字体资源
- 自定义词典

检查结果会按状态分级展示，帮助区分“可运行”“需要注意”“必须修复”。部署向导支持导出以下格式的诊断报告：

- Markdown
- HTML
- PDF

如果启动后需要再次检查当前环境，可在主界面中重新打开“环境自检”。

## 导出能力

分析结果当前支持导出为：

- Markdown
- HTML
- JSON

HTML 报告面向打印和归档，包含封面、摘要、议题变化和证据区。部署诊断报告则支持 Markdown、HTML、PDF 三种格式，适合交付和排障留档。

## 项目结构概览

```text
D:\chapter1
|-- main.py              # 程序入口
|-- README.md            # 项目说明
|-- config/              # 配置文件
|-- core/                # 核心功能模块
|-- docs/                # 文档
|-- importers/           # 文档导入模块
|-- models/              # 离线模型目录
|-- scripts/             # 构建和部署脚本
|-- tests/               # 测试文件
|   |-- test_smoke.py    # 冒烟测试
|   `-- test_gui.py      # GUI 测试
`-- ui/                  # 用户界面
```

## 性能优化

- **模型加载优化**：利用 Python 3.13+ 运行时优化，减少模型加载时间
- **预热机制**：在程序启动和工作进程初始化时预热模型，减少首次分析延迟
- **多进程管理**：优化进程池配置，提高并发处理能力
- **内存使用**：减少不必要的内存分配，提高内存使用效率

## 安全性改进

- **输入验证**：增强文件路径和输入参数验证，防止路径遍历攻击
- **文件大小限制**：设置最大文件大小限制，防止处理过大的文件
- **错误处理**：改进错误处理机制，提供更清晰的错误信息
- **权限管理**：确保模型和缓存目录权限正确，避免权限错误

## 开发与测试

### 语法检查

```powershell
D:\chapter1\.venv\Scripts\python.exe -m py_compile D:\chapter1\main.py D:\chapter1\core\config.py D:\chapter1\core\algorithms.py D:\chapter1\core\nlp_thread.py D:\chapter1\core\result_formatter.py D:\chapter1\core\startup_checks.py D:\chapter1\core\text_cleaner.py D:\chapter1\core\import_preview.py D:\chapter1\importers\document_loader.py D:\chapter1\ui\main_window.py D:\chapter1\ui\startup_wizard.py
```

### 测试运行

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
```

当前仓库包含 smoke tests 与 GUI 交互测试，适合在改动导入、分析流程、部署自检和主界面交互后做回归验证。
### 源码自检

```powershell
.\.venv\Scripts\python.exe .\main.py --self-check --self-check-json .\tmp\startup-self-check.json
```

### OCR 端到端验收

```powershell
.\.venv\Scripts\python.exe .\scripts\ocr_acceptance.py --output-dir .\tmp\ocr_acceptance
```

### P0 验收入口

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_p0_acceptance.ps1 -Python .\.venv\Scripts\python.exe
```

### 打包后启动校验

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_dist.ps1 -Python .\.venv\Scripts\python.exe -Build
```


## 打包与部署

### 构建可执行文件

```powershell
.\scripts\build.ps1 -Python .\.venv\Scripts\python.exe
```

构建脚本会自动处理依赖、资源文件和模型文件的打包，生成独立的可执行文件。

## 文档入口

- **架构说明**：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **模型目录说明**：[models/README.md](models/README.md)
- **Tesseract 安装说明**：[docs/TESSERACT_SETUP.md](docs/TESSERACT_SETUP.md)
- **打包脚本**：[scripts/build.ps1](scripts/build.ps1)

## 版本更新

### v2.0.0 主要更新

- **性能优化**：利用 Python 3.13+ 运行时优化，优化模型加载和推理速度
- **功能增强**：添加文本结构分析功能，改进 UI/UX 体验
- **安全性**：增强输入验证，改进错误处理和日志记录
- **部署优化**：更新打包脚本，改进离线模型管理
- **文档更新**：完善项目文档，提供更详细的使用指南

## 开源协议

本项目基于 MIT License 协议开源。
