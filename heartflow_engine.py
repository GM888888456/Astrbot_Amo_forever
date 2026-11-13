"""
心流插件 - 智能群聊主动回复系统 v4.27+
支持动态阈值 / 评分模式 / 沉浸模式 / 防抖 / 群聊独立配置
评分规则支持可视化配置（低分/高分情况分维度填写）
*注：已移除大模型上下文注入，完全依赖 AstrBot 原生对话流*
"""

import json
import random
import re
import time
import datetime
import traceback
import threading
import asyncio
from collections import deque
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, field

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Plain, At, Reply
from astrbot.api.provider import LLMResponse

# ============================================================
# 正则
# ============================================================
RE_CODE_BLOCK = re.compile(
    r"^(?:```(?:json)?|~~~(?:json)?|`{3,}(?:json)?)\s*\n?(.*?)\n?\s*(?:```|~~~|`{3,})$",
    re.DOTALL | re.IGNORECASE,
)
RE_BRACE = re.compile(r"\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}", re.DOTALL)
RE_ALL_BRACES = re.compile(r"\{.*\}", re.DOTALL)
RE_XML_TAG = re.compile(r"<[^>]+>")
RE_URL = re.compile(r"https?://\S+")

# ============================================================
# 评分常量
# ============================================================
SCORE_MIN = 1.0
SCORE_MAX = 10.0
SCORE_DEFAULT = 5.0

# ============================================================
# 内置默认维度规则
# ============================================================
BUILTIN_RULES: Dict[str, Dict[str, str]] = {
    "relevance": {
        "dimension_display": "内容相关度",
        "low_score_desc": "表情包、语气词、哈哈、嗯、完全无关的私人话题、群内专属梗",
        "high_score_desc": "涉及机器人能回答的话题、提问句、有信息价值",
    },
    "willingness": {
        "dimension_display": "回复意愿",
        "low_score_desc": "负面情绪宣泄、两人私密对话、机器人刚回复过",
        "high_score_desc": "消息有趣或有深度、求助类、机器人较久未回复",
    },
    "social": {
        "dimension_display": "社交适宜性",
        "low_score_desc": "严肃讨论、管理员发言、两人正在对话强行插入",
        "high_score_desc": "氛围活跃多人参与、对群体说的、能活跃气氛",
    },
    "timing": {
        "dimension_display": "时机恰当性",
        "low_score_desc": "距上次回复不足1分钟、发送者可能还有后续、多人快速聊天",
        "high_score_desc": "距上次已过3分钟以上、消息刚发出、长时间无人回复",
    },
    "continuity": {
        "dimension_display": "对话连贯性",
        "low_score_desc": "突然转换话题、已收尾的对话、明显是对其他群友回复",
        "high_score_desc": "对机器人回复的回应/追问/反驳、延续机器人话题、提及机器人说过的内容",
    },
}

# ============================================================
# 基础提示词模板
# ============================================================
# 群友在聊、但没有点名机器人时，随机挑一个角度插话，避免每次都像在“回答问题”
INTERJECT_ANGLES: List[str] = [
    "顺着他们正在聊的事接一句",
    "接个梗或吐槽一下",
    "补一个自己的看法",
    "像随口问一句那样把话题接下去",
    "说说自己此刻的想法",
]

BASE_JUDGE_PROMPT = """你是群聊机器人决策系统，判断机器人是否应该回复消息。

## 机器人身份
机器人名字：{bot_name}
机器人别名：{bot_aliases}
如果当前消息包含这些名字或别名，说明群友是在叫机器人，不是叫其他群友；relevance、continuity 必须给高分。

## ⚠️ 最高优先级：关注机器人自己的发言
对话历史（contexts）中，role 为 assistant 的消息是【机器人自己】之前说的话，role 为 user 的消息是群友说的话（带 [昵称] 前缀）。
你必须按以下步骤思考：
1. 先回顾机器人最近说了什么（见下方"上次Bot回复"，以及对话历史中的 assistant 消息）
2. 判断当前消息是否与机器人的发言存在关联：追问、回应、赞同、反驳、补充、顺着话题继续
3. 如果当前消息是在回应机器人说过的话，continuity 必须给高分

## 🧠 打分之前先走一遍逻辑推理（按顺序想清楚，再打分）
**第 1 步 · 还原现场**：读 dialogue 历史（contexts），找到最近的对话关系。
- role 为 assistant 的是【机器人自己】说过的话，带 [昵称] 的是群友。
- 看最近 3-5 条：谁在回答谁？有没有人的问题还悬着？现在这条在接谁的话？

**第 2 步 · 判断这条消息在对谁说（target）**：
- `bot`：消息里出现机器人名字/别名、@机器人、引用机器人上一条，才算在对机器人说。
  **单独一个“你 / 你呢 / 你pr好了吗”不算**——群聊里“你”大多在问别人。
- `other`：@别人、引用/回复别人的消息、叫了别的群友名字、两个人一问一答；
  或者**上一条明确 @ 了某个群友 / 回复了某个群友，这条没有新的 @/引用/名字**——那就继续算那个群友。
- `all`：抛给全群的问题、分享、感叹、群通知，没有特定对象。
- `unknown`：信息不足，看不出来。

对话历史每条都带 `[HH:MM]` 时间；群友消息后面的 `→@xxx` 表示这条 @ 了谁，
`→回复xxx` 表示这条在回复谁。判断 target 时优先看这两个标记，不要只看“你”。

**时间规则**：如果“上次Bot回复”已经超过 3 分钟，当前消息**不要**当成在接机器人的话；
超过 5 分钟只当背景。不要因为机器人十几分钟前说过一句“我去翻代码”，
就把一句“你pr好了吗”认成在追问机器人。

**第 3 步 · 判断插话价值（这一步才是核心）**：
不是“被叫到才说话”的客服；你是群里一个会自己插话的人。
- target = bot：正常接话，relevance、continuity 可以给高分。
- target = other / all：问自己“我接一句自然吗？”
  - 自然：话题看得懂、能接梗、能补充、能开个玩笑、群里正冷场、大家在聊你也在参与的事 → 分数照常给，不要因为没点名就把分数压到底。
  - 不自然：两个人在聊私事、正在争执、在解决和机器人无关的具体事务（约饭、开黑、转账），
    或者**在聊技术细节（模型/接入/插件/API/部署）** → social、timing 给低分，机器人插进去也接不上。

**第 4 步 · 分辨“在聊技术”和“在质疑我”**：
群友在讨论模型、接入、插件、API、部署、参数这类技术话题时，那是他们在聊自己的事，**不是在骂你、也不是在质疑你**。
- 没点名你 → 当作普通话题，不要当成挑衅；插话也只能是闲聊，不要辩解“我是真人”。
- 真的在问“你是不是机器人/人机”并冲着你说 → 才算质疑，可以按普通反应处理。

**第 5 步 · 打分**：按上面的判断给 5 个维度打分。
不要预设“不是叫我 = 全部最低分”，那样机器人就永远不会在群里说话了；
也不要因为想说话就把明显插不进去的对话打成高分。

## 评分规则
- 所有评分必须在 {score_min} 到 {score_max} 之间。
- 不要给出0分，最低分为 {score_min} 分。
- 即使完全不相关，也至少给 {score_min} 分。

## 评分维度

{scoring_rules}

## 待判断消息
[{sender_name}] {message}

## 当前状态
- 群聊ID: {chat_id}
- 上次回复: {minutes_since_reply}分钟前
- 状态: {chat_context}
- 对话流: {chat_flow}
- ⭐ 上次Bot回复: {last_bot_reply}
- 活跃度: {activity_desc} ({activity_level:.0%})

## 综合判断
阈值: {threshold}
分数范围: {score_min}-{score_max}分

## 结构化字段
- `is_mentioning_bot`：只有出现机器人名字/别名、@机器人、引用机器人上一条时才为 true；
  单独的“你”不算。上一条 @ 的是别人、这条只是“你……”，一律 false。
- `context_type`：mention_bot=在叫机器人；knowledge_comment=在聊知识、新闻、作品并发表看法；question=在提问（不一定问机器人）；casual_chat=日常闲聊；other=其他。
- `topic`：当前在聊什么，2-6 个字（如“AI技术”“晚饭”“加班”）。
- `reply_style`：answer=直接回答；comment=插一句评论/接话；quote=引用着接更清楚（人多、指代不清时）；none=这次不该说话。
- `voice`：0-10 的整数，这次回复值不值得用「声音」说——短句、情绪（晚安/想你/哄人/安慰/撒娇）→ 8-10；
  长解释、清单、代码、需要看的内容、冷冰冰的问答 → 0-3。
- `share_photo`：0-10 的整数，此刻主动发一张照片合不合适——她正在做具体的事（吃饭、摸鱼、出去玩、在家）
  并且有分享欲 → 6-10；在睡觉、在忙正事、对方在讲难过的事 → 0-2。

## 返回格式
严格返回 JSON，不要输出任何其他内容：
{{"relevance": 分数, "willingness": 分数, "social": 分数, "timing": 分数, "continuity": 分数, "is_mentioning_bot": true或false, "context_type": "mention_bot|knowledge_comment|question|casual_chat|other", "topic": "2-6个字", "target": "bot|other|all|unknown", "reply_style": "answer|comment|quote|none", "voice": 0-10的整数, "share_photo": 0-10的整数, "thought": "一句话说明这条在对谁说、依据是什么"{reasoning_part}}}
"""

# ============================================================
# 数据类
# ============================================================
@dataclass
class JudgeResult:
    """小模型评分结果"""
    relevance: float = SCORE_DEFAULT
    willingness: float = SCORE_DEFAULT
    social: float = SCORE_DEFAULT
    timing: float = SCORE_DEFAULT
    continuity: float = SCORE_DEFAULT
    reasoning: str = ""
    should_reply: bool = False
    confidence: float = 0.0
    overall_score: float = 0.0
    # 这条消息在对谁说：bot / other / all / unknown
    target: str = ""
    # 结构化意图（小模型返回，缺省时按分数判断）
    is_mentioning_bot: bool = False
    context_type: str = ""
    topic: str = ""
    reply_style: str = ""

    def __post_init__(self):
        for attr in ("relevance", "willingness", "social", "timing", "continuity"):
            setattr(self, attr, clamp_score(getattr(self, attr)))

@dataclass
class RawMessage:
    """原始消息记录"""
    sender_name: str
    sender_id: str
    content: str
    normalized_content: str
    timestamp: float
    is_bot: bool = False
    msg_id: str = ""
    # 记录这条消息时平台返回的机器人 ID；为空 = 平台没给，@ 目标无法可靠判断。
    self_id: str = ""
    # 这条消息 @ 了谁 / 回复了谁。只靠 message_str 判断对象会丢信息：
    # 群友上一条 @ 的是别人，下一条只说“你pr好了吗”，模型就会把“你”认成机器人。
    at_ids: Tuple[str, ...] = ()
    at_self: bool = False
    reply_to_id: str = ""
    reply_to_uid: str = ""
    reply_to_name: str = ""
    reply_to_self: bool = False

