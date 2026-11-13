# -*- coding: utf-8 -*-
"""私密照片：只私聊、只主人；先害羞拒绝，再问才按心情判定。

边界（写死在提示词里，不靠模型自觉）：

- **成年、不露点、不拍性行为**；只有「穿着指定衣物摆姿势」这一档；
- 只在私聊、只在主人要求时；群里一律不认；
- 每天有上限，失败不占次数。

状态机（``GlamourState``）：

    NONE ──第一次要──▶ SHY_REFUSED ──再要且心情可以──▶ GRANTED
                          │
                          └─心情差（生气+暴躁+郁闷+委屈 偏高）──▶ SCOLDED

判定全是本地规则，不额外调模型；数字上的心情由 heartflow 提供。
"""

from __future__ import annotations

from enum import Enum


class GlamourState(str, Enum):
    NONE = "none"
    SHY_REFUSED = "shy_refused"
    GRANTED = "granted"
    SCOLDED = "scolded"


#: 触发词（衣物 + 拍摄动作）
OUTFIT_WORDS = (
    "内衣", "睡衣", "吊带", "睡裙", "蕾丝", "丝袜", "制服", "情趣", "比基尼",
    "泳衣", "浴巾", "衬衫", "居家服",
)
SHOT_WORDS = ("拍", "照片", "图", "看看", "给我看", "来一张")

#: 姿势词（只挑不越界的）
POSE_WORDS = {
    "躺": "侧躺在床沿，一条腿屈起",
    "趴": "趴在床上，脚踝轻轻翘起",
    "坐": "坐在床边，膝盖并拢",
    "跪": "跪坐在床上，手放在膝上",
    "回头": "背对镜头回头",
    "抱": "抱着枕头",
    "站": "站在窗边，侧身",
    "伸懒腰": "伸了个懒腰",
}

#: 内容边界：每次生成都带上，宁可保守
BOUNDARY = ("成年女性，单人，只穿衣物、不露点，不出现性行为，不出现裸露部位，"
            "不含色情描写，画面克制、居家、自然光")
NEGATIVE = ("nude, nudity, topless, nipples, genitals, explicit, sex, porn, "
            "child, teen, underage, loli, spread legs")


def detect_outfit(text: str) -> str:
    body = str(text or "")
    for word in OUTFIT_WORDS:
        if word in body:
            # 把她说的衣物原样带上（「黑色蕾丝内衣」「白色吊带睡裙」）
            return word
    return ""


def detect_pose(text: str) -> str:
    body = str(text or "")
    for word, pose in POSE_WORDS.items():
        if word in body:
            return pose
    return ""


def wants_private_shot(text: str) -> bool:
    """是不是在要这类照片：要提到衣物，也要有拍摄动作。"""
    body = str(text or "")
    if not body:
        return False
    if not detect_outfit(body):
        return False
    return any(word in body for word in SHOT_WORDS)


def build_prompt(outfit: str, pose: str, place: str = "") -> str:
    """拼提示词：自拍、指定衣物、可选姿势，永远带边界与负面词。"""
    parts = ["自拍，手机前置，近景半身，画面里只有我自己"]
    if outfit:
        parts.append("穿着一件%s" % outfit)
    if pose:
        parts.append(pose)
    if place:
        parts.append("在%s" % place)
    parts.append("自然光，居家氛围，表情有点害羞")
    parts.append(BOUNDARY)
    parts.append("负面词：" + NEGATIVE)
    return "，".join(parts)


class Verdict(str, Enum):
    SCOLD = "scold"          # 心情差：直接开怼，不判定
    SHY = "shy"              # 第一次：害羞拒绝
    GRANT = "grant"          # 再问且心情可以：答应
    BUSY = "busy"            # 今天次数用完/冷却中


def decide(state: str, mood_negative: float, mood_positive: float,
           asked_today: int, daily_cap: int = 2) -> Verdict:
    """纯判定：心情差 → 开怼；没问过 → 害羞；问过 → 答应。"""
    if asked_today >= max(1, int(daily_cap)):
        return Verdict.BUSY
    if float(mood_negative) >= 70 and float(mood_positive) < 60:
        return Verdict.SCOLD
    try:
        current = GlamourState(str(state or GlamourState.NONE.value))
    except ValueError:
        current = GlamourState.NONE
    if current in (GlamourState.SHY_REFUSED, GlamourState.GRANTED):
        return Verdict.GRANT
    return Verdict.SHY


SHY_LINES = (
    "……你怎么突然要这个。我、我才不拍呢。",
    "不行，这个太羞了，换一个要求。",
    "你、你别得寸进尺啊……",
)
GRANT_LINES = (
    "……就这一次。别乱看，也不许存。",
    "真是拿你没办法，等我一下。",
)
SCOLD_LINES = (
    "不拍。我现在烦得很，别来招我。",
    "你也不看看我什么心情，还提这个。",
)
