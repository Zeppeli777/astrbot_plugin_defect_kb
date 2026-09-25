"""杀戮尖塔「故障机器人(The Defect)」人格知识库插件。

纯 BM25 关键词检索，不依赖 embedding：
- identity.md / taboos.md 每条消息自动注入 system prompt（人设底线）
- 其余条目由 LLM 通过 defect_kb_search 工具按需检索
- kb 目录下的 md 文件改动后自动重建索引（按 mtime 判断），无需重启
"""

import re
from datetime import datetime
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

_TOKEN_PATTERN = re.compile(r"\w", re.UNICODE)

# 调用记录文件路径，initialize() 时赋值；None = 未初始化不记录
_log_path: Path | None = None


def _log(msg: str) -> None:
    """追加调用记录；超过 4MB 自动清空重置。"""
    if _log_path is None:
        return
    try:
        if _log_path.exists() and _log_path.stat().st_size > 4_000_000:
            _log_path.write_text("", encoding="utf-8")
        with _log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}\n\n")
    except OSError:
        pass

# 精简中文停用词：只滤高频虚词，实词全部保留给 BM25
_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "看", "好", "自己", "这", "那", "这个", "那个", "什么", "怎么", "为什么",
    "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "得", "地", "他", "她", "它",
    "我们", "你们", "他们", "们", "个", "中", "大", "小", "为", "以", "及",
    "或", "与", "被", "把", "让", "用", "从", "对", "但", "而", "还", "又",
    "再", "才", "只", "就是", "还是", "可以", "不是", "没有", "如果",
    "因为", "所以", "但是", "然后", "或者", "一下", "一下子", "的话",
    "the", "a", "an", "is", "are", "of", "to", "in", "on", "and", "or",
}


def _tokenize(text: str) -> list[str]:
    tokens = []
    for tok in jieba.cut(text or ""):
        tok = tok.strip().lower()
        if not tok or tok in _STOPWORDS:
            continue
        if not _TOKEN_PATTERN.search(tok):
            continue
        tokens.append(tok)
    return tokens


class KBIndex:
    """BM25 索引：空行分条目，按 mtime 热更新，条目来自 kb 目录下所有 .md。"""

    def __init__(self, kb_dir: Path) -> None:
        self.kb_dir = kb_dir
        self.docs: list[dict] = []
        self._bm25: BM25Okapi | None = None
        self._corpus: list[list[str]] = []
        self._mtimes: dict[str, float] = {}

    def refresh_if_needed(self) -> None:
        mtimes: dict[str, float] = {}
        if self.kb_dir.exists():
            for fp in sorted(self.kb_dir.glob("*.md")):
                try:
                    mtimes[fp.name] = fp.stat().st_mtime
                except OSError:
                    continue
        if mtimes != self._mtimes or self._bm25 is None:
            self._mtimes = mtimes
            self._rebuild()

    def _rebuild(self) -> None:
        docs: list[dict] = []
        for fp in sorted(self.kb_dir.glob("*.md")):
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logger.warning(f"[defect_kb] 读取失败 {fp.name}: {e}")
                continue
            for block in self._split_blocks(text):
                docs.append({"source": fp.name, "text": block})
        self.docs = docs
        self._corpus = [_tokenize(d["text"]) for d in docs]
        self._bm25 = BM25Okapi(self._corpus) if docs else None
        logger.info(
            f"[defect_kb] BM25 索引已构建: {len(docs)} 条条目, 来源 {len(self._mtimes)} 个文件"
        )

    @staticmethod
    def _split_blocks(text: str) -> list[str]:
        """连续非空行聚合成一个条目；# 开头的 markdown 标题行不入索引。"""
        blocks: list[str] = []
        cur: list[str] = []
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if line.strip():
                cur.append(line.strip())
            elif cur:
                blocks.append("\n".join(cur))
                cur = []
        if cur:
            blocks.append("\n".join(cur))
        return blocks

    def read_file(self, name: str) -> str:
        fp = self.kb_dir / name
        if not fp.exists():
            return ""
        try:
            return fp.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return ""

    def search(self, query: str, top_k: int) -> list[dict]:
        self.refresh_if_needed()
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: list[dict] = []
        for idx, score in ranked:
            if float(score) <= 0 or len(results) >= top_k:
                break
            d = self.docs[idx]
            results.append(
                {"source": d["source"], "text": d["text"], "score": float(score)}
            )
        return results