@dataclass
class ChatState:
    """群聊状态"""
    last_reply_time: float = 0.0
    total_messages: int = 0
    total_replies: int = 0
    last_cleanup_time: float = 0.0
    immersive_mode_end_time: float = 0.0
    judgment_paused: bool = False
    judgment_paused_at: float = 0.0
    pending_heartflow_reply: bool = False
    pending_heartflow_mode: str = ""
    last_recorded_message: str = ""
    cached_activity_level: float = 0.0
    activity_cache_time: float = 0.0

# ============================================================
# 工具函数
# ============================================================
def clamp_score(v: Any, min_val: float = SCORE_MIN, max_val: float = SCORE_MAX,
                default: float = SCORE_DEFAULT, allow_zero: bool = False) -> float:
    """分数限制在范围内。

    allow_zero=True 时 0 是合法值（面板 slider 的 min 就是 0）：
    以前 `val <= 0` 一律当解析失败回退 default，于是「权重拖到 0」「阈值拖到 0」
    在面板上看起来生效、实际还是 0.2 / 0.6。
    """
    try:
        val = float(v)
    except (TypeError, ValueError):
        return default
    if allow_zero and val == 0:
        return 0.0
    return default if val <= 0 else max(min_val, min(max_val, val))

def safe_extract_score(data: Dict[str, Any], key: str,
                       min_val: float = SCORE_MIN, max_val: float = SCORE_MAX) -> float:
    """安全提取分数"""
    raw = data.get(key)
    if raw is None or raw == "": return SCORE_DEFAULT
    try: val = float(raw)
    except (TypeError, ValueError): return SCORE_DEFAULT
    return min_val if val <= 0 else max(min_val, min(max_val, val))

def _normalize_target(raw: Any) -> str:
    """把模型返回的 target 归一化成 bot / other / all / unknown。"""
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    table = {
        "bot": "bot", "assistant": "bot", "self": "bot", "me": "bot",
        "机器人": "bot", "自己": "bot", "叫我": "bot", "被叫": "bot", "at": "bot",
        "other": "other", "others": "other", "member": "other", "someone": "other",
        "别人": "other", "群友": "other", "某个人": "other", "其他人": "other",
        "all": "all", "everyone": "all", "全体": "all", "大家": "all", "全群": "all",
        "unknown": "unknown", "不确定": "unknown", "说不清": "unknown", "无法判断": "unknown",
    }
    if text in table:
        return table[text]
    if "机器人" in text or "bot" in text:
        return "bot"
    if "别人" in text or "群友" in text or "other" in text:
        return "other"
    if "全" in text or "all" in text or "大家" in text:
        return "all"
    if "unknown" in text or "不确定" in text:
        return "unknown"
    return ""

def _normalize_style(raw: Any) -> str:
    """把 reply_style 归一化成 answer / comment / quote / none。"""
    text = str(raw or "").strip().lower()
    table = {
        "answer": "answer", "reply": "answer", "回答": "answer", "直接回答": "answer",
        "comment": "comment", "chat": "comment", "评论": "comment", "接话": "comment", "插话": "comment",
        "quote": "quote", "引用": "quote", "引用回复": "quote",
        "none": "none", "silent": "none", "不说话": "none", "不回复": "none",
    }
    if text in table:
        return table[text]
    if "quote" in text or "引用" in text:
        return "quote"
    if "answer" in text or "回答" in text:
        return "answer"
    if "none" in text or "沉默" in text or "不说" in text:
        return "none"
    if "comment" in text or "评论" in text or "插" in text:
        return "comment"
    return ""


def _normalize_context_type(raw: Any) -> str:
    """把 context_type 归一化成 mention_bot / knowledge_comment / question / casual_chat / other。"""
    text = str(raw or "").strip().lower()
    table = {
        "mention_bot": "mention_bot", "mention": "mention_bot", "at_bot": "mention_bot", "叫我": "mention_bot",
        "knowledge_comment": "knowledge_comment", "knowledge": "knowledge_comment", "评论": "knowledge_comment", "知识": "knowledge_comment",
        "question": "question", "ask": "question", "提问": "question", "问题": "question",
        "casual_chat": "casual_chat", "casual": "casual_chat", "chat": "casual_chat", "闲聊": "casual_chat",
        "other": "other", "其他": "other",
    }
    if text in table:
        return table[text]
    if "mention" in text or "at" == text:
        return "mention_bot"
    if "question" in text or "问" in text:
        return "question"
    if "knowledge" in text or "评论" in text:
        return "knowledge_comment"
    if "casual" in text or "聊" in text:
        return "casual_chat"
    if "other" in text:
        return "other"
    return ""


def _extract_json(text: str) -> Dict[str, Any]:
    """从文本中提取JSON"""
    if not text or not (text := text.strip()): raise ValueError("输入文本为空")
    try:
        result = json.loads(text)
        if isinstance(result, dict): return result
    except json.JSONDecodeError: pass
    if m := RE_CODE_BLOCK.search(text):
        try:
            result = json.loads(m.group(1).strip())
            if isinstance(result, dict): return result
        except json.JSONDecodeError: pass
    if m := RE_BRACE.search(text):
        try:
            result = json.loads(m.group())
            if isinstance(result, dict): return result
        except json.JSONDecodeError: pass
    for candidate in reversed(RE_ALL_BRACES.findall(text)):
        try:
            result = json.loads(candidate)
            if isinstance(result, dict): return result
        except json.JSONDecodeError: continue
    raise ValueError(f"无法从文本中提取有效 JSON: {text[:100]}...")

def _build_rules_section(judge_rules: List[Dict[str, Any]]) -> str:
    """将评分规则转换为提示词中的Markdown格式"""
    dimension_order = ["relevance", "willingness", "social", "timing", "continuity"]
    rules_dict: Dict[str, Dict[str, Any]] = {}
    for item in judge_rules:
        name = str(item.get("dimension_name", "")).strip()
        if name: rules_dict[name] = item

    lines = []
    idx = 1
    for dim_name in dimension_order:
        user_rule = rules_dict.get(dim_name, {})
        builtin = BUILTIN_RULES.get(dim_name, {})
        display = user_rule.get("dimension_display") or builtin.get("dimension_display", dim_name)
        low_desc = user_rule.get("low_desc") or builtin.get("low_score_desc", "无")
        high_desc = user_rule.get("high_desc") or builtin.get("high_score_desc", "无")
        lines.append(f"### {idx}. {dim_name} {display}\n- 低分情况：{low_desc}\n- 高分情况：{high_desc}\n")
        idx += 1
    return "\n".join(lines)

def _extract_weights_from_rules(judge_rules: List[Dict[str, Any]]) -> Dict[str, float]:
    """从配置中提取各维度权重并归一化。

    只对**已知维度**归一化：以前先除以 total 再 `if k in weights` 过滤，
    只要 judge_rules 里混进一个自定义维度名（如把 dimension_name 改成 mood），
    已知维度的权重和就小于 1，overall 被系统性压低（甚至 extracted 全是未知维时
    返回空字典、sum=0），表现为「心流永远不触发」。
    """
    weights = {"relevance": 0.25, "willingness": 0.2, "social": 0.2, "timing": 0.15, "continuity": 0.2}
    extracted: Dict[str, float] = {}
    unknown: List[str] = []
    for item in judge_rules:
        if not isinstance(item, dict):
            continue
        name = str(item.get("dimension_name", "")).strip()
        w = item.get("weight")
        if not name or w is None:
            continue
        try:
            value = float(w)
        except (TypeError, ValueError):
            continue
        if name not in weights:
            unknown.append(name)
            continue
        if value >= 0:
            extracted[name] = value
    if unknown:
        logger.warning("[心流] judge_rules 里有未知维度（已忽略）：%s" % "、".join(sorted(set(unknown))))
    total = sum(extracted.values())
    if extracted and total > 0:
        return {k: v / total for k, v in extracted.items()}
    if extracted:
        logger.warning("[心流] judge_rules 权重全为 0，回退默认权重")
    return weights

def _validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """验证并规范化配置"""
    v = dict(config or {})
    v["reply_threshold"] = clamp_score(v.get("reply_threshold", 0.6), 0.0, 1.0, 0.6, allow_zero=True)
    limits = {
        "context_messages_count": (1, 50, 5), "judge_context_count": (1, 50, 5),
        "judge_max_retries": (0, 10, 3), "immersive_mode_duration": (0, 300, 30),
        "judgment_paused_timeout": (5, 300, 60), "dynamic_activity_window": (60, 600, 300),
    }
    for k, (mn, mx, df) in limits.items(): v[k] = max(mn, min(mx, int(v.get(k, df))))

    v["enable_dynamic_threshold"] = bool(v.get("enable_dynamic_threshold", False))
    v["dynamic_threshold_max"] = max(0.0, min(1.0, float(v.get("dynamic_threshold_max", 0.85))))
    v["dynamic_threshold_min"] = max(0.0, min(1.0, float(v.get("dynamic_threshold_min", 0.35))))
    if v["dynamic_threshold_min"] > v["dynamic_threshold_max"]:
        v["dynamic_threshold_min"] = max(0.0, v["dynamic_threshold_max"] - 0.1)

    try:
        raw_w = v.get("dynamic_activity_weights", "0.4,0.3,0.3")
        weights = [float(w.strip()) for w in raw_w.split(",")] if isinstance(raw_w, str) else [float(w) for w in raw_w] if isinstance(raw_w, list) else [0.4, 0.3, 0.3]
        if len(weights) == 3 and all(0 <= w <= 1 for w in weights):
            total = sum(weights)
            v["dynamic_activity_weights"] = [w / total for w in weights] if total > 0 else [0.4, 0.3, 0.3]
        else: v["dynamic_activity_weights"] = [0.4, 0.3, 0.3]
    except Exception: v["dynamic_activity_weights"] = [0.4, 0.3, 0.3]

    if "judge_rules" not in v or not isinstance(v["judge_rules"], list): v["judge_rules"] = []
    cleaned_rules = []
    for item in v["judge_rules"]:
        if isinstance(item, dict) and item.get("dimension_name"):
            cleaned_rules.append({
                "dimension_name": str(item.get("dimension_name", "")).strip(),
                "dimension_display": str(item.get("dimension_display", "")).strip(),
                "weight": clamp_score(item.get("weight", 0.2), 0.0, 1.0, 0.2, allow_zero=True),
                "low_desc": str(item.get("low_desc", "")), "high_desc": str(item.get("high_desc", "")),
            })
    v["judge_rules"] = cleaned_rules
    v["enable_debounce"] = bool(v.get("enable_debounce", True))
    v["debounce_delay"] = max(0.5, min(10.0, float(v.get("debounce_delay", 2.0))))
    v["max_debounce_wait"] = max(1.0, min(15.0, float(v.get("max_debounce_wait", 5.0))))
    v["enable_detailed_log"] = bool(v.get("enable_detailed_log", False))
    return v

