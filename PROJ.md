# STS2LLM

Last updated: 2026-03-28

## 文档职责

- `PROJ.md`：只记录当前目标和最近改动
- `README.md`：保存长期说明，如目录结构、pack 结构、查询层设计、策略分层等

## 当前目标

构建一套本地可检索的 STS2 数据库/知识层，供 agent 离线查询，不让 agent 在运行时实时抓网页。

## 变更记录

- 2026-03-28
  - 已把 `card_pack.json` 和 `enemy_pack.json` 的 `id` 切到运行时程序键
  - 已新增 `data/processed/wiki_gg/relic_pack.json`
  - 已给 agent 增加 `card` / `enemy` / `relic` 的精确查询工具
  - 已把三层策略定义写入 prompt：`global_strategy`、`combat_strategy`、`stage_strategy`
  - 已整理代码目录：根目录保留运行时与通用模块，`src/sts2llm/content/` 只放抓取、解包、pack 构建等内容处理模块
