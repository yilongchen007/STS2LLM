# STS2LLM

Last updated: 2026-03-27

## 当前目标

构建一套本地可检索的 STS2 数据库/知识层，供 agent 离线查询，不让 agent 在运行时实时抓网页。

## 当前数据源

- `games.gg` 攻略 raw data 已抓取
- `wiki.gg` 主入口一层页面已抓取
- `wiki.gg` 四个 act 的 `Monsters` / `Elites` / `Bosses` 二层敌人页已定向抓取

## 当前产物

- `data/raw/games_gg/...`
- `data/raw/wiki_gg/...`
- `data/processed/wiki_gg/enemy_pack.json`
- `data/processed/wiki_gg/card_pack.json`
- `data/processed/wiki_gg/keyword_pack.json`
- `data/processed/wiki_gg/buffs_pack.json`
- `data/processed/wiki_gg/debuffs_pack.json`

## Pack 设计

- `enemy_pack.json`
  - 字段：`id`, `name`, `contexts`, `content`
  - 群怪页按单怪切开
- `card_pack.json`
  - 字段：`id`, `name`, `color`, `type`, `rarity`, `content`
- `keyword_pack.json`
  - 字段：`id`, `name`, `content`
- `buffs_pack.json`
  - 字段：`id`, `name`, `content`
- `debuffs_pack.json`
  - 字段：`id`, `name`, `content`

## 关键结论

- 运行时工具返回是中英混合：
  - 英文：`id`, `type`, `target_type`, `unplayable_reason` 等程序键
  - 中文：`name`, `description` 等本地化展示文本
- 这些中文不是 MCP 自己翻译的，而是游戏当前语言直接提供的本地化文本
- `entity_id` 这类值由 MCP 基于游戏内部怪物 ID 派生生成

## 当前判断

- 不能用运行时 `name` 直接查英文 pack
- 后续需要一层 `runtime_id -> canonical_name/pack_id` 的映射
- 模糊匹配只能做 fallback，不能做主逻辑

## 下一步优先级

1. 解包/扫描游戏资源，拿更完整的运行时键列表
2. 构建 `runtime_registry` 或 `runtime_mapping`
3. 给 agent 增加精确联查层，而不是直接全文搜索