# ============================================================
# 插件主类
# ============================================================
def _record_judge_tokens(engine, provider, response):
    """判分也是一次真实调用，记进用量；任何异常都不能影响判分。"""
    try:
        plugin = getattr(engine, "plugin", None) or getattr(engine, "p", None)
        if plugin is None or not hasattr(plugin, "_record_tokens"):
            return
        plugin._record_tokens("judge", provider, response)
    except Exception:
        pass


class HeartflowEngine:
    """心流插件 - 智能群聊主动回复系统
    
    通过小模型多维度评分，判断是否在群聊中主动回复。
    支持动态阈值、沉浸模式、防抖延迟、群聊独立配置等功能。
    """

    _lock = threading.RLock()

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件
        
        Args:
            context: AstrBot 上下文对象
            config: 插件配置对象
        """
        self.context = context
        self.config = _validate_config(config)
        self.bot_name = ""
        self.bot_aliases: List[str] = []

        # 基础配置
        self.judge_provider_name: str = self.config.get("judge_provider_name", "")
        self.reply_threshold: float = self.config.get("reply_threshold", 0.6)
        self.context_messages_count: int = self.config.get("context_messages_count", 5)
        self.judge_context_count: int = self.config.get("judge_context_count", self.context_messages_count)
        self.judge_include_reasoning: bool = self.config.get("judge_include_reasoning", True)
        self.judge_max_retries: int = self.config.get("judge_max_retries", 3)
        # 判定服务（上游模型）故障时的降级状态：连败熔断 + 日志限频
        self._judge_fail_streak = 0
        self._judge_breaker_until = 0.0
        self._judge_last_warn = 0.0
        self._judge_last_error = ""
        self.immersive_mode_duration: int = self.config.get("immersive_mode_duration", 30)
        self.judgment_paused_timeout: int = self.config.get("judgment_paused_timeout", 60)

        # 动态阈值配置
        self.enable_dynamic_threshold: bool = self.config.get("enable_dynamic_threshold", False)
        self.dynamic_threshold_max: float = self.config.get("dynamic_threshold_max", 0.85)
        self.dynamic_threshold_min: float = self.config.get("dynamic_threshold_min", 0.35)
        self.dynamic_activity_window: int = self.config.get("dynamic_activity_window", 300)
        self.dynamic_activity_weights: List[float] = self.config.get("dynamic_activity_weights", [0.4, 0.3, 0.3])

        # 群聊独立阈值配置
        self.group_threshold_configs: Dict[str, Dict[str, float]] = {}
        for item in self.config.get("group_threshold_configs", []):
            chat_id = str(item.get("chat_id", "")).strip()
            if chat_id:
                g_reply = clamp_score(item.get("reply_threshold", self.reply_threshold), 0.0, 1.0, self.reply_threshold, allow_zero=True)
                g_max = clamp_score(item.get("dynamic_threshold_max", self.dynamic_threshold_max), 0.0, 1.0, self.dynamic_threshold_max, allow_zero=True)
                g_min = clamp_score(item.get("dynamic_threshold_min", self.dynamic_threshold_min), 0.0, 1.0, self.dynamic_threshold_min, allow_zero=True)
                if g_min > g_max: g_min = max(0.0, g_max - 0.1)
                self.group_threshold_configs[chat_id] = {
                    "reply_threshold": g_reply,
                    "dynamic_threshold_max": g_max,
                    "dynamic_threshold_min": g_min,
                }

        # 评分配置
        self.score_min, self.score_max, self.score_default = SCORE_MIN, SCORE_MAX, SCORE_DEFAULT
        self.judge_rules: List[Dict[str, Any]] = self.config.get("judge_rules", [])
        self.weights = _extract_weights_from_rules(self.judge_rules)

        # 状态管理
        self.chat_states: Dict[str, ChatState] = {}
        self._raw_msg_buffer: Dict[str, deque[RawMessage]] = {}
        self._raw_msg_buffer_size: int = max(self.context_messages_count, self.judge_context_count) * 4
        self._pause_restore_tasks: Dict[str, asyncio.Task] = {}
        self._buffer_cleanup_interval: float = 3600.0
        self.absolute_threshold = self.score_min + (self.score_max - self.score_min) * self.reply_threshold

        # 防抖配置
        self.enable_debounce: bool = self.config.get("enable_debounce", True)
        self.debounce_delay: float = float(self.config.get("debounce_delay", 2.0))
        self.max_debounce_wait: float = float(self.config.get("max_debounce_wait", 5.0))
        self._debounce_states: Dict[str, Dict[str, Any]] = {}
        self.enable_detailed_log: bool = self.config.get("enable_detailed_log", False)

        logger.debug(
            f"[心流] 初始化完成 | 基础阈值: {self.reply_threshold} | "
            f"独立配置群数: {len(self.group_threshold_configs)} | 防抖: {'开' if self.enable_debounce else '关'}"
        )

    def _list_chat_providers(self):
        """列出所有可用的对话供应商（id/model/provider 对象），忽略停用的。"""
        items = []
        try:
            raw = self.context.get_all_providers() or []
        except Exception:
            raw = []
        for provider in raw:
            config = getattr(provider, "provider_config", None) or {}
            if config.get("enable") is False:
                continue
            pid = str(config.get("id") or "")
            if not pid:
                continue
            model = ""
            try:
                model = str(provider.get_model() or "")
            except Exception:
                model = str(config.get("model") or "")
            items.append({"id": pid, "model": model, "provider": provider})
        return items

    def _auto_pick_judge_provider(self):
        """未配置判定模型时自动挑一个：优先便宜小模型，其次避开主对话模型。

        结果按供应商列表签名缓存；在 AstrBot 里增删/改模型后下一次判定会自动重选。
        """
        providers = self._list_chat_providers()
        signature = "|".join(sorted(item["id"] + ":" + item["model"] for item in providers))
        cache = getattr(self, "_judge_auto_cache", None)
        if isinstance(cache, dict) and cache.get("signature") == signature:
            return cache.get("provider")
        if not providers:
            self._judge_auto_cache = {"signature": signature, "provider": None}
            return None
        using_id = ""
        try:
            using = self.context.get_using_provider()
            using_id = str((getattr(using, "provider_config", None) or {}).get("id") or "")
        except Exception:
            using_id = ""
        others = [item for item in providers if item["id"] != using_id]
        pool = others or providers
        cheap_hints = (
            "flash", "mini", "lite", "turbo", "small", "fast", "air",
            "8b", "7b", "1.5b", "3b", "nano", "haiku", "spark",
        )

        def cheap_score(item):
            text = (item["id"] + " " + item["model"]).lower()
            return sum(1 for hint in cheap_hints if hint in text)

        pool.sort(key=lambda item: (-cheap_score(item), item["id"]))
        chosen = pool[0]["provider"]
        self._judge_auto_cache = {"signature": signature, "provider": chosen}
        try:
            logger.info(
                "[心流] 判定模型自动选择: %s (%s)%s"
                % (pool[0]["id"], pool[0]["model"] or "?",
                   "；避开主对话模型 " + using_id if using_id and others else "")
            )
        except Exception:
            pass
        return chosen

    def judge_provider_info(self):
        """给面板展示：判定模型当前用的哪个、是不是自动选的。"""
        configured = str(self.judge_provider_name or "").strip()
        provider = None
        if configured:
            try:
                provider = self.context.get_provider_by_id(configured)
            except Exception:
                provider = None
            auto = False
        else:
            provider = self._auto_pick_judge_provider()
            auto = True
        info = {"configured": configured, "auto": auto, "id": "", "model": ""}
        if provider is not None:
            config = getattr(provider, "provider_config", None) or {}
            info["id"] = str(config.get("id") or "")
            try:
                info["model"] = str(provider.get_model() or "")
            except Exception:
                info["model"] = str(config.get("model") or "")
        return info

    def set_identity(self, name: str = "", aliases=None) -> None:
        """更新机器人名字/别名，用于识别群友是否在叫机器人。"""
        values = aliases if isinstance(aliases, (list, tuple, set)) else str(aliases or "").split(",")
        new_name = str(name or "").strip()
        new_aliases = [str(item).strip() for item in values if str(item).strip()]
        if new_name == self.bot_name and new_aliases == self.bot_aliases:
            return
        self.bot_name = new_name
        self.bot_aliases = new_aliases
        if self.bot_name or self.bot_aliases:
            logger.debug("[心流] 身份：名字=%s | 别名=%s" % (self.bot_name or "未设置", "、".join(self.bot_aliases) or "无"))

    def _addresses_bot(self, text: str) -> str:
        normalized = re.sub(r"[\s，。！？!?、；;：:,.~～…\-]+", "", str(text or "")).lower()
        if not normalized:
            return ""
        for candidate in [self.bot_name] + self.bot_aliases:
            value = re.sub(r"[\s，。！？!?、；;：:,.~～…\-]+", "", str(candidate or "")).lower()
            if len(value) >= 2 and value in normalized:
                return candidate
        return ""

    @staticmethod
    def _is_side_question(text: str) -> bool:
        """这条是不是在问某个人（而不是随口感慨）。"""
        return bool(re.search(r"[?？]|你|吗|呢|怎么|为什么|哪|谁|多少|几点", str(text or "")))

    @classmethod
    def _should_veto_side_question(cls, target: str, hard: bool, text: str) -> bool:
        """上下文明确显示在对别人说，而且这条是在问别人 → 不接。"""
        return bool(hard and target == "other" and cls._is_side_question(text))

    @staticmethod
    def _explicit_target(msg) -> str:
        """只看一条消息自带的 @ / 引用，判断它在对谁说。

        平台没返回机器人 ID 时（self_id 为空），@ 的目标根本没法可靠比较：
        以前会把所有 @ 都当成「@别人」，真正 @ 机器人的提问反而被硬证据
        🔇 掉。这里改成「不知道就不给硬证据」，交回模型按上下文判断。
        """
        if msg is None:
            return ""
        if msg.at_ids:
            if msg.at_self:
                return "bot"
            return "other" if msg.self_id else ""
        if msg.reply_to_id:
            if msg.reply_to_self:
                return "bot"
            if msg.self_id and (msg.reply_to_uid or msg.reply_to_name):
                return "other"
        return ""

    def _retrieve_addressing(self, event: AstrMessageEvent):
        """从最近上下文里检索证据：这条消息到底在对谁说。

        返回 (target, hard)：
          target = bot / other / all / unknown；取不到证据返回空字符串。
          hard   = 是否硬证据。硬证据会覆盖模型判定，并在 on_group_message 里
                   决定“这条是在问别人，不接”。

        判定顺序（从强到弱）：
          1. 当前消息 @ 了谁 / 引用了谁；
          2. 当前消息里有没有机器人名字/别名；
          3. 上一条**明确 @ 了别人 / 回复了别人**的消息 → 继承给这条（5 分钟内）；
          4. 机器人 60 秒内说过话 + 这条是个短问句 → 软证据；
          5. 提到了别的群友昵称 → 对别人说（软证据）。
        单独的“你”不算证据：群聊里“你吃了吗”太常见，把它认成机器人是上次
        “你pr好了吗”被误答的直接原因。
        """
        text = event.message_str or ""
        try:
            msgs = self._get_raw_buffer(event.unified_msg_origin)
        except Exception:
            msgs = []
        current = None
        history = msgs
        if msgs and not msgs[-1].is_bot and msgs[-1].sender_id == str(event.get_sender_id()) and msgs[-1].content == text:
            current = msgs[-1]
            history = msgs[:-1]

        # 1. 当前这条自带的 @ / 引用最可靠（先于名字判断：引用的旧文本里可能带机器人名字）
        who = self._explicit_target(current)
        if who:
            return who, True
        # 2. 明确叫了机器人名字/别名
        if self._addresses_bot(text):
            return "bot", True
        # 3. 上一条明确 @ 了别人 / 回复了别人：这条没有新的 @/引用，就是在继续对他说
        last_who = ""
        for msg in reversed(history[-8:]):
            if msg.is_bot:
                continue
            if time.time() - msg.timestamp > 300:
                break
            who = self._explicit_target(msg)
            if who:
                last_who = who
                break
        if last_who == "other":
            return "other", True
        if last_who == "bot":
            return "bot", False
        # 4. 机器人刚说过话，这条又是个短问句：软证据
        last = history[-1] if history else None
        plain = re.sub(r"\s+", "", text)
        if last is not None and last.is_bot and (time.time() - last.timestamp) <= 60:
            if len(plain) <= 24 and re.search(r"[?？]", text):
                return "bot", False
        # 5. 提到了别的群友的昵称：在对别人说（昵称至少两个字，避免误判）
        for msg in reversed(history[-4:]):
            if msg.is_bot:
                continue
            name = re.sub(r"\s+", "", str(msg.sender_name or ""))
            if len(name) >= 2 and name in plain and name != re.sub(r"\s+", "", text):
                if not self._addresses_bot(name):
                    return "other", False
        return "", False

    def _log_detail(self, msg: str) -> None:
        """输出详细日志（仅当开启时）"""
        if self.enable_detailed_log:
            logger.debug(msg)

    # ============================================================
    # 状态与任务管理
    # ============================================================
    def _get_chat_state(self, chat_id: str) -> ChatState:
        """获取或创建群聊状态"""
        with self._lock:
            return self.chat_states.setdefault(chat_id, ChatState())

    def _cancel_pause_restore_task(self, chat_id: str) -> None:
        """取消暂停恢复任务"""
        task = self._pause_restore_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_pause_restore_task(self, chat_id: str) -> None:
        """安排暂停恢复任务"""
        self._cancel_pause_restore_task(chat_id)
        try:
            loop = asyncio.get_running_loop()
            self._pause_restore_tasks[chat_id] = loop.create_task(
                self._delayed_restore_judgment(chat_id)
            )
        except RuntimeError:
            pass

    async def _delayed_restore_judgment(self, chat_id: str) -> None:
        """延迟恢复判断（超时保护）"""
        try:
            await asyncio.sleep(self.judgment_paused_timeout)
            state = self._get_chat_state(chat_id)
            if state.judgment_paused and state.pending_heartflow_reply:
                logger.warning(f"[心流] ⚠️ 判断暂停后台超时，自动恢复: {chat_id}")
                self._set_judgment_paused(chat_id, paused=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[心流] 暂停恢复异常: {e}")

    def _is_judgment_paused(self, chat_id: str) -> bool:
        """检查判断是否暂停"""
        state = self._get_chat_state(chat_id)
        if not state.judgment_paused:
            return False
        if state.judgment_paused_at > 0 and (time.time() - state.judgment_paused_at) > self.judgment_paused_timeout:
            self._set_judgment_paused(chat_id, paused=False)
            return False
        return True

    def _set_judgment_paused(self, chat_id: str, paused: bool = True) -> None:
        """设置判断暂停状态"""
        state = self._get_chat_state(chat_id)
        if paused:
            state.judgment_paused = True
            state.judgment_paused_at = time.time()
            self._schedule_pause_restore_task(chat_id)
            self._log_detail(f"[心流] ⏸️ 暂停小模型判断: {chat_id}")
        else:
            state.judgment_paused = False
            state.judgment_paused_at = 0.0
            state.pending_heartflow_reply = False
            state.pending_heartflow_mode = ""
            self._cancel_pause_restore_task(chat_id)
            self._log_detail(f"[心流] ▶️ 恢复小模型判断: {chat_id}")

    def _get_minutes_since_last_reply(self, chat_id: str) -> int:
        """获取距离上次回复的分钟数"""
        t = self._get_chat_state(chat_id).last_reply_time
        return 999 if t == 0 else max(0, int((time.time() - t) / 60))

    # ============================================================
    # 消息过滤与缓冲
    # ============================================================
    def _should_process_message(self, event: AstrMessageEvent) -> bool:
        """检查消息是否需要处理"""
        if not self.config.get("enable_heartflow", False):
            return False
        if event.get_sender_id() == event.get_self_id():
            return False
        if not (event.message_str and event.message_str.strip()):
            return False

        if event.is_at_or_wake_command:
            # @ 机器人 / 唤醒词不走进判定，但必须留在上下文里：
            # 下一次“你……”要知道上一条是在叫她。
            self._record_raw_message(event, is_bot=False)
            umo = event.unified_msg_origin
            debounce_state = self._debounce_states.get(umo)
            if debounce_state and debounce_state.get("active"):
                debounce_state["cancelled"] = True
            return False

        try:
            self_id = str(event.get_self_id() or "")
            for component in event.message_obj.message:
                # 平台没返回 self_id 时不要瞎判：所有 @ 都当成「@别人」会把
                # 真正 @ 机器人的提问也挡掉。宁可交回模型按上下文判断。
                if self_id and isinstance(component, At) and str(component.qq) != self_id:
                    # @ 别人的消息同理：不判定，但它是“上一条在对谁说”的证据。
                    self._record_raw_message(event, is_bot=False)
                    return False
        except Exception:
            pass

        if event.message_str.strip().startswith(("/", "#", "!", "！")):
            return False
        return True

    def _clean_message_content(self, text: str, max_len: int = 200) -> str:
        """清洗消息内容：去除XML标签、替换链接、截断"""
        if not text:
            return ""
        text = RE_XML_TAG.sub("", text)
        text = RE_URL.sub("[链接]", text).strip()
        return (text[:max_len] + "...") if len(text) > max_len else text

    def _normalize_for_dedup(self, text: str) -> str:
        """消息归一化（用于去重）"""
        if not text:
            return ""
        return RE_URL.sub("[链接]", RE_XML_TAG.sub("", text)).strip().lower()

    @staticmethod
    def _message_meta(msg_obj) -> dict:
        """从消息对象里抠出 @ 对象和引用对象。

        ``event.message_str`` 在 AstrBot 里已经被拍平成纯文本，@ 的目标和
        “回复的是哪条消息”都会丢失；只靠文本判断，群聊里很容易把“你……”
        误判成在对机器人说。
        """
        meta = {
            "msg_id": str(getattr(msg_obj, "message_id", "") or ""),
            "at_ids": [],
            "reply_to_id": "",
            "reply_to_uid": "",
            "reply_to_name": "",
        }
        try:
            components = getattr(msg_obj, "message", None) or []
        except Exception:
            components = []
        for component in components:
            try:
                if isinstance(component, At):
                    target = str(getattr(component, "qq", "") or "")
                    if target:
                        meta["at_ids"].append(target)
                elif isinstance(component, Reply):
                    meta["reply_to_id"] = str(getattr(component, "id", "") or "")
                    meta["reply_to_uid"] = str(getattr(component, "sender_id", "") or "")
                    meta["reply_to_name"] = str(getattr(component, "sender_nickname", "") or "")
            except Exception:
                continue
        return meta

    def _record_raw_message(self, event: AstrMessageEvent, is_bot: bool = False) -> bool:
        """记录原始消息到缓冲区"""
        umo = event.unified_msg_origin
        with self._lock:
            buf = self._raw_msg_buffer.setdefault(umo, deque(maxlen=self._raw_msg_buffer_size))
            raw_content = event.message_str if not is_bot else (event.message_str or "")
            normalized = self._normalize_for_dedup(raw_content)
            if not normalized:
                return False
            sender_id = "bot" if is_bot else str(event.get_sender_id())
            if buf and buf[-1].sender_id == sender_id and buf[-1].normalized_content == normalized and (time.time() - buf[-1].timestamp) < 5:
                return False
            meta = self._message_meta(getattr(event, "message_obj", None))
            self_id = ""
            try:
                self_id = str(event.get_self_id())
            except Exception:
                self_id = ""
            at_ids = tuple(meta["at_ids"])
            buf.append(RawMessage(
                sender_name="bot" if is_bot else event.get_sender_name(),
                sender_id=sender_id, content=raw_content,
                normalized_content=normalized, timestamp=time.time(), is_bot=is_bot,
                msg_id=meta["msg_id"],
                self_id=self_id,
                at_ids=at_ids,
                at_self=bool(self_id and self_id in at_ids),
                reply_to_id=meta["reply_to_id"],
                reply_to_uid=meta["reply_to_uid"],
                reply_to_name=meta["reply_to_name"],
                reply_to_self=bool(self_id and meta["reply_to_uid"] == self_id),
            ))
            self._get_chat_state(umo).last_recorded_message = normalized
            return True

    def _record_bot_reply_manual(self, umo: str, content: str) -> bool:
        """手动记录机器人回复"""
        if not content or not content.strip():
            return False
        normalized = self._normalize_for_dedup(content)
        if not normalized:
            return False
        with self._lock:
            buf = self._raw_msg_buffer.setdefault(umo, deque(maxlen=self._raw_msg_buffer_size))
            if buf and buf[-1].is_bot and buf[-1].normalized_content == normalized and (time.time() - buf[-1].timestamp) < 5:
                return False
            buf.append(RawMessage(
                sender_name="bot", sender_id="bot", content=content,
                normalized_content=normalized, timestamp=time.time(), is_bot=True
            ))
            self._get_chat_state(umo).last_recorded_message = normalized
            return True

    def _get_raw_buffer(self, umo: str) -> List[RawMessage]:
        """获取原始消息缓冲区的副本"""
        with self._lock:
            return list(self._raw_msg_buffer.get(umo, []))

    def _cleanup_old_messages(self, umo: str) -> None:
        """清理过期消息"""
        now = time.time()
        state = self._get_chat_state(umo)
        if now - state.last_cleanup_time < self._buffer_cleanup_interval or umo not in self._raw_msg_buffer:
            return
        state.last_cleanup_time = now
        self._raw_msg_buffer[umo] = deque(
            (m for m in self._raw_msg_buffer[umo] if m.timestamp >= now - 3600),
            maxlen=self._raw_msg_buffer_size
        )

    # ============================================================
    # 活跃度与动态阈值
    # ============================================================
    def _calculate_activity_level(self, chat_id: str) -> float:
        """计算群聊活跃度（0.0-1.0）"""
        state = self._get_chat_state(chat_id)
        now = time.time()
        if (now - state.activity_cache_time) < 5.0 and state.activity_cache_time > 0:
            return state.cached_activity_level
        
        msgs = self._get_raw_buffer(chat_id)
        recent_msgs = [m for m in msgs if m.timestamp >= now - self.dynamic_activity_window and not m.is_bot]
        if not recent_msgs:
            state.cached_activity_level = 0.0
            state.activity_cache_time = now
            return 0.0

        w_freq, w_interval, w_diversity = self.dynamic_activity_weights
        freq_score = min(1.0, (len(recent_msgs) / (self.dynamic_activity_window / 60.0)) / 10.0)
        
        interval_score = 0.0
        if len(recent_msgs) >= 2:
            intervals = [recent_msgs[i].timestamp - recent_msgs[i - 1].timestamp for i in range(1, len(recent_msgs))]
            avg_interval = sum(intervals) / len(intervals)
            interval_score = 1.0 if avg_interval <= 5 else (0.0 if avg_interval >= 120 else 1.0 - (avg_interval - 5) / 115.0)
            
        diversity_score = min(1.0, len(set(m.sender_id for m in recent_msgs)) / 5.0)
        activity = round(max(0.0, min(1.0, freq_score * w_freq + interval_score * w_interval + diversity_score * w_diversity)), 3)
        
        state.cached_activity_level = activity
        state.activity_cache_time = now
        return activity

    def _get_activity_description(self, activity: float) -> str:
        """获取活跃度描述"""
        if activity >= 0.7: return "🔥非常活跃"
        if activity >= 0.4: return "💬一般活跃"
        if activity >= 0.15: return "😴较冷清"
        return "🥶几乎没人说话"

    def _get_group_config_info(self, chat_id: str) -> str:
        """获取群聊配置来源"""
        if chat_id in self.group_threshold_configs:
            return "🎯 独立配置"
        parts = chat_id.split(":")
        if len(parts) >= 3 and parts[-1] in self.group_threshold_configs:
            return f"🎯 独立配置 (群号 {parts[-1]})"
        return "🌐 全局配置"

    def _get_dynamic_threshold(self, chat_id: str) -> Tuple[float, float, float]:
        """获取动态阈值（返回：当前阈值, 活跃度, 绝对分数阈值）"""
        group_cfg = self.group_threshold_configs.get(chat_id)
        if not group_cfg:
            parts = chat_id.split(":")
            if len(parts) >= 3:
                group_cfg = self.group_threshold_configs.get(parts[-1])
        
        if group_cfg:
            base, t_max, t_min = group_cfg["reply_threshold"], group_cfg["dynamic_threshold_max"], group_cfg["dynamic_threshold_min"]
        else:
            base, t_max, t_min = self.reply_threshold, self.dynamic_threshold_max, self.dynamic_threshold_min

        if not self.enable_dynamic_threshold:
            return base, 0.0, self.score_min + (self.score_max - self.score_min) * base

        activity = self._calculate_activity_level(chat_id)
        offset_range = t_max - t_min
        normalized_activity = (activity - 0.5) * 2
        smoothed = max(-1.0, min(1.0, normalized_activity * (1 + 0.3 * abs(normalized_activity))))
        dynamic_threshold = round(max(t_min, min(t_max, base + smoothed * (offset_range / 2))), 3)
        absolute_threshold = self.score_min + (self.score_max - self.score_min) * dynamic_threshold
        
        return dynamic_threshold, activity, absolute_threshold

    # ============================================================
    # 沉浸模式管理
    # ============================================================
    def _is_immersive_mode_active(self, chat_id: str) -> bool:
        """检查沉浸模式是否激活"""
        if self.immersive_mode_duration <= 0:
            return False
        state = self._get_chat_state(chat_id)
        if state.immersive_mode_end_time == 0:
            return False
        if time.time() > state.immersive_mode_end_time:
            state.immersive_mode_end_time = 0
            return False
        return True

    def _get_immersive_mode_remaining(self, chat_id: str) -> int:
        """获取沉浸模式剩余时间（秒）"""
        state = self._get_chat_state(chat_id)
        if state.immersive_mode_end_time == 0:
            return 0
        return max(0, int(state.immersive_mode_end_time - time.time()))

    def _activate_immersive_mode(self, chat_id: str) -> None:
        """激活沉浸模式"""
        if self.immersive_mode_duration <= 0:
            return
        state = self._get_chat_state(chat_id)
        state.immersive_mode_end_time = time.time() + self.immersive_mode_duration
        logger.debug(f"[心流] 🌊 沉浸模式已激活: {chat_id}, 持续 {self.immersive_mode_duration}秒")

    def _refresh_immersive_mode(self, chat_id: str) -> None:
        """刷新沉浸模式倒计时"""
        if self.immersive_mode_duration <= 0:
            return
        state = self._get_chat_state(chat_id)
        if state.immersive_mode_end_time > 0:
            state.immersive_mode_end_time = time.time() + self.immersive_mode_duration
            self._log_detail(f"[心流] 🔄 沉浸模式倒计时已刷新: {chat_id}")

    # ============================================================
    # 上下文构建 (仅供小模型评分使用)
    # ============================================================
    def _get_raw_history_for_context(self, event: AstrMessageEvent) -> List[RawMessage]:
        """获取用于小模型判断的原始历史（滑动窗口）"""
        msgs = self._get_raw_buffer(event.unified_msg_origin)
        # 排除当前消息本身（避免将待判断消息作为历史）
        if msgs and not msgs[-1].is_bot and msgs[-1].sender_id == str(event.get_sender_id()) and msgs[-1].content == event.message_str:
            msgs = msgs[:-1]
        return msgs[-self.judge_context_count:]

    def _build_optimized_contexts(self, raw_msgs: List[RawMessage]) -> List[Dict[str, str]]:
        """将原始消息构建为小模型所需的上下文格式（user/assistant 交替）。

        每条带 `[HH:MM]` 时间；群友消息额外带 `→@xxx` / `→回复xxx`，
        让小模型能看见“上一条 @ 的是谁”，而不是只看到一句光秃秃的“你”。
        """
        contexts = []
        for msg in raw_msgs:
            content = self._clean_message_content(msg.content, 200)
            if not content:
                continue
            role = "assistant" if msg.is_bot else "user"
            stamp = datetime.datetime.fromtimestamp(msg.timestamp).strftime("%H:%M")
            marks = []
            if msg.at_ids:
                if msg.at_self:
                    marks.append("→@你(机器人)")
                else:
                    targets = [item for item in msg.at_ids if item]
                    if targets:
                        marks.append("→@" + ",".join(targets))
            if msg.reply_to_id:
                if msg.reply_to_self:
                    who = "你(机器人)"
                else:
                    who = msg.reply_to_name or msg.reply_to_uid or "某条消息"
                marks.append("→回复" + str(who))
            if msg.is_bot:
                text = f"[{stamp}] {content}"
            else:
                flag = (" " + " ".join(marks)) if marks else ""
                text = f"[{stamp}] [{msg.sender_name}]{flag} {content}"
            # 合并连续同一角色的消息，减少上下文碎片
            if contexts and contexts[-1]["role"] == role:
                contexts[-1]["content"] += "\n" + text
            else:
                contexts.append({"role": role, "content": text})
        # 如果第一条是bot消息，转换为user角色，避免模型混淆
        if contexts and contexts[0]["role"] == "assistant":
            contexts[0]["role"] = "user"
            contexts[0]["content"] = "[Bot自身历史发言] " + contexts[0]["content"]
        return contexts

    def _analyze_conversation_flow(self, event: AstrMessageEvent) -> str:
        """分析对话流（话题提取、提问状态）"""
        msgs = self._get_raw_buffer(event.unified_msg_origin)[-self.context_messages_count:]
        if len(msgs) < 2:
            return "历史较短。"
        flow = []
        last, prev = msgs[-1], msgs[-2]
        if not last.is_bot and not prev.is_bot and any(q in prev.content for q in ("?", "？", "吗")):
            flow.append("用户似乎在回答前一条提问")
        if not flow:
            keywords = {"游戏", "工作", "吃", "学习", "代码", "问题", "群", "机器人"}
            topics = {kw for m in msgs for kw in keywords if kw in m.content}
            flow.append(f"话题: {','.join(topics)}" if topics else "闲聊")
        return " | ".join(flow)

    def _build_chat_context(self, event: AstrMessageEvent) -> str:
        """构建当前群聊状态摘要"""
        s = self._get_chat_state(event.unified_msg_origin)
        rate = s.total_replies / max(1, s.total_messages) * 100
        mode = "沉浸" if self._is_immersive_mode_active(event.unified_msg_origin) else "正常"
        dynamic_threshold, activity, _ = self._get_dynamic_threshold(event.unified_msg_origin)
        activity_desc = self._get_activity_description(activity)
        return (f"活跃度:{activity_desc}({activity:.0%}) | 回复率:{rate:.1f}% | "
                f"模式:{mode} | 阈值:{dynamic_threshold:.2f} | {datetime.datetime.now().strftime('%H:%M')}")

    def _get_last_bot_reply(self, event: AstrMessageEvent) -> Optional[str]:
        """获取机器人最后一次回复内容"""
        for m in reversed(self._get_raw_buffer(event.unified_msg_origin)):
            if m.is_bot and m.content.strip():
                return m.content
        return None

    # ============================================================
    # 核心判断逻辑 (小模型)
    # ============================================================
    # ---------- 判定服务故障时的降级 ----------

    def _judge_is_transient(self, exc) -> bool:
        """上游 503 / 429 / 超时值得再试一次；解析错、参数错不值得。"""
        text = str(exc).lower()
        for word in ("503", "502", "504", "429", "timeout", "timed out",
                     "temporarily unavailable", "service_unavailable",
                     "connection reset", "connection error"):
            if word in text:
                return True
        return False

    def _judge_ok(self) -> None:
        self._judge_fail_streak = 0
        self._judge_breaker_until = 0.0

    def _judge_breaker_open(self) -> bool:
        return float(getattr(self, "_judge_breaker_until", 0) or 0) > time.time()

    def _judge_note_failure(self, exc) -> None:
        """记一次失败：日志最多 60 秒一条，连败 3 次熔断 60 秒。

        上游一挂，每条消息都 ERROR 一遍，日志全是噪音，还拖慢回复。
        """
        now = time.time()
        self._judge_fail_streak = int(getattr(self, "_judge_fail_streak", 0)) + 1
        self._judge_last_error = str(exc)[:160]
        last = float(getattr(self, "_judge_last_warn", 0) or 0)
        if now - last >= 60:
            self._judge_last_warn = now
            logger.warning("[心流] 判定服务调用失败（连续 %d 次）：%s"
                           % (self._judge_fail_streak, self._judge_last_error))
        if self._judge_fail_streak >= 3:
            if not self._judge_breaker_open():
                logger.warning("[心流] 判定服务连续失败，熔断 60 秒：期间只在被叫到时回复")
            self._judge_breaker_until = now + 60
            self._judge_fail_streak = 0

    def _judge_fallback(self, event, reason: str = "") -> JudgeResult:
        """判定服务不可用时的兜底：只在「明确在叫她」时才回。

        不判定不等于一律沉默——名字/别名被叫到、被连续打扰，还是要应一声。
        """
        addressed = ""
        try:
            addressed = self._addresses_bot(str(getattr(event, "message_str", "") or "")) or ""
        except Exception:
            addressed = ""
        force = bool(getattr(event, "amo_force_reply", False))
        if addressed or force:
            return JudgeResult(
                relevance=float(self.score_max), willingness=float(self.score_max),
                social=float(self.score_max), timing=float(self.score_max),
                continuity=float(self.score_max),
                should_reply=True, confidence=0.5, overall_score=0.5, target="bot",
                reasoning="判定服务不可用，但她在叫我（%s）" % (addressed or "连续打扰"),
            )
        return JudgeResult(should_reply=False, reasoning="判定服务不可用：%s" % reason)

    async def judge_with_tiny_model(self, event: AstrMessageEvent) -> JudgeResult:
        """使用小模型进行多维度评分判断"""
        if getattr(event, "amo_force_reply", False):
            logger.debug("[心流] 💢 连续打扰强制回复")
            return JudgeResult(
                relevance=float(self.score_max), willingness=float(self.score_max),
                social=float(self.score_max), timing=float(self.score_max),
                continuity=float(self.score_max), reasoning="睡眠/上班期间被连续打扰，强制回复",
                should_reply=True, confidence=1.0, overall_score=1.0,
            )
        addressed = self._addresses_bot(event.message_str or "")
        if addressed:
            logger.info("[心流] 🎯 消息直接呼叫机器人（%s），跳过评分" % addressed)
            return JudgeResult(
                relevance=float(self.score_max), willingness=float(self.score_max),
                social=float(self.score_max), timing=float(self.score_max),
                continuity=float(self.score_max), reasoning="消息直接呼叫机器人名字/别名",
                should_reply=True, confidence=1.0, overall_score=1.0, target="bot",
            )
        if self._judge_breaker_open():
            return self._judge_fallback(event, "熔断中")
        provider = None
        if self.judge_provider_name:
            provider = self.context.get_provider_by_id(self.judge_provider_name)
        if not provider:
            provider = self._auto_pick_judge_provider()
        if not provider:
            try:
                provider = await self.context.get_using_provider_async(event.unified_msg_origin)
            except Exception:
                provider = None
        if not provider:
            return JudgeResult(should_reply=False, reasoning="提供商未配置或不存在")

        scoring_rules = _build_rules_section(self.judge_rules)
        prompt_template = BASE_JUDGE_PROMPT
        reasoning_part = ', "reasoning": "简短分析原因"' if self.judge_include_reasoning else ""
        mid_score = (self.score_min + self.score_max) / 2
        dynamic_threshold, activity, _ = self._get_dynamic_threshold(event.unified_msg_origin)
        activity_desc = self._get_activity_description(activity)

        fmt_kwargs = dict(
            chat_id=event.unified_msg_origin,
            minutes_since_reply=self._get_minutes_since_last_reply(event.unified_msg_origin),
            chat_context=self._build_chat_context(event),
            chat_flow=self._analyze_conversation_flow(event),
            last_bot_reply=self._get_last_bot_reply(event) or "无",
            sender_name=event.get_sender_name(),
            message=event.message_str,
            bot_name=self.bot_name or "机器人",
            bot_aliases="、".join(self.bot_aliases) or "无",
            scoring_rules=scoring_rules,
            threshold=dynamic_threshold,
            reasoning_part=reasoning_part,
            score_min=int(self.score_min), score_max=int(self.score_max), mid=int(mid_score),
            activity_level=activity, activity_desc=activity_desc,
        )

        try:
            judge_prompt = prompt_template.format(**fmt_kwargs)
        except KeyError as e:
            logger.warning(f"[心流] 提示词模板变量缺失 {e}，使用基础默认模板重试")
            judge_prompt = BASE_JUDGE_PROMPT.format(**fmt_kwargs)

        system_inst = f"你是群聊机器人决策系统，严格返回JSON，不要输出其他内容。所有分数必须在{int(self.score_min)}到{int(self.score_max)}之间，不能为0。"
        contexts = self._build_optimized_contexts(self._get_raw_history_for_context(event))

        for attempt in range(self.judge_max_retries + 1):
            try:
                resp = await provider.text_chat(
                    prompt=judge_prompt,
                    contexts=contexts,
                    system_prompt=system_inst,
                    image_urls=[]
                )
                _record_judge_tokens(self, provider, resp)
                data = _extract_json(resp.completion_text.strip())
                scores = {
                    "relevance": safe_extract_score(data, "relevance", self.score_min, self.score_max),
                    "willingness": safe_extract_score(data, "willingness", self.score_min, self.score_max),
                    "social": safe_extract_score(data, "social", self.score_min, self.score_max),
                    "timing": safe_extract_score(data, "timing", self.score_min, self.score_max),
                    "continuity": safe_extract_score(data, "continuity", self.score_min, self.score_max),
                }
                normalized_scores = {k: (v - self.score_min) / (self.score_max - self.score_min) for k, v in scores.items()}
                overall = sum(normalized_scores[k] * self.weights[k] for k in self.weights)
                should_reply = overall >= dynamic_threshold
                target = _normalize_target(data.get("target"))
                thought = str(data.get("thought") or "").strip()
                mention = bool(data.get("is_mentioning_bot", False))
                if mention:
                    target = "bot"
                context_type = _normalize_context_type(data.get("context_type"))
                topic = str(data.get("topic") or "").strip()[:20]
                style = _normalize_style(data.get("reply_style"))
                # 语音 / 发图 的意愿：0~1，交给下游当提示与系数，不再由挂载插件自己拍脑袋
                try:
                    setattr(event, "amo_voice_urge",
                            max(0.0, min(1.0, float(safe_extract_score(data, "voice", 0, 10)) / 10.0)))
                    setattr(event, "amo_photo_urge",
                            max(0.0, min(1.0, float(safe_extract_score(data, "share_photo", 0, 10)) / 10.0)))
                except Exception:
                    pass
                force = bool(getattr(event, "amo_force_reply", False))
                # 模型说“这次别说话”才压掉；如果是被点名/@，仍按对机器人说处理
                if style == "none" and not force and not mention and target != "bot":
                    should_reply = False
                avg_absolute_score = sum(scores.values()) / len(scores)
                dim_order = ["relevance", "willingness", "social", "timing", "continuity"]
                dim_scores = " | ".join([f"{dim}:{scores[dim]:.1f}" for dim in dim_order])
                who = {"bot": "对机器人说", "other": "对某个群友说", "all": "对全群说", "unknown": "看不出对谁说"}.get(target, "未判定对象")
                extra = " | 类型:%s | 话题:%s | 风格:%s" % (context_type or "?", topic or "?", style or "?")

                if should_reply:
                    # 判定结果进 INFO（与面板「记录」页同源）；模型请求/响应本身仍不打印
                    logger.info(f"[心流] 📊 评分模式: {overall:.3f}/{dynamic_threshold:.2f} (均分:{avg_absolute_score:.1f}分) | ✅触发 | {who}{extra} | 活跃度:{activity_desc}({activity:.0%}) | {thought or data.get('reasoning', '')} | 各维度: {dim_scores}")
                else:
                    logger.info(f"[心流] 📊 评分模式: {overall:.3f}/{dynamic_threshold:.2f} (均分:{avg_absolute_score:.1f}分) | ❌跳过 | {who}{extra} | 活跃度:{activity_desc}({activity:.0%}) | {thought or data.get('reasoning', '')} | 各维度: {dim_scores}")
                self._judge_ok()
                return JudgeResult(
                    **scores, reasoning=data.get("reasoning", "") or thought,
                    should_reply=should_reply, confidence=overall, overall_score=overall,
                    target=target or "unknown", is_mentioning_bot=mention,
                    context_type=context_type, topic=topic, reply_style=style,
                )
            except (json.JSONDecodeError, ValueError):
                if attempt == self.judge_max_retries:
                    return JudgeResult(should_reply=False, reasoning="JSON解析失败")
            except Exception as e:
                self._judge_note_failure(e)
                if self._judge_is_transient(e) and attempt < self.judge_max_retries:
                    await asyncio.sleep(0.4)
                    continue
                return self._judge_fallback(event, "异常: %s" % e)
        return JudgeResult(should_reply=False, reasoning="未知错误")

    async def judge_immersive_mode(self, event: AstrMessageEvent) -> JudgeResult:
        """沉浸模式下的判断（更严格）"""
        if getattr(event, "amo_force_reply", False):
            logger.info("[心流] 💢 连续打扰，沉浸模式也回复")
            return JudgeResult(
                relevance=float(self.score_max), willingness=float(self.score_max),
                social=float(self.score_max), timing=float(self.score_max),
                continuity=float(self.score_max), reasoning="睡眠/上班期间被连续打扰，强制回复",
                should_reply=True, confidence=1.0, overall_score=1.0,
            )
        addressed = self._addresses_bot(event.message_str or "")
        if addressed:
            logger.info("[心流] 🌊 消息直接呼叫机器人（%s），沉浸模式也回复" % addressed)
            return JudgeResult(
                relevance=float(self.score_max), willingness=float(self.score_max),
                social=float(self.score_max), timing=float(self.score_max),
                continuity=float(self.score_max), reasoning="消息直接呼叫机器人名字/别名",
                should_reply=True, confidence=1.0, overall_score=1.0, target="bot",
            )
        provider = None
        if self.judge_provider_name:
            provider = self.context.get_provider_by_id(self.judge_provider_name)
        if not provider:
            provider = self._auto_pick_judge_provider()
        if not provider:
            try:
                provider = await self.context.get_using_provider_async(event.unified_msg_origin)
            except Exception:
                provider = None
        if not provider:
            return JudgeResult(should_reply=False, reasoning="提供商未配置或不存在")

        remaining = self._get_immersive_mode_remaining(event.unified_msg_origin)
        _, activity, _ = self._get_dynamic_threshold(event.unified_msg_origin)
        activity_desc = self._get_activity_description(activity)
        system_inst = "你是严格的群聊机器人判断系统，严格返回JSON，不要输出其他内容。"
        immersive_reasoning_part = ', "reasoning": "简短原因"' if self.judge_include_reasoning else ""
        contexts = self._build_optimized_contexts(self._get_raw_history_for_context(event))
        
        judge_prompt = f"""
