# 架构说明

## 1. 设计目标

PolicyAnalyzerPro is an offline-first desktop analyzer for government, research, and intranet use cases. The current architecture is optimized around the goals below:

- Offline-first execution: local analysis remains the default path; online and hybrid routes are optional enhancements and must never break the offline workflow
- Windows 桌面环境中保持 UI 可响应，不把重计算压在界面线程
- 支持长文本的单篇分析、双篇比对和批量分析
- 支持 TXT、DOCX、PDF 和扫描版 PDF 的统一导入链路
- 在进入业务功能前先完成部署自检、模型试加载和性能基准判断
- 输出适合研究使用、归档打印和正式交付
- 利用 Python 3.13+ 运行时优化，提升性能和用户体验
- 增强安全性，提高系统稳定性和可靠性

## 2. 系统分层

当前实现可以按四层理解：

- **入口与启动层**：`main.py` ，负责 Qt 初始化、高分屏适配、全局异常捕获和启动前自检。
- **UI 与交互层**：`ui/main_window.py` 和 `ui/startup_wizard.py` ，负责主窗口、部署向导、导入预览、结果展示和导出。
- **Service and domain layer**: configuration, text cleaning, analysis algorithms, result formatting, startup diagnostics, mode routing, and import preview logic under `core/`.
- **Import and execution layer**: `importers/document_loader.py`, `core/analysis_router.py`, `core/nlp_thread.py`, and the skeleton packages under `core/online_llm/`, `core/hybrid_pipeline/`, and `core/policy_fetch/`.

这种分层的目标是把界面展示、分析逻辑、环境诊断和导入/OCR 隔离开，避免主窗口直接承担所有职责。

## 3. 关键运行链路

### 3.1 启动链路

1. `main.py` 在 `QApplication` 初始化前开启高分屏适配。
2. 注册全局异常钩子，避免桌面端崩溃后无提示退出。
3. 调用 `multiprocessing.freeze_support()` ，兼容 Windows 打包后的多进程启动。
4. 加载配置并执行启动自检。
5. 如果环境未就绪或检测到关键问题，先弹出部署向导；否则直接进入主窗口。
6. 初始化时预热模型，减少首次分析延迟。

### 3.2 导入链路

1. 用户在主界面选择 TXT、DOCX 或 PDF。
2. `DocumentLoader` 统一负责文本提取与清洗。
3. 对 PDF ，优先读取文字层；若文字层不可用且配置允许，则回退到 OCR。
4. OCR 支持页码范围选择，并根据文件信息、OCR 参数和页码范围做缓存命中判断。
5. 导入结果会同时进入编辑区和导入预览，方便用户在分析前复核标题区和正文前几段。
6. 增强输入验证，防止路径遍历攻击和处理过大的文件。

### 3.3 分析链路

1. The UI collects input text and the requested analysis mode.
2. `analysis_router` resolves the requested mode against config and capability state.
3. `NLPAnalysisThread` chooses offline, online, or hybrid execution; unavailable online or hybrid routes degrade back to offline.
4. Actual heavy analysis still runs inside `ProcessPoolExecutor(max_workers=1)` to keep the UI responsive.
5. Worker processes still inject offline environment variables and conservative `torch` thread settings.
6. Results now carry requested mode, executed mode, and fallback warnings before reaching `result_formatter`.
7. `policy_fetch` stays decoupled from the main analysis path and only exposes source status for future tasks.

### 3.4 部署诊断链路

1. `startup_checks.py` 生成结构化检查结果。
2. `startup_wizard.py` 负责展示检查详情、差异高亮和修复建议。
3. 检查结果可以导出为 Markdown、HTML、PDF，便于排障、交付和留档。

## 4. 核心模块职责

### `main.py`

- 应用入口
- 高分屏设置与全局异常捕获
- 启动前部署自检
- 主窗口与部署向导的调度入口
- 应用图标设置

### `core/config.py`

- 定义默认配置和 JSON 覆盖逻辑
- 管理模型目录、字体、词典、OCR 参数、阈值和离线环境变量
- 提供资源路径解析与运行环境注入工具

### `core/startup_checks.py`

- 负责部署诊断的核心逻辑
- 检查配置、依赖、模型目录、模型试加载、性能基准、OCR 管线、语言包、字体和词典
- 生成差异摘要与 Markdown、HTML、PDF 诊断报告

### `core/text_cleaner.py`

- 清理政务新闻通稿噪音、页脚和非正文信息
- 保留段落和句子结构，服务于后续分析与比对

### `core/algorithms.py`

- **单篇分析**：元信息、新提法、核心议题、摘要页、文本结构分析
- **双篇比对**：措辞演变、删减监测、新增议题、保留议题、强化议题
- **批量分析**：聚合多份文档的议题、新提法和汇总指标
- 按需懒加载本地 `SentenceTransformer` 模型
- 模型预热机制，减少首次分析延迟

### `core/analysis_router.py`
- Unified entry for `offline / online / hybrid` route decisions
- Decides when to stay offline and when to degrade back from unavailable optional routes
- Produces route metadata and fallback messages for UI and export layers


