# Conversation summary tokenizers

Both MIT-licensed artifacts are pinned by SHA-256 in `conversation_summary_runtime.py`.
They are loaded locally with the locked `tokenizers` dependency; no model weights or
network access are needed at runtime.

- `glm_5_3_flash.json`: [Z.ai GLM-5.3-Flash tokenizer](https://huggingface.co/zai-org/GLM-5.3-Flash/blob/46a050bec13002ad29ee795c16e61cf4fa3c4a9c/tokenizer.json), revision `46a050bec13002ad29ee795c16e61cf4fa3c4a9c`; see `GLM-LICENSE`.
- `deepseek_v4_1_flash.json`: [DeepSeek-V4.1-Flash tokenizer](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/314113f8a7dadb388215396ba5fbee2c610a04d6/tokenizer.json), revision `314113f8a7dadb388215396ba5fbee2c610a04d6`; see `DeepSeek-LICENSE`.