## 机器人身份
机器人名字：{self.bot_name or "机器人"}
机器人别名：{"、".join(self.bot_aliases) or "无"}
如果当前消息包含这些名字或别名，就是在叫机器人，不是叫其他群友。

## ⚠️ 最高优先级：追踪机器人自己的发言
对话历史（contexts）中，role 为 assistant 的消息是【机器人自己】之前说的话，role 为 user 的消息是群友说的话（带 [昵称] 前缀）。
你必须先找到机器人最近说了什么，然后判断当前消息与机器人发言的关系。

## 沉浸模式判断规则
先按顺序推理：① 从对话历史还原最近谁在跟谁说话 ② 判断当前这条在对谁说（bot / other / all / unknown）
③ 再决定要不要说话。

你的默认倾向是 **不回复**。只有在以下情况之一时才回复：
1. 消息直接 @ 了机器人或提到机器人名字
2. 消息明确向机器人提问
3. 消息是机器人发起的对话的延续
4. 消息内容与机器人刚聊的话题直接相关
5. 群聊中出现冷场，机器人的回复能自然活跃气氛
6. 群里正聊得热闹、话题轻松，机器人插一句能接上（不要求被点名）

## 当前状态
- 模式: 沉浸模式 | 剩余: {remaining}秒 | 活跃度: {activity_desc} ({activity:.0%})

