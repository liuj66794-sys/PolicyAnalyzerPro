将离线模型放到以下目录：

- models/hfl/chinese-roberta-wwm-ext/

建议至少包含 SentenceTransformer / Transformers 所需的本地文件，例如：
- config.json
- tokenizer.json 或 vocab.txt
- model.safetensors 或 pytorch_model.bin
- modules.json
- sentence_bert_config.json

程序会以 `local_files_only=True` 强制本地加载，若目录缺失将不会联网回退。