@register(
    "astrbot_plugin_defect_kb",
    "zeppeli",
    "杀戮尖塔故障机器人人格知识库（纯BM25检索，无需embedding）",
    "0.1.0",
)
class FaultBotKBPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.index: KBIndex | None = None

    async def initialize(self):
        global _log_path
        data_dir = StarTools.get_data_dir("astrbot_plugin_defect_kb")
        _log_path = data_dir / "calls.log"
        kb_dir = data_dir / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)
        if not any(kb_dir.glob("*.md")):
            seed_dir = Path(__file__).parent / "kb_seed"
            if seed_dir.exists():
                for fp in sorted(seed_dir.glob("*.md")):
                    (kb_dir / fp.name).write_text(
                        fp.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                logger.info(f"[defect_kb] 已从 kb_seed 播种默认知识库到 {kb_dir}")
        self.index = KBIndex(kb_dir)
        self.index.refresh_if_needed()
        logger.info(f"[defect_kb] 插件已初始化，知识库目录: {kb_dir}")

    async def terminate(self):
        self.index = None

    @filter.on_llm_request()
    async def inject_persona(self, event: AstrMessageEvent, request):
        """每条消息把身份锚点与禁忌注入 system prompt。"""
        if not self.config.get("auto_inject", True) or not self.index:
            return
        identity = self.index.read_file("identity.md")
        taboos = self.index.read_file("taboos.md")
        parts = []
        if identity:
            parts.append(f"【身份锚点（必须遵守）】\n{identity}")
        if taboos:
            parts.append(f"【禁忌（绝对不能违反）】\n{taboos}")
        if self.config.get("inject_hint", True):
            parts.append(
                "【检索工具使用规则】涉及说话风格、游戏梗、卡牌属性、充能球机制、"
                "对具体场景的反应时，先调用 defect_kb_search 工具（query 用 2~6 个短关键词），"
                "并严格按返回条目的方式说话；检索不到再用贴近故障机器人口吻的话自由发挥。"
            )
        block = "\n\n".join(parts)
        try:
            max_chars = int(self.config.get("max_inject_chars", 1500))
        except (TypeError, ValueError):
            max_chars = 1500
        if len(block) > max_chars:
            block = block[:max_chars]
        if block:
            request.system_prompt = (request.system_prompt or "") + "\n\n" + block
        if self.config.get("debug_log", True):
            try:
                umo = event.unified_msg_origin
            except Exception:
                umo = "?"
            _log(
                f"=== LLM请求 | 会话: {umo} | 用户消息: {getattr(request, 'prompt', '')[:60]}\n"
                f"[最终 system_prompt（含人格+本插件注入）]\n{request.system_prompt}"
            )

    @filter.llm_tool(name="defect_kb_search")
    async def kb_search(self, event: AstrMessageEvent, query: str, top_k: int = 5):
        """在故障机器人(The Defect)的人格知识库中检索条目。

        涉及说话风格、游戏梗、卡牌属性、充能球机制、场景反应时调用。
        query 必须是 2~6 个短关键词，不要输入长句。

        Args:
            query(string): 短关键词，如「充能球 焦点」「闪电 卡牌」「被夸 反应」
            top_k(number): 返回条目数，1~10，默认 5
        """
        if not self.index:
            return "知识库未初始化。"
        query = (query or "").strip()
        if not query:
            return "query 不能为空。"
        try:
            k = int(top_k)
        except (TypeError, ValueError):
            k = 5
        k = max(1, min(k, 10))
        results = self.index.search(query, k)
        if self.config.get("debug_log", True):
            lines = [f"检索 | query={query!r} top_k={k}"]
            if not results:
                lines.append("  结果: 无命中")
            for i, r in enumerate(results, 1):
                lines.append(f"  [{i}] {r['source']} 分数{r['score']:.1f} | {r['text'][:80]}")
            _log("\n".join(lines))
        if not results:
            return "知识库中没有匹配条目。请换更短、更核心的关键词再试一次。"
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[{i}] 来源:{r['source']} 相关度:{r['score']:.1f}\n{r['text']}"
            )
        return "\n\n".join(parts)