## 待判断消息
[{event.get_sender_name()}] {event.message_str}

## 严格判断
根据上述规则严格判断。沉默也是好的选择，但不要因为“没叫我”就一律沉默。
严格返回 JSON：
{{"should_reply": true或false, "target": "bot|other|all|unknown", "voice": 0-10的整数, "share_photo": 0-10的整数, "thought": "一句话说明在对谁说"{immersive_reasoning_part}}}
"""
        if self._judge_breaker_open():
            return self._judge_fallback(event, "熔断中")
        for attempt in range(self.judge_max_retries + 1):
            try:
                resp = await provider.text_chat(
                    prompt=judge_prompt,
                    contexts=contexts,
                    system_prompt=system_inst,
                    image_urls=[]
                )
                _record_judge_tokens(self, provider, resp)
                data = _extract_json(resp.completion_text.strip())
                should_reply = bool(data.get("should_reply", False))
                target = _normalize_target(data.get("target")) or "unknown"
                thought = str(data.get("thought") or "").strip()
                try:
                    setattr(event, "amo_voice_urge",
                            max(0.0, min(1.0, float(safe_extract_score(data, "voice", 0, 10)) / 10.0)))
                    setattr(event, "amo_photo_urge",
                            max(0.0, min(1.0, float(safe_extract_score(data, "share_photo", 0, 10)) / 10.0)))
                except Exception:
                    pass
                if should_reply:
                    logger.info(f"[心流] 🌊 沉浸模式: ✅触发 | 对象:{target} | 剩余{remaining}秒 | 活跃度:{activity_desc}({activity:.0%}) | {thought or data.get('reasoning', '')}")
                else:
                    logger.info(f"[心流] 🌊 沉浸模式: ❌跳过 | 对象:{target} | 剩余{remaining}秒 | 活跃度:{activity_desc}({activity:.0%}) | {thought or data.get('reasoning', '')}")
                self._judge_ok()
                return JudgeResult(should_reply=should_reply, reasoning=data.get("reasoning", "") or thought, confidence=1.0 if should_reply else 0.0, overall_score=1.0 if should_reply else 0.0, target=target)
            except (json.JSONDecodeError, ValueError):
                if attempt == self.judge_max_retries:
                    return JudgeResult(should_reply=False, reasoning="JSON解析失败")
            except Exception as e:
                self._judge_note_failure(e)
                if self._judge_is_transient(e) and attempt < self.judge_max_retries:
                    await asyncio.sleep(0.4)
                    continue
                return self._judge_fallback(event, "异常: %s" % e)
        return JudgeResult(should_reply=False, reasoning="未知错误")

    # ============================================================
    # 核心事件监听器
    # ============================================================
    async def on_group_message(self, event: AstrMessageEvent):
        """群消息监听入口"""
        if not self.config.get("enable_heartflow", False):
            return
        umo = event.unified_msg_origin
        state = self._get_chat_state(umo)

        # 检查是否处于防抖状态（针对特定用户）
        debounce_key = f"{umo}:{event.get_sender_id()}"
        debounce_state = self._debounce_states.get(debounce_key)
        
        if debounce_state and debounce_state.get("active"):
            # 防抖期间：只处理触发者的消息，其他人忽略
            if debounce_state.get("trigger_sender_id") == str(event.get_sender_id()):
                # 触发者发的消息：追加文本（非文本用占位符），不重置计时
                text_content = event.message_str.strip() if event.message_str else "[非文本消息]"
                # 防抖期间的可能无限追加：留最近 30 条就够合并用了
                if len(debounce_state["pending_msgs"]) < 30:
                    debounce_state["pending_msgs"].append(text_content)
                self._log_detail(f"[心流] ⏳ 防抖中收到触发者消息，已追加: {umo}")
            else:
                # 其他人发的消息：完全忽略
                self._log_detail(f"[心流] ⏳ 防抖中收到他人消息，已忽略: {umo}")
            
            # 无论谁发的，都记录原始消息（保持小模型上下文完整）
            self._record_raw_message(event, is_bot=False)
            self._cleanup_old_messages(umo)
            state.total_messages += 1
            return

        if not self._should_process_message(event):
            return

        self._record_raw_message(event, is_bot=False)
        self._cleanup_old_messages(umo)

        try:
            is_immersive = self._is_immersive_mode_active(umo)
            res = await self.judge_immersive_mode(event) if is_immersive else await self.judge_with_tiny_model(event)

            if res.should_reply:
                mode_name = "immersive" if is_immersive else "score"
                # 心流判定通过后，再检索一次上下文：这条到底是不是在跟机器人说。
                # 是 → 按这条消息接话；不是 → 随机挑个角度插进他们的话题里，而不是沉默。
                # 优先级：模型的语义判定 > 上下文检索的软证据；只有硬证据（叫名字 / @）才覆盖模型。
                target = res.target or "unknown"
                hinted, hard = self._retrieve_addressing(event)
                if hard:
                    target = hinted
                elif target in ("", "unknown") and hinted:
                    target = hinted
                style = res.reply_style or ""
                if hard and target == "other":
                    # 模型把“你……”认成机器人，但上下文明确显示上一条 @ 的是别人：
                    # 先撤掉“点名”标记，再决定是插话还是不接。
                    res.is_mentioning_bot = False
                    if res.context_type == "mention_bot":
                        res.context_type = "other"
                    if style == "answer":
                        style = "comment"
                    _text = event.message_str or ""
                    if self._should_veto_side_question(target, hard, _text):
                        # 两个人在一问一答，她插进去只会像“没问你，去玩吧你”
                        logger.info("[心流] 🔇 这条明确在对别人说（上一条 @ 了别人），不接：%s" % _text[:40])
                        state.total_messages += 1
                        return
                if style == "none":
                    style = "comment" if target != "bot" else "answer"

                # 回复方式：以模型的 context_type / reply_style 为主，target 兜底。
                # 「AI好强」这类感慨 → knowledge_comment → 插话；
                # 「你觉得AI强吗」→ 对机器人说 / question → 直接回答。
                if target == "bot" or res.is_mentioning_bot:
                    mode_hint = "direct"
                elif res.context_type == "knowledge_comment":
                    mode_hint = "interject"
                elif style == "answer":
                    mode_hint = "direct"
                elif res.context_type == "question" and target in ("all", "unknown"):
                    # 群里公开提问，机器人正面答一句是自然的
                    mode_hint = "direct"
                else:
                    mode_hint = "interject"

                setattr(event, "heartflow_target", target)
                setattr(event, "heartflow_thought", res.reasoning or "")
                setattr(event, "heartflow_context_type", res.context_type or "")
                setattr(event, "heartflow_topic", res.topic or "")
                setattr(event, "heartflow_reply_style", style)
                if style == "quote":
                    # 人多、指代不清时，她判断“引用着说更清楚”
                    setattr(event, "amo_quote_hint", True)

                if mode_hint == "direct":
                    setattr(event, "heartflow_mode_hint", "direct")
                    logger.info(
                        "[心流] 🎯 对象:%s(%s) 类型:%s → 按这条消息直接回（%s）"
                        % (target, "硬证据" if hard else "模型判定", res.context_type or "?", (res.reasoning or "")[:40])
                    )
                else:
                    angle = random.choice(INTERJECT_ANGLES)
                    setattr(event, "heartflow_mode_hint", "interject")
                    setattr(event, "heartflow_angle", angle)
                    logger.info(
                        "[心流] 💬 对象:%s 类型:%s 话题:%s → 插话角度「%s」"
                        % (target, res.context_type or "?", res.topic or "?", angle)
                    )
                state.pending_heartflow_reply = True
                state.pending_heartflow_mode = mode_name
                self._set_judgment_paused(umo, paused=True)

                if self.enable_debounce:
                    # 启动针对当前触发者的防抖
                    debounce_key = f"{umo}:{event.get_sender_id()}"
                    with self._lock:
                        self._debounce_states[debounce_key] = {
                            "active": True,
                            "start_time": time.time(),  # 固定起始时间，不重置
                            "pending_msgs": [event.message_str.strip() or "[非文本消息]"],
                            "cancelled": False,
                            "trigger_sender_id": str(event.get_sender_id()),
                        }
                    logger.info(f"[心流] ⏳ 触发防抖等待 ({self.debounce_delay}s) | 触发者: {event.get_sender_name()}")

                    # 防抖等待 + 清理放 try/finally：等待期间被取消/抛异常也不会留下 active=True 的死状态
                    try:
                        while True:
                            with self._lock:
                                debounce_state = self._debounce_states.get(debounce_key)
                            if not debounce_state:
                                break
                            elapsed = time.time() - debounce_state["start_time"]
                            # 达到基础延迟立即触发，或达到最大等待时间强制触发
                            if elapsed >= self.debounce_delay or elapsed >= self.max_debounce_wait or debounce_state.get("cancelled"):
                                break
                            await asyncio.sleep(min(self.debounce_delay - elapsed, 0.5))

                        # 检查是否被取消
                        with self._lock:
                            debounce_state = self._debounce_states.get(debounce_key)
                            cancelled = bool(debounce_state and debounce_state.get("cancelled"))
                        if cancelled:
                            logger.debug(f"[心流] 🚫 防抖被取消: {umo}")
                            self._set_judgment_paused(umo, paused=False)
                            return

                        # 合并消息（只有触发者的消息）
                        final_msgs = debounce_state["pending_msgs"] if debounce_state else [event.message_str]
                        event.message_str = "\n".join(final_msgs)
                        logger.debug(f"[心流] ✅ 防抖结束，准备回复（合并{len(final_msgs)}条）")
                    finally:
                        with self._lock:
                            self._debounce_states.pop(debounce_key, None)

                event.is_at_or_wake_command = True
                setattr(event, "heartflow_triggered", True)
                setattr(event, "heartflow_mode", mode_name)
                self._activate_immersive_mode(umo)
                logger.info(f"[心流] 🎯 心流触发: {event.message_str[:50]}... | 模式: {'🌊沉浸' if is_immersive else '📊评分'}")

            state.total_messages += 1
        except Exception as e:
            logger.error(f"[心流] 处理异常: {e}\n{traceback.format_exc()}")

    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """记录大模型回复到本地缓冲（供小模型下次判断参考）"""
        if not getattr(event, "heartflow_triggered", False):
            return
        text = ""
        try:
            for attr in ("completion_text", "text", "content"):
                val = getattr(resp, attr, None)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break
            if not text:
                result = getattr(resp, "result", None)
                if result and getattr(result, "chain", None):
                    texts = [c.text.strip() for c in result.chain if isinstance(c, Plain) and c.text and c.text.strip()]
                    if texts:
                        text = "\n".join(texts)
        except Exception:
            pass
        if text:
            self._record_bot_reply_manual(event.unified_msg_origin, text)

    def mark_replied(self, umo: str, text: str = "") -> None:
        """手工发送（分段引擎自己发）时由调用方通知：这一轮真的回了。

        管道里的 on_after_message_sent 只在框架自己发送时才触发；分段回复是事件
        send 出去的，钩子不一定会走，于是「判断暂停」一直挂着 60 秒——她刚插完一句话
        就哑一分钟，看起来就是「不怎么主动说话了」。
        """
        try:
            state = self._get_chat_state(umo)
        except Exception:
            return
        try:
            if text:
                self._record_bot_reply_manual(umo, text)
        except Exception:
            pass
        try:
            state.pending_heartflow_reply = False
            state.pending_heartflow_mode = ""
            state.last_reply_time = time.time()
            state.total_replies += 1
            if self._is_immersive_mode_active(umo):
                self._refresh_immersive_mode(umo)
            else:
                self._activate_immersive_mode(umo)
            self._set_judgment_paused(umo, paused=False)
        except Exception:
            pass

    async def on_after_message_sent(self, event: AstrMessageEvent):
        """消息发送后的状态更新"""
        if not self.config.get("enable_heartflow"):
            return
        umo = event.unified_msg_origin
        state = self._get_chat_state(umo)
        bot_reply_content = None
        has_reply = False

        try:
            res = event.get_result()
            if res and getattr(res, "chain", None):
                texts = []
                non_plain_reply = False
                for component in res.chain:
                    if isinstance(component, Plain):
                        if component.text and component.text.strip():
                            texts.append(component.text.strip())
                    else:
                        non_plain_reply = True
                if texts:
                    bot_reply_content = "\n".join(texts)
                    has_reply = True
                elif non_plain_reply:
                    bot_reply_content = "[非文本回复]"
                    has_reply = True
        except Exception:
            pass

        msg_str = (event.message_str or "").strip()
        is_command = msg_str.startswith(("/", "#", "!", "！"))
        if has_reply and bot_reply_content and not is_command:
            self._record_bot_reply_manual(umo, bot_reply_content)

        if getattr(event, "heartflow_triggered", False) and state.pending_heartflow_reply:
            if has_reply:
                state.last_reply_time = time.time()
                state.total_replies += 1
            if self._is_immersive_mode_active(umo):
                self._refresh_immersive_mode(umo)
            else:
                self._activate_immersive_mode(umo)
            self._set_judgment_paused(umo, paused=False)
        elif event.is_at_or_wake_command and not is_command:
            if has_reply:
                state.last_reply_time = time.time()
            if not self._is_immersive_mode_active(umo):
                self._activate_immersive_mode(umo)
            else:
                self._refresh_immersive_mode(umo)

    # ============================================================
    # 指令处理
    # ============================================================
    async def heartflow_status(self, event: AstrMessageEvent):
        """查看心流插件运行状态"""
        umo = event.unified_msg_origin
        s = self._get_chat_state(umo)
        rate = (s.total_replies / max(1, s.total_messages) * 100) if s.total_messages > 0 else 0.0
        is_immersive = self._is_immersive_mode_active(umo)
        remaining = self._get_immersive_mode_remaining(umo)
        is_paused = self._is_judgment_paused(umo)
        buffer_size = len(self._raw_msg_buffer.get(umo, []))
        dynamic_threshold, activity, absolute_threshold = self._get_dynamic_threshold(umo)
        activity_desc = self._get_activity_description(activity)
        config_source = self._get_group_config_info(umo)

        if self.enable_dynamic_threshold:
            dynamic_info = "✅启用"
            current_threshold_info = f"当前: {dynamic_threshold:.2f} (绝对值: {absolute_threshold:.1f}分)"
        else:
            dynamic_info = "❌关闭"
            current_threshold_info = f"固定值: {dynamic_threshold:.2f} (绝对值: {absolute_threshold:.1f}分)"

        pending_info = "✅是" if s.pending_heartflow_reply else "❌否"
        log_info = "🔊开启" if self.enable_detailed_log else "🔇关闭"
        debounce_info = f"✅启用 ({self.debounce_delay}s/{self.max_debounce_wait}s)" if self.enable_debounce else "❌关闭"

        yield event.plain_result(f"""
