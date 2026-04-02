# STS2LLM

Last updated: 2026-04-01

## 文档职责

- `PROJ.md`：只记录当前目标和最近改动
- `README.md`：保存长期说明，如目录结构、pack 结构、查询层设计、策略分层等

## 当前目标

以尽快让 agent 稳定通关为导向，优先采用低时间/低经费成本的 ad hoc 方法：保留本地可检索的 STS2 知识层与必要的工具约束，通过 prompt 和小步补丁修复高频失败模式，而不是优先投入训练或复杂通用架构。

## 变更记录

- 2026-04-01
  - 已从 `SYSTEM_PROMPT` 中移除 `BOSS_LOOKUP_MAPPING` 与 `BOSS_FALLBACK_ROSTER`，减少与代码层职责混杂
  - 已把 tool 参数解析错误、非法参数和动作执行异常统一转成结构化 `tool_output` 错误返回给模型，避免直接中断当前 turn
  - 已重构 `SYSTEM_PROMPT` 结构：改为分段式规则，并抽离 boss mapping / fallback roster 常量，减少重复与维护噪音
  - 已新增 `sts2llm web` 本地简易 Web UI，可查看 system prompt、输入 user prompt，并追踪 agent 的工具调用与输出
  - 已把 `winning_rate.csv` 与 `data/raw/xhh/ironclad_latest.csv` 接入 `card_pack.json` 生成流程，并补充 `win_rate` / `pick_rate` / `skip_rate`
  - 已新增 `data/manual/card_annotations.json`，为 `Ironclad` 卡牌补充 `pick_advice_zh`
  - 已新增 `data/manual/enemy_annotations.json`，为 `enemy_pack.json` 补充 `enemy_advice_zh`
  - 已把 `enemy` 注释接入构建流程，并在 CLI 中增加 `--enemy-annotations-path`
  - 已把 agent 的战术输出简化为 `target_rule` 与 `pace_rule`
  - 已把地图完整结构纳入 `path_rule`，并要求用 `map.nodes` 而不是只看 `next_options`
  - 已把 `map.boss.encounter_id` 接入长期策略，当前 Act Boss 可直接用于 `boss_rule`
  - 已把策略层改为事件式 `Strategy:` 输出，只在初始化或更新时输出结构化 JSON
  - 已加强约束：`stage_strategy` 固定为 `{\"steps\":[...]}` 结构，奖励界面必须显式处理奖励后才能 `proceed_to_map`
- 2026-03-28
  - 已把 `card_pack.json` 和 `enemy_pack.json` 的 `id` 切到运行时程序键
  - 已新增 `data/processed/wiki_gg/relic_pack.json`
  - 已给 agent 增加 `card` / `enemy` / `relic` 的精确查询工具
  - 已把三层策略定义写入 prompt：`global_strategy`、`combat_strategy`、`stage_strategy`
  - 已整理代码目录：根目录保留运行时与通用模块，`src/sts2llm/content/` 只放抓取、解包、pack 构建等内容处理模块