### `core/online_llm/`
- Skeleton package for online LLM invocation and normalized request / response contracts
- Current phase only exposes status and error wrapping; it does not implement real provider details


### `core/hybrid_pipeline/`
- Skeleton package for local-preprocess plus online-enhancement orchestration
- Current phase only exposes status, entry points, and fallback boundaries; it does not implement full segment selection


### `core/policy_fetch/`
- Skeleton package for policy collection, status reading, and result pulling
- Kept decoupled from the main analysis router so policy fetching never blocks startup or analysis


### `core/nlp_thread.py`

- 把 UI 线程和模型执行线程隔离开
- 使用 `QThread + ProcessPoolExecutor(max_workers=1)` 实现保守调度
- 负责进度、结果、错误和取消信号的桥接
- 工作进程初始化时预热分析器，提高分析速度

### `core/import_preview.py`

- 构建导入预览内容、状态条、轻提示 badge 和说明文本
- 支持将导入说明插入分析结果或复制到剪贴板

### `core/result_formatter.py`

- 将单篇、双篇、批量分析结果统一格式化为 Markdown、HTML、JSON
- 将报告输出组织为封面、摘要、排行、证据等可读结构
- 支持将导入提示说明附加到导出结果中
- 支持新的文本结构分析结果展示

### `importers/document_loader.py`

- 统一处理 TXT、DOCX、PDF 导入
- 支持 PDF 文字层清洗、封面标题修复、扫描版 OCR 回退
- 支持 OCR 页码范围选择和 OCR 结果缓存
- 生成导入状态，用于预览页和主窗口状态展示
- 增强输入验证，防止路径遍历攻击和处理过大的文件

### `ui/main_window.py`

- 主界面与主交互入口
- 管理单篇分析、双篇比对、批量分析
- 展示导入预览、分析结果、环境自检入口和导出操作
- 改进 UI/UX 体验，增加窗口图标和布局优化

### `ui/startup_wizard.py`

- 展示部署检查结果和变化差异
- 提供重检、打开目录、导出报告等操作
- 在关键问题未修复时做进入软件前的二次确认

## 5. 关键工程约束
### 5.1 Offline-First
### 5.1 彻底离线
- The default workflow stays offline and continues to load models only from local directories
- Worker processes still force `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; unavailable optional routes must degrade back to offline
- 子进程统一设置 `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`
- `SentenceTransformer` 使用 `local_files_only=True`

### 5.2 Windows 多进程安全

- 启动入口调用 `multiprocessing.freeze_support()`
- 多进程任务使用 `spawn` 语义与保守的 `max_workers=1`
- 子进程中限制 `torch.set_num_threads(2)`，避免桌面假死

### 5.3 OCR 稳定性

- PDF 优先走文字层提取，降低 OCR 成本和误识别风险
- 扫描版 PDF 才进入 OCR 路径
- OCR 支持页码范围和缓存，避免重复识别整份文档
- 自检会单独诊断 `tesseract.exe`、`TESSDATA_PREFIX` 和语言包位置

### 5.4 报告与诊断可交付

- 分析结果导出支持 Markdown、HTML、JSON
- 部署诊断导出支持 Markdown、HTML、PDF
- HTML 输出包含打印型结构，适合归档和正式交付

### 5.5 安全性

- 增强输入验证，防止路径遍历攻击
- 设置文件大小限制，防止处理过大的文件
- 改进错误处理机制，提供更清晰的错误信息
- 确保模型和缓存目录权限正确，避免权限错误

## 6. 性能优化

- **模型加载优化**：利用 Python 3.13+ 运行时优化，减少模型加载时间
- **预热机制**：在程序启动和工作进程初始化时预热模型，减少首次分析延迟
- **多进程管理**：优化进程池配置，提高并发处理能力
- **内存使用**：减少不必要的内存分配，提高内存使用效率

## 7. 测试与验证策略

当前仓库的验证分两类：

- `tests/test_smoke.py`：覆盖配置加载、文本清洗、导入、OCR 回退、结果格式化、启动检查、批量分析和文本结构分析等核心流程
- `tests/test_gui.py`：覆盖主窗口关键交互，包括启动分析、批量导入、批量运行、预览 badge 交互等 GUI 流程

这两类测试的目的不同：smoke tests 保证核心能力不退化，GUI 测试保证桌面交互链路不被改坏。

## 8. 当前边界与扩展点

当前架构已经能支撑离线桌面交付，但仍保留了明确边界：

- 项目不会自动下载模型，模型目录需部署方提前准备
- OCR 依赖本地 Tesseract 与语言包，项目只做检查和接入，不自动托管安装
- 现阶段分析重点仍是政务长文本，不是通用 NLP 平台

后续如果继续扩展，建议优先从这几个方向入手：

- 增加更多文档格式或扫描件质量增强策略
- 增加更细的结果筛选、导出模板和批量报告汇总页
- 将部署诊断和分析结果进一步标准化，方便交付流程复用
- 利用 Python 3.13+ 运行时优化，进一步优化性能和用户体验
- 增强安全性，提高系统稳定性和可靠性
