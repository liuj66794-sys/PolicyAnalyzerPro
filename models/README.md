# 模型管理指南

## 模型目录结构

将离线模型放到以下目录：

```
models/hfl/chinese-roberta-wwm-ext/
```

## 必需文件

确保包含以下文件以支持 SentenceTransformer / Transformers 本地加载：

- `config.json` - 模型配置文件
- `tokenizer.json` 或 `vocab.txt` - 分词器配置
- `model.safetensors` 或 `pytorch_model.bin` - 模型权重
- `modules.json` - SentenceTransformer 模块配置
- `sentence_bert_config.json` - SentenceBERT 配置

## 模型获取方法

### 方法 1：从 Hugging Face 下载

1. 访问 [hfl/chinese-roberta-wwm-ext](https://huggingface.co/hfl/chinese-roberta-wwm-ext)
2. 点击 "Files and versions"
3. 下载上述必需文件到 `models/hfl/chinese-roberta-wwm-ext/` 目录

### 方法 2：使用 SentenceTransformer 缓存

1. 在有网络的环境中运行：
   ```python
   from sentence_transformers import SentenceTransformer
   model = SentenceTransformer('hfl/chinese-roberta-wwm-ext')
   print(model.cache_folder)
   ```
2. 复制缓存目录中的模型文件到 `models/hfl/chinese-roberta-wwm-ext/` 目录

## 验证模型完整性

程序启动时会执行以下检查：
1. 模型目录存在性检查
2. 模型文件完整性检查
3. 模型试加载检查
4. 模型性能基准测试

## Python 3.13 兼容性

- 确保使用兼容 Python 3.13 的 SentenceTransformer 和 Transformers 版本
- 建议使用最新版本的依赖包以获得最佳性能

## 离线加载机制

程序会以 `local_files_only=True` 强制本地加载，若目录缺失或文件不完整将不会联网回退，而是在启动自检时报告错误。

## 性能优化

- 模型文件建议使用 `model.safetensors` 格式，加载速度更快
- 确保模型目录权限正确，避免加载时出现权限错误
- 对于大型模型，建议使用 SSD 存储以提高加载速度
