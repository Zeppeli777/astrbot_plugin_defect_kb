# 故障机器人知识库（astrbot_plugin_defect_kb）

杀戮尖塔「故障机器人（The Defect，社区昵称鸡煲）」人格知识库插件 for AstrBot。

纯 BM25 关键词检索，**不依赖任何 embedding 模型**：适合只会对话 + tool calling 的普通多模态 LLM API（OpenAI / Anthropic 协议均兼容）。

- 当前版本：v0.1.0
- 要求：AstrBot >= 4.17.0

## 工作方式

```
用户消息 ─→ identity.md + taboos.md 自动注入 system prompt（人设底线，永不丢失）
        └→ LLM 按需调用 defect_kb_search 工具
             └→ jieba 分词 + BM25 打分，返回 top-K 条目
                  └→ 模型按条目扮演/报数据
```

- **混合触发**：身份与禁忌每条消息强制注入；场景/卡牌/梗等长尾知识由模型通过工具按需检索
- **热更新**：`kb/` 目录下 md 文件保存即重建索引（mtime 检测），无需重启
- **官方数据**：卡牌/遗物/怪物/药水/关键词/状态/事件共 ~1300 条，来自 [nkhoit/spire-archive](https://github.com/nkhoit/spire-archive) 数据集 + 官方中文翻译
- **社区梗库**：B站（晓夫九/白夕seal/菜农来辣/破碎的星光brkstar 评论区）、贴吧杀戮尖塔吧、小黑盒社区抓取整理（宇宙冷漠、基米精神、攻哈、噶人……）
- **调用观测**：`debug_log` 开启时，每次检索的 query/命中条目/分数 + 最终 system prompt 全量记录到 `calls.log`

## 安装

放到 AstrBot 的 `data/plugins/` 目录下（或在 WebUI 插件市场从该 repo 安装），重启即可。首次启动自动把 `kb_seed/` 播种到 `data/plugin_data/astrbot_plugin_defect_kb/kb/`，之后直接编辑那边的数据文件即可（不会被插件更新覆盖）。

## 知识库结构（kb_seed/）

| 文件 | 内容 |
|---|---|
| identity.md / taboos.md | 身份锚点 + 禁忌（每条消息自动注入） |
| cards_sts1.md / cards_sts2.md | 塔1/塔2 全卡牌（76 + 88 条） |
| relics_sts1.md / relics_sts2.md | 全遗物（181 + 296 条） |
| monsters_sts1.md / monsters_sts2.md | 全怪物图鉴含招式伤害（68 + 111 条） |
| keywords.md / powers.md | 机制关键词（55）+ buff/debuff 状态（380） |
| events.md / potions.md | 事件（118）+ 药水（105） |
| orbs.md / game_concepts.md | 充能球机制 + 玩家高频概念（火堆/删卡/进阶/心脏前置…） |
| community_memes.md / sts2_glossary.md | 社区梗词典 + 塔二黑话 |
| style_lexicon.md / scenario_rules.md / templates.md | 说话风格 / 场景反应 / 台词模板 |

条目格式（BM25 友好：空行分隔、触发词开头、每条 1~3 行）：

```
[触发词: 爪 CLAW 爪爪]
爪(Claw)：1费攻击。造成3点伤害；本场战斗每打出一次，所有爪永久+2。CLAW IS LAW——爪教玩家不需要别的卡
```

## 配置项

| 键 | 说明 | 默认 |
|---|---|---|
| auto_inject | 自动注入身份锚点与禁忌 | true |
| max_inject_chars | 注入内容字符上限 | 1500 |
| inject_hint | 注入工具使用提示 | true |
| search_top_k | 检索默认返回条数 | 5 |
| debug_log | 记录检索与 system prompt 到 calls.log | true |
| kb_admin_only | 仅管理员可用 /dkb 写入指令 | true |

## 对话写入（/dkb 指令）

在聊天里直接教 bot（写入后热更新立即生效，默认仅管理员）：

```
/dkb 添加 打招呼 早上好 | 「[POWER ON] 早，塔批。自检通过……大概。」
/dkb 添加 scenario_rules 被问进度 | 汇报三层进度，语气丧但继续走
/dkb 查看 [文件名]      # 列出条目编号
/dkb 删除 <文件名> <编号>
/dkb 文件               # 列出全部知识库文件
```

条目内容即「遇到这类消息时 bot 的标准反应」，LLM 检索到后会照此扮演。

## 数据再生成

`raw/gen_kb.py` 可从 spire-archive 原始 JSON 重新生成全部数据类条目（升级游戏版本后同步用）：

```bash
# 下载 data/*.json 到 raw/ 后
python3 raw/gen_kb.py
```

## License

MIT
