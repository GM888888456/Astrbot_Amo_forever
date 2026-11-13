# -*- coding: utf-8 -*-
"""服装库：他自己给她添的衣服。

日程配装不再随机，而是从这份库里按场景挑；库是空的才回落到内置兜底。

数据存在插件数据目录的 ``wardrobe.json``，
每条：id / name / scenes / gender / enabled / note / created。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
import zlib

# 场景标签：和 outfit_engine 的 scene 一一对应
SCENES = ("work", "home", "casual", "out", "formal", "sport", "sleep", "beach")

#: 分件槽位：上衣/裤子/裙子/JK 格裙/JK 衬衣/袜子/鞋/配饰

#: 固定搭配：某些槽位只能和特定的槽位一起出现，别的都不能配
SLOT_EXCLUSIVE = {
    # JK 衬衣只配 JK 格裙，绝不配裤子/裙子
    "jk_shirt": {"jk_skirt"},
    # JK 格裙只配 JK 衬衣，不配普通上衣
    "jk_skirt": {"jk_shirt"},
    # 连衣裙独占，不能叠裤子/上衣（外套另说，现在没有外套槽）
    "dress": set(),
}


def pair_ok(slots) -> bool:
    """判断一套搭配在规则上成不成立（只看槽位，不看具体衣服）。"""
    have = set(str(slot or "") for slot in (slots or []) if slot)
    for slot in list(have):
        need = SLOT_EXCLUSIVE.get(slot)
        if need is None:
            continue
        # 有独占规则：允许的搭档之外，不许出现别的衣服槽位
        allowed = need | {slot}
        extra = {x for x in have if x not in allowed}
        # 袜子/鞋是任何搭配都能穿的，不算冲突
        extra -= {"socks", "shoes", "accessory"}
        if extra:
            return False
    return True

SLOTS = ("top", "bottom", "dress", "jk_skirt", "jk_shirt", "socks", "shoes", "accessory")
SLOT_LABELS = {"top": "上衣", "bottom": "裤子", "dress": "裙子", "jk_skirt": "JK 格裙",
               "jk_shirt": "JK 衬衣", "socks": "袜子", "shoes": "鞋", "accessory": "配饰"}

SCENE_LABELS = {
    "work": "上班",
    "home": "在家",
    "casual": "日常",
    "out": "出门",
    "formal": "正式",
    "sport": "运动",
    "sleep": "睡觉",
    "beach": "海边",
}

# 没有显式标签时按名字猜场景；猜不到就进「日常 + 出门」
SCENE_HINTS = (
    (("睡衣", "睡裙", "家居", "居家", "棉拖"), ("sleep", "home")),
    (("泳", "比基尼"), ("beach",)),
    (("西装", "礼服", "套装", "衬衫配", "正装"), ("work", "formal")),
    (("运动", "速干", "跑鞋", "瑜伽", "健身"), ("sport",)),
    (("卫衣", "牛仔裤", "t恤", "T 恤", "外套", "针织", "毛衣", "开衫", "风衣", "夹克"),
     ("casual", "out")),
    (("连衣裙", "半身裙", "裙", "短裤", "阔腿裤"), ("casual", "out")),
)

MIN_NAME = 2
MAX_NAME = 40
MAX_ITEMS = 200


def scenes_for_slot(slot: str, style: str = "") -> list[str]:
    """分件 → 适合的场景（JK/裙子偏校园日常，鞋袜配饰全天可用）。"""
    slot = str(slot or "")
    style = str(style or "")
    if slot in ("shoes", "socks", "accessory"):
        return ["work", "home", "casual", "out", "formal", "sport"]
    if slot.startswith("jk") or "校园" in style:
        return ["casual", "out"]
    if slot == "dress":
        return ["out", "formal", "casual"]
    return ["work", "casual", "out", "home"]


def build_items_from_catalog(rows) -> list[dict]:
    """把市场目录的服装行转成衣柜条目（带 slot / scenes）。"""
    items = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = clean_name(row.get("name"))
        slot = str(row.get("slot") or "").strip()
        if not name or slot not in SLOTS:
            continue
        items.append({
            "id": uuid.uuid4().hex[:10],
            "name": name,
            "slot": slot,
            "scenes": scenes_for_slot(slot, row.get("style")),
            "gender": "女",
            "enabled": True,
            "note": "市场目录",
            "created": time.time(),
        })
    return items[:MAX_ITEMS]


def clean_name(text):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = value.strip("，,。.；;：:、!！?？\"'“”‘’")
    return value[:MAX_NAME]


def guess_scenes(name):
    lowered = str(name or "").lower()
    for words, scenes in SCENE_HINTS:
        if any(word in lowered for word in words):
            return list(scenes)
    return ["casual", "out"]


class Wardrobe:
    def __init__(self, plugin):
        self.plugin = plugin
        self._lock = threading.RLock()
        self._data = None
        base = ""
        try:
            base = os.path.dirname(str(getattr(plugin.db, "path", "") or ""))
        except Exception:
            base = ""
        if not base:
            base = str(getattr(plugin, "plugin_dir", "") or ".")
        self.path = os.path.join(base, "wardrobe.json")

    # ---------- 存储 ----------

    def _load(self):
        if self._data is not None:
            return self._data
        data = {"items": []}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                data = raw
            elif isinstance(raw, list):
                data = {"items": raw}
        except Exception:
            data = {"items": []}
        items = []
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = clean_name(item.get("name"))
            if not name:
                continue
            scenes = [scene for scene in (item.get("scenes") or []) if scene in SCENES]
            items.append({
                "id": str(item.get("id") or ("w" + uuid.uuid4().hex[:10])),
                "name": name,
                "slot": str(item.get("slot") or ""),
                "scenes": scenes or guess_scenes(name),
                "gender": str(item.get("gender") or "通用"),
                "enabled": bool(item.get("enabled", True)),
                "note": str(item.get("note") or "")[:120],
                "created": float(item.get("created") or time.time()),
            })
        data["items"] = items[-MAX_ITEMS:]
        self._data = data
        return data

    def _save(self):
        data = self._data or {"items": []}
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as exc:
            try:
                self.plugin.logger.debug("[amo] 服装库落盘失败: %s" % exc)
            except Exception:
                pass

    # ---------- 读写 ----------

    def items(self, only_enabled=False):
        with self._lock:
            items = [dict(item) for item in self._load()["items"]]
        if only_enabled:
            items = [item for item in items if item.get("enabled", True)]
        return items

    def count(self):
        return len(self.items(only_enabled=True))

    def find(self, name):
        target = clean_name(name)
        if not target:
            return {}
        for item in self.items():
            if item["name"] == target:
                return item
        return {}

    def replace_all(self, items):
        """整库替换（按市场目录重建衣柜时用）；返回替换后的条数。"""
        rows = []
        for row in items or []:
            if not isinstance(row, dict):
                continue
            name = clean_name(row.get("name"))
            if not name:
                continue
            item = {
                "id": str(row.get("id") or uuid.uuid4().hex[:10]),
                "name": name,
                "slot": str(row.get("slot") or ""),
                "scenes": list(row.get("scenes") or guess_scenes(name)),
                "gender": str(row.get("gender") or "女"),
                "enabled": bool(row.get("enabled", True)),
                "note": str(row.get("note") or ""),
                "created": float(row.get("created") or time.time()),
            }
            rows.append(item)
        with self._lock:
            data = self._load()
            data["items"] = rows[:MAX_ITEMS]
            self._data = data
            self._save()
        return len(rows[:MAX_ITEMS])

    def add(self, name, scenes=None, gender="通用", note="", slot=""):
        name = clean_name(name)
        if len(name) < MIN_NAME:
            return {}
        scenes = [scene for scene in (scenes or []) if scene in SCENES]
        with self._lock:
            data = self._load()
            for item in data["items"]:
                if item["name"] == name:
                    # 同名直接更新，避免库被同名刷爆
                    if scenes:
                        item["scenes"] = scenes
                    if gender in ("女", "男", "通用"):
                        item["gender"] = gender
                    if note:
                        item["note"] = str(note)[:120]
                    item["enabled"] = True
                    self._save()
                    return dict(item)
            item = {
                "id": "w" + uuid.uuid4().hex[:10],
                "name": name,
                "slot": str(slot or ""),
                "scenes": scenes or guess_scenes(name),
                "gender": gender if gender in ("女", "男", "通用") else "通用",
                "enabled": True,
                "note": str(note or "")[:120],
                "created": time.time(),
            }
            data["items"].append(item)
            data["items"] = data["items"][-MAX_ITEMS:]
            self._save()
            return dict(item)

    def update(self, item_id, **fields):
        with self._lock:
            data = self._load()
            for item in data["items"]:
                if item["id"] != str(item_id):
                    continue
                if "name" in fields:
                    name = clean_name(fields["name"])
                    if len(name) >= MIN_NAME:
                        item["name"] = name
                if "scenes" in fields:
                    scenes = [scene for scene in (fields["scenes"] or []) if scene in SCENES]
                    if scenes:
                        item["scenes"] = scenes
                if "gender" in fields and fields["gender"] in ("女", "男", "通用"):
                    item["gender"] = fields["gender"]
                if "enabled" in fields:
                    item["enabled"] = bool(fields["enabled"])
                if "note" in fields:
                    item["note"] = str(fields["note"] or "")[:120]
                self._save()
                return dict(item)
        return {}

    def delete(self, item_id):
        with self._lock:
            data = self._load()
            before = len(data["items"])
            data["items"] = [item for item in data["items"] if item["id"] != str(item_id)]
            if len(data["items"]) == before:
                return False
            self._save()
            return True

    def clear(self):
        with self._lock:
            self._data = {"items": []}
            self._save()

    # ---------- 挑选 ----------

    def pool(self, gender, scene):
        """这一场景能穿的衣服；性别不符的跳过（通用都算）。"""
        out = []
        for item in self.items(only_enabled=True):
            if item.get("gender") in ("女", "男") and gender in ("女", "男") and item["gender"] != gender:
                continue
            scenes = item.get("scenes") or []
            if scene and scene not in scenes:
                continue
            out.append(item["name"])
        return out

    def pick(self, gender, scene, day, key=""):
        """同一天同一场景固定一套，重启也不变。"""
        pool = self.pool(gender, scene)
        if not pool:
            return ""
        seed = ("%s|%s|%s" % (day, scene, key)).encode("utf-8")
        return pool[zlib.crc32(seed) % len(pool)]

    def match_text(self, text):
        """从一句话里认出「哪件衣服」；库里有才算。"""
        body = str(text or "")
        if not body:
            return {}
        hits = []
        for item in self.items(only_enabled=True):
            name = item["name"]
            if name and name in body:
                hits.append(item)
                continue
            # 「那条红裙子」：按名字里的关键词松匹配
            tokens = [token for token in re.split(r"[，,、\s]+", name) if len(token) >= 2]
            if any(token in body for token in tokens):
                hits.append(item)
        if not hits:
            return {}
        hits.sort(key=lambda item: len(item["name"]), reverse=True)
        return hits[0]

    def panel_data(self):
        items = self.items()
        return {
            "path": self.path,
            "count": len([item for item in items if item.get("enabled", True)]),
            "items": items,
            "scenes": [{"key": key, "label": SCENE_LABELS[key]} for key in SCENES],
        }
