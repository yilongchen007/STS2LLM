# STS2LLM

`STS2LLM` is a small Python agent that uses the OpenAI Responses API to control Slay the Spire 2 through the local `STS2MCP` mod.

## Why this repo talks to the raw STS2 API

The current `STS2MCP` Python bridge runs as a local `stdio` MCP server. OpenAI's built-in remote MCP tool is intended for HTTP-based MCP servers, so the most reliable first version is:

1. `Slay the Spire 2` runs the `STS2MCP` mod.
2. The mod exposes `http://127.0.0.1:15526/api/v1/singleplayer`.
3. `STS2LLM` exposes those game actions to the model as local function tools.

This keeps the tool surface aligned with `STS2MCP` while staying compatible with the OpenAI API.

Sources:
- OpenAI models and Responses API overview: https://developers.openai.com/api/docs/models
- OpenAI tools guidance: https://platform.openai.com/docs/guides/tools

## Features

- Uses the OpenAI Responses API tool loop
- Talks to the local `STS2MCP` HTTP API
- Prefers `card_instance_id` over unstable card indices
- Supports exact local reference lookup for `card`, `enemy`, and `relic`
- Supports common singleplayer actions:
  - reading game state
  - playing cards
  - ending turn
  - map navigation
  - event choices
  - reward handling
  - deck selection screens
  - relic selection
  - shop purchase
  - potion use

## Project Layout

- `src/sts2llm/`
  - runtime agent, local tool definitions, API client, prompt, config, and CLI
- `src/sts2llm/content/`
  - offline content pipeline modules: crawlers, unpack helpers, and pack builders
- `data/raw/`
  - raw crawl and unpack artifacts
- `data/processed/wiki_gg/`
  - processed lookup packs consumed by the local reference layer

## Reference Data Layer

The repo currently maintains three exact-reference packs for runtime lookup:

- `data/processed/wiki_gg/card_pack.json`
  - top key: `cards`
  - fields: `id`, `name`, `color`, `type`, `rarity`, `content`
  - optional fields when matched from `data/raw/winning_rate.csv`: `internal_name`, `name_zh`, `win_rate`, `pick_rate`, `skip_rate`
  - optional override fields when matched from `data/raw/xhh/ironclad_latest.csv`: latest `name_zh`, `win_rate`, `pick_rate`, `skip_rate` for Ironclad cards
  - optional curated field when matched from `data/manual/card_annotations.json`: `pick_advice_zh`
  - `id` uses exact runtime card ids such as `BASH` and `DEFEND_IRONCLAD`
- `data/processed/wiki_gg/enemy_pack.json`
  - top key: `enemies`
  - fields: `id`, `name`, `contexts`, `content`
  - optional curated field when matched from `data/manual/enemy_annotations.json`: `enemy_advice_zh`
  - `id` uses exact base monster ids such as `TOADPOLE` and `TEST_SUBJECT`
  - live combat `entity_id` values such as `TOADPOLE_1` are normalized back to base `monster_id`
- `data/processed/wiki_gg/relic_pack.json`
  - top key: `relics`
  - fields: `id`, `name`, `rarity`, `character`, `content`
  - `id` uses exact runtime relic ids such as `BURNING_BLOOD`

Additional text-only packs are also generated for keyword and status reference:

- `data/processed/wiki_gg/keyword_pack.json`
- `data/processed/wiki_gg/buffs_pack.json`
- `data/processed/wiki_gg/debuffs_pack.json`

The local exact lookup tools exposed to the model are:

- `get_card_info(card_id)`
- `get_enemy_info(entity_id | monster_id)`
- `get_relic_info(relic_id)`

## Strategy Layers

The agent prompt uses three internal strategy layers:

- `global_strategy`
  - fields: `build_rule`, `path_rule`, `boss_rule`
  - `path_rule` should be based on the visible full map structure when on the map screen, not only the immediate next choice
  - `path_rule` should connect route preference to current HP, deck strength, relics, and boss prep needs
  - `boss_rule` should use `map.boss.encounter_id` / `encounter_name` as the exact current-act boss when those fields are present, instead of reasoning over the whole act roster
  - when newly created or refreshed, it should be emitted through one event-style `Strategy:` line rather than repeated every turn
  - it should not be re-emitted just because combat started; only refresh it when its own inputs changed
  - refreshed when cards or relics materially change