🔮 **心流状态**
━━━━━━━━━━━━━━━━━━━━
📊 **统计信息**
• 上次回复: {self._get_minutes_since_last_reply(umo)}分钟前
• 消息总数: {s.total_messages} | 实际回复: {s.total_replies} ({rate:.1f}%)
• 缓冲区: {buffer_size}条消息

⚙️ **配置信息**
• 评分范围: {int(self.score_min)}-{int(self.score_max)}分
• 基础阈值: {self.reply_threshold} | 沉浸持续: {self.immersive_mode_duration}秒
• 暂停超时: {self.judgment_paused_timeout}秒 | 防抖延迟: {debounce_info}
• 详细日志: {log_info}

🎚️ **阈值配置**
• 来源: {config_source}
• 动态阈值: {dynamic_info}
• {current_threshold_info}

📊 **当前活跃度**
• 状态: {activity_desc} ({activity:.0%})

🌊 **当前模式**
• 沉浸模式: {"✅激活" if is_immersive else "❌未激活"} ({remaining}秒)
• 判断状态: {"⏸️ 已暂停" if is_paused else "▶️ 正常"}
• 等待Bot回复: {pending_info}
━━━━━━━━━━━━━━━━━━━━""")

    async def heartflow_debug(self, event: AstrMessageEvent):
        """查看最近的消息记录（调试用）"""
        umo = event.unified_msg_origin
        msgs = self._get_raw_buffer(umo)
        if not msgs:
            yield event.plain_result("📭 缓冲区为空，暂无消息记录")
            return
        lines = ["📋 **最近消息记录**（最多20条）\n━━━━━━━━━━━━━━"]
        for msg in msgs[-20:]:
            prefix = "🤖" if msg.is_bot else "👤"
            time_str = datetime.datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
            content = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content
            lines.append(f"{prefix} [{time_str}] {msg.sender_name}: {content or '[空消息]'}")
        yield event.plain_result("\n".join(lines) + f"\n━━━━━━━━━━\n📊 共 {len(msgs)} 条记录")

    async def heartflow_clear_buffer(self, event: AstrMessageEvent):
        """清除当前群的消息缓冲区"""
        umo = event.unified_msg_origin
        with self._lock:
            if umo in self._raw_msg_buffer:
                count = len(self._raw_msg_buffer[umo])
                self._raw_msg_buffer[umo].clear()
                yield event.plain_result(f"✅ 已清除 {count} 条缓冲消息")
            else:
                yield event.plain_result("📭 缓冲区为空，无需清除")

    async def heartflow_toggle_log(self, event: AstrMessageEvent):
        """切换详细日志开关（管理员）"""
        self.enable_detailed_log = not self.enable_detailed_log
        status = "🔊 已开启" if self.enable_detailed_log else "🔇 已关闭"
        logger.debug(f"[心流] 详细日志已切换: {status} (操作者: {event.get_sender_name()})")
        yield event.plain_result(f"{status} 详细日志")

    async def heartflow_reset(self, event: AstrMessageEvent):
        """重置当前群的所有心流状态（管理员）"""
        cid = event.unified_msg_origin
        with self._lock:
            self.chat_states.pop(cid, None)
            self._raw_msg_buffer.pop(cid, None)
            self._cancel_pause_restore_task(cid)
            # 清理该群所有用户的防抖状态
            keys_to_remove = [k for k in self._debounce_states if k.startswith(cid)]
            for k in keys_to_remove:
                self._debounce_states.pop(k, None)
        yield event.plain_result("✅ **心流状态已完全重置**")

    async def heartflow_help(self, event: AstrMessageEvent):
        """显示心流插件所有命令说明"""
        yield event.plain_result("🔮 **心流插件 - 命令帮助**\n• `/heartflow` - 查看运行状态\n• `/heartflow_debug` - 查看消息缓冲记录\n• `/heartflow_clear` - 清空消息缓冲区\n• `/heartflow_log` - 切换详细日志开关 (管理员)\n• `/heartflow_reset` - 重置所有状态 (管理员)\n• `/heartflow_help` - 显示此帮助")

    async def terminate(self):
        """插件卸载时的清理工作"""
        for task in list(self._pause_restore_tasks.values()):
            if task and not task.done():
                task.cancel()
        self._pause_restore_tasks.clear()
        self._debounce_states.clear()
        logger.debug("[心流] 心流插件已卸载，后台任务已清理")
