# PolicyAnalyzerPro

PolicyAnalyzerPro 是一套面向 Windows 的离线政务文本分析桌面软件，用于政府工作报告、政策通稿、会议纪要等长文本的单篇研判、双篇演变比对和批量分析。项目重点解决离线部署、模型加载稳定性、扫描版 PDF OCR、报告导出和桌面端可交付性问题。

## 项目简介

这套项目不是通用聊天工具，而是面向内网、政务、研究场景的本地分析器。核心设计目标是：

- 全程离线，不依赖联网推理或在线模型下载
- Windows 桌面环境可稳定运行，不阻塞 UI
- 支持长文本导入、清洗、分析和正式报告导出
- 在进入业务功能前先完成部署自检，尽量把环境问题前置暴露

## 核心能力

- 单篇分析：提取元信息、新提法、核心议题和摘要页
- 双篇比对：输出措辞演变、删减监测、新增议题、保留议题和强化议题
- 批量分析：对多份文档执行聚合分析并汇总主题与新提法
- 文档导入：支持 TXT、DOCX、PDF
- PDF 处理：优先读取文字层；扫描版 PDF 支持 OCR 回退
- OCR 增强：支持页码范围选择和 OCR 结果缓存
- 结果导出：支持 Markdown、HTML、JSON 分析报告
- 部署诊断：支持 Markdown、HTML、PDF 诊断报告导出
- 启动前自检：覆盖配置、依赖、模型目录、模型试加载、性能基准、OCR 管线、语言包、字体和词典
- 测试覆盖：当前仓库包含 smoke tests 与 GUI 交互测试

## 运行环境与依赖前提

- 操作系统：Windows 10 或 Windows 11
- Python 环境：项目虚拟环境 `.venv`
- 本地模型：需提前放置离线 `SentenceTransformer / Transformers` 模型文件
- OCR 可选能力：如需处理扫描版 PDF，需本地安装 Tesseract 和对应语言包

项目依赖见 [requirements.txt](requirements.txt)。离线模型目录要求见 [models/README.md](models/README.md)。

## 快速开始

1. 安装依赖

```powershell
D:\chapter1\.venv\Scripts\python.exe -m pip install -r D:\chapter1\requirements.txt
```

2. 放置本地模型

将离线模型放到 [models/README.md](models/README.md) 说明的目录中，默认路径为：

```text
D:\chapter1\models\hfl\chinese-roberta-wwm-ext
```

3. 按需配置 OCR

如果你需要处理扫描版 PDF，可在 [config/default_config.json](config/default_config.json) 中设置 `tesseract_cmd`，并确认 `ocr_languages` 对应的语言包已经安装。

4. 启动程序

```powershell
D:\chapter1\.venv\Scripts\python.exe D:\chapter1\main.py
```

首次启动会先执行部署自检；如果环境未就绪，会自动进入部署向导。

## 离线模型与 OCR 说明

### 离线模型

- 模型目录、最低必需文件和放置方式见 [models/README.md](models/README.md)
- 程序使用 `local_files_only=True` 强制本地加载，不会联网回退
- 启动自检会区分“模型目录存在”“模型可以试加载”“模型热身和性能是否可接受”

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
|-- main.py
|-- README.md
|-- config/
|-- core/
|-- docs/
|-- importers/
|-- models/
|-- scripts/
|-- tests/
|   |-- test_smoke.py
|   `-- test_gui.py
`-- ui/
```

## 开发与测试

语法检查：

```powershell
D:\chapter1\.venv\Scripts\python.exe -m py_compile D:\chapter1\main.py D:\chapter1\core\config.py D:\chapter1\core\algorithms.py D:\chapter1\core\nlp_thread.py D:\chapter1\core\result_formatter.py D:\chapter1\core\startup_checks.py D:\chapter1\core\text_cleaner.py D:\chapter1\core\import_preview.py D:\chapter1\importers\document_loader.py D:\chapter1\ui\main_window.py D:\chapter1\ui\startup_wizard.py
```

测试运行：

```powershell
D:\chapter1\.venv\Scripts\python.exe -m unittest D:\chapter1\tests\test_smoke.py D:\chapter1\tests\test_gui.py
```

当前仓库包含 smoke tests 与 GUI 交互测试，适合在改动导入、分析流程、部署自检和主界面交互后做回归验证。

## 文档入口

- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 模型目录说明：[models/README.md](models/README.md)
- Tesseract 安装说明：[docs/TESSERACT_SETUP.md](docs/TESSERACT_SETUP.md)
- 打包脚本：[scripts/build.ps1](scripts/build.ps1)