- `combat_strategy`
  - fields: `target_rule`, `pace_rule`
  - `target_rule` only answers which enemy should receive priority damage right now
  - `pace_rule` only answers whether the current turn should lean offensive or defensive, and why
  - refreshed when combat starts or when the enemy side materially changes
- `stage_strategy`
  - field: `steps`
  - `stage_strategy` must always be emitted as `{"steps":[...]}`
  - `steps` is an ordered short list of next actions for the current observation window
  - refreshed when a new decision stage begins or the current stage is invalidated by material change

## Setup

1. Make sure the `STS2MCP` mod is installed and enabled in the game.
2. Make sure the game is running and the local API is available on `localhost:15526`.
3. Create an `.env` file:

```bash
cp .env.example .env
```

4. Fill in `OPENAI_API_KEY`.
5. Install dependencies:

```bash
uv sync
```

## Usage

One-shot prompt:

```bash
uv run sts2llm run "读取当前状态并帮我做出本回合最优动作"
```

Interactive chat:

```bash
uv run sts2llm chat
```

Raw guide crawl for local data collection:

```bash
uv run sts2llm crawl-games-gg-guides
```

The default crawl target is `games.gg` English guides for `slay-the-spire-2`. Output is written to:

- `data/raw/games_gg/slay-the-spire-2/manifest.json`
- `data/raw/games_gg/slay-the-spire-2/guides.jsonl`
- `data/raw/games_gg/slay-the-spire-2/articles/*.json`
- `data/raw/games_gg/slay-the-spire-2/html/*.html`
- `data/raw/games_gg/slay-the-spire-2/sitemaps/*.xml`

Useful flags:

```bash
uv run sts2llm crawl-games-gg-guides --limit 5
uv run sts2llm crawl-games-gg-guides --skip-existing
uv run sts2llm crawl-games-gg-guides --output-dir data/raw/games_gg
```

Raw wiki.gg crawl for hub pages plus linked pages:

```bash
uv run sts2llm crawl-wiki-gg "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2%3AMain"
```

The default wiki crawl follows links to depth `1` and saves up to `20` pages under:

- `data/raw/wiki_gg/<wiki-host>/<start-page>/manifest.json`
- `data/raw/wiki_gg/<wiki-host>/<start-page>/pages.jsonl`
- `data/raw/wiki_gg/<wiki-host>/<start-page>/articles/*.json`
- `data/raw/wiki_gg/<wiki-host>/<start-page>/html/*.html`

Useful flags:

```bash
uv run sts2llm crawl-wiki-gg "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2%3AMain" --max-depth 1 --max-pages 12
uv run sts2llm crawl-wiki-gg "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2%3AMain" --skip-existing
uv run sts2llm crawl-wiki-gg "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2%3AMain" --headless
```

Targeted wiki.gg crawl for act encounter pages already linked from a saved hub crawl:

```bash
uv run sts2llm crawl-wiki-gg-act-enemies
```

By default this reads the previously saved main crawl under
`data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Main`,
extracts links from the `Monsters`, `Elites`, and `Bosses` sections of
`Overgrowth`, `Underdocks`, `Hive`, and `Glory`, then saves the fetched pages under:

- `data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies/manifest.json`
- `data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies/pages.jsonl`
- `data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies/articles/*.json`
- `data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies/html/*.html`

Useful flags:

```bash
uv run sts2llm crawl-wiki-gg-act-enemies --sections Monsters Elites
uv run sts2llm crawl-wiki-gg-act-enemies --acts Overgrowth Hive
uv run sts2llm crawl-wiki-gg-act-enemies --skip-existing
```

Build a simplified enemy pack JSON from the saved wiki.gg enemy crawl:

```bash
uv run sts2llm build-enemy-pack
```

By default this reads
`data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies/pages.jsonl`
plus curated enemy annotations from `data/manual/enemy_annotations.json`,
and writes:

- `data/processed/wiki_gg/enemy_pack.json`

Build simplified card, relic, keyword, buff, and debuff packs from the saved wiki.gg main crawl:

```bash
uv run sts2llm build-reference-packs
```

By default this reads
`data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Main`
plus card pick-rate data from `data/raw/winning_rate.csv`,
plus optional latest Ironclad overrides from `data/raw/xhh/ironclad_latest.csv`,
plus curated card annotations from `data/manual/card_annotations.json`,
and writes:

- `data/processed/wiki_gg/card_pack.json`
- `data/processed/wiki_gg/relic_pack.json`
- `data/processed/wiki_gg/keyword_pack.json`
- `data/processed/wiki_gg/buffs_pack.json`
- `data/processed/wiki_gg/debuffs_pack.json`

Examples:

```bash
uv run sts2llm run "先读取当前状态，然后如果在事件界面就选择最稳的选项"
uv run sts2llm run "如果在地图界面，选择一条偏保守的路线"
uv run sts2llm run "如果在战斗中，优先使用 instance_id 出牌并结束回合"
```

## Terminal UX

The `chat` command is designed to feel closer to an agent terminal:

- prints your prompt as `You`
- prints model text as `Assistant`
- in `test` mode, prints every tool call as `Tool`
- in `test` mode, prints tool results as `Tool Output`
- in `run` mode, hides tool activity and shows only assistant messages
- keeps conversation context between turns
- saves each session to `logs/session-YYYYMMDD-HHMMSS.jsonl`
- supports `/reset` and `/exit`

Examples:

```bash
uv run sts2llm chat
uv run sts2llm chat --mode run
uv run sts2llm chat --show-tool-output full
uv run sts2llm run "先读取状态再决定动作" --show-tool-output compact
```

Modes:

- `--mode test`: for debugging and prompt tuning. Shows tool calls and tool outputs in the terminal.
- `--mode run`: for normal play. Hides tool calls and tool outputs in the terminal, but still shows assistant messages. Full details are still saved to the session log.

## Control discipline

The agent is instructed to identify the stopping boundary before acting.

Examples:

- "只读取当前状态并总结" -> inspect only, no actions
- "只选地图下一步，选完就停" -> choose exactly one node, then stop
- "打完这一回合就停，不要进下一回合" -> act within the current turn only
- "看到选牌界面先不要确认" -> select if requested, but stop before confirmation

If the instruction is ambiguous and acting could overshoot the requested step, the agent should ask instead of continuing.

### Output protocol

Per user request, the assistant should follow this shape:

- one `Boundary:` line before the first tool call
- then one `State:` line and one `Decision:` line at the start of a turn or phase
- only when a strategy layer is created or updated, emit one `Strategy:` line with compact JSON and only the changed layers
- on reward screens, do not use `proceed_to_map` until every reward item was explicitly handled
- during execution, use short `Action:` lines
- only use `State Update:` and `Decision Update:` when the plan genuinely needs to change
- after finishing, do not add a battle recap unless the user asked for one
- do not repeat `Boundary:` unless the user changed the task

Example:

```text
Boundary: 只打这一回合，回合结束后停止。
State: 当前是玩家回合，能量 2/3，对面总意图伤害 12。
Strategy: {"event":"init","updated_layers":["combat_strategy","stage_strategy"],"combat_strategy":{"target_rule":"先击杀 3 血小怪。","pace_rule":"这回合偏进攻，因为能低成本减少即时伤害。"},"stage_strategy":{"steps":["先用两张打击击杀 3 血小怪","再用剩余能量补防御","若敌人死亡后手牌/能量结构变化，重新观察"]}}
Decision: 先击杀 3 血小怪，再用防御降低剩余伤害。
Action: 防御(card_32)
Action: 防御(card_35)
Action: 打击(card_33) -> 小啃兽
Action: 结束回合
```

Only when needed:

```text
State Update: 抽到头槌，当前能量 1，敌人剩余 37/43。
Decision Update: 原计划改为先打头槌优化下回合，再结束回合。
```

## Tool round limit

Default `--max-rounds` is `40`. Increase it for long autonomous runs:

```bash
uv run sts2llm chat --max-rounds 80
```

## Notes

- This repo currently targets singleplayer only.
- `STS2MCP` card actions should use `card_instance_id` whenever the state provides it.
- If you later want a true remote MCP setup, add an HTTP MCP wrapper and swap the backend without changing the agent loop.
