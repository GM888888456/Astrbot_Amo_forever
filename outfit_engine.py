# -*- coding: utf-8 -*-
"""日程穿搭：给每一段日程配一套衣服。

规则很短：

- 优先从服装库挑（他在面板里添的衣服），库是空的才用内置兜底；
- 按角色性别挑衣服（`outfit_gender`：自动 / 女 / 男，自动时从人格判断）；
- 按场景挑：睡觉/居家/上班/通勤/出门/运动/正式/海边；
- 同一段日程+同一天结果固定（crc32），重启不变，不会一小时换三套；
- **硬约束**：泳装只在海边/泳池/温泉出现，睡衣/家居服不出门；
  场景和服装对不上时退回日常装，宁可普通也不穿泳装去公司。

生成完写进日程条目的 `outfit` 字段，面板、`schedule_view`、生图插件都读它。
"""

from __future__ import annotations

import random

import re
import time
import zlib

try:  # 固定搭配规则在衣柜里定义
    from .wardrobe import pair_ok
except Exception:  # pragma: no cover - 单文件加载时的兜底
    try:
        from wardrobe import pair_ok
    except Exception:
        def pair_ok(slots):
            return True

FEMALE_POOLS = {
    "sleep": ("纯棉睡衣", "宽松家居服", "睡裙"),
    "home": ("家居卫衣配棉裤", "针织开衫配家居裤", "宽松T恤配短裤"),
    "work": ("白衬衫配西裤", "针织衫配半身裙", "西装外套配直筒裤", "雪纺衬衫配包臀裙"),
    "commute": ("风衣配牛仔裤", "针织开衫配长裤", "衬衫配休闲裤"),
    "casual": ("卫衣配牛仔裤", "T恤配半身裙", "牛仔外套配长裤"),
    "out": ("碎花连衣裙外搭薄开衫", "衬衫配半裙", "卫衣配阔腿裤", "T恤配牛仔裤"),
    "sport": ("运动T恤配速干裤", "运动套装配跑鞋"),
    "formal": ("黑色小礼服", "衬衫配西装裤", "针织连衣裙"),
    "beach": ("泳装外搭防晒衫", "连体泳衣配沙滩裙", "泳装配沙滩裤"),
}

MALE_POOLS = {
    "sleep": ("纯棉睡衣", "宽松家居服"),
    "home": ("家居卫衣配棉裤", "宽松T恤配短裤"),
    "work": ("白衬衫配西裤", "针织衫配休闲裤", "西装外套配直筒裤"),
    "commute": ("夹克配牛仔裤", "针织开衫配长裤", "衬衫配休闲裤"),
    "casual": ("卫衣配牛仔裤", "T恤配工装裤", "牛仔外套配长裤"),
    "out": ("衬衫配休闲裤", "卫衣配阔腿裤", "T恤配牛仔裤"),
    "sport": ("运动T恤配速干裤", "运动套装配跑鞋"),
    "formal": ("西装套装", "衬衫配西装裤", "针织衫配西裤"),
    "beach": ("泳裤配防晒衫", "泳裤配沙滩裤"),
}

SWIM_WORDS = ("泳装", "泳衣", "泳裤", "比基尼")
HOME_WEAR_WORDS = ("睡衣", "家居服", "睡裙")
BEACH_PLACES = ("海边", "沙滩", "泳池", "游泳馆", "温泉", "海滩", "水上乐园")
BEACH_ACTIVITIES = ("游泳", "泡温泉", "玩水", "潜水", "冲浪")
HOME_PLACE_WORDS = ("家", "小窝", "公寓", "住处", "宿舍", "房间")


# 贴身穿的 / 睡觉穿的：在外面不能换，换了也不能说
PRIVATE_WEAR_WORDS = (
    "睡衣", "睡裙", "睡袍", "家居服", "内衣", "文胸", "胸罩", "内裤", "吊带",
    "丝袜", "比基尼", "泳装", "泳衣", "泳裤", "浴巾", "浴袍",
)
HOME_PLACES = ("家", "小窝", "公寓", "住处", "宿舍", "房间", "卧室")


def is_private_wear(name):
    return any(word in str(name or "") for word in PRIVATE_WEAR_WORDS)


def at_home(activity):
    """按日程判断她此刻是不是在家（含卧室/宿舍这类）。"""
    activity = activity or {}
    place = str(activity.get("place") or "")
    zone = str(activity.get("zone") or "")
    if zone in ("home", "bedroom"):
        return True
    return any(word in place for word in HOME_PLACES)


class OutfitEngine:
    """按性别 + 场景 + 日期给日程配衣服。"""

    def __init__(self, plugin):
        self.plugin = plugin

    # ---------- 性别 ----------

    def enabled(self):
        try:
            return bool(self.plugin.cfg_bool("outfit_enable", True))
        except Exception:
            return True

    def gender(self, persona=""):
        value = ""
        try:
            value = str(self.plugin.cfg_str("outfit_gender", "自动") or "自动").strip()
        except Exception:
            value = "自动"
        if value in ("女", "女生", "female"):
            return "女"
        if value in ("男", "男生", "male"):
            return "男"
        return self._guess_gender(persona)

    @staticmethod
    def _guess_gender(text):
        raw = str(text or "")
        female = sum(raw.count(word) for word in
                     ("女孩", "女生", "少女", "女性", "姑娘", "妻子", "老婆", "她"))
        male = sum(raw.count(word) for word in ("男孩", "男生", "少年", "男性"))
        return "男" if male > female else "女"

    # ---------- 场景 ----------

    @staticmethod
    def scene_of(item):
        activity = str(item.get("activity") or "")
        place = str(item.get("place") or "")
        category = str(item.get("category") or "")
        text = activity + place
        if category == "sleep" or "睡觉" in activity or "睡衣" in activity or "睡裙" in activity:
            return "sleep"
        if (any(word in place for word in BEACH_PLACES)
                or any(word in activity for word in BEACH_ACTIVITIES)):
            return "beach"
        if category == "sport" or any(word in text for word in ("健身", "跑步", "运动", "瑜伽")):
            return "sport"
        if category == "work" or any(word in text for word in ("上班", "公司", "开会", "办公")):
            return "work"
        if any(word in text for word in ("婚礼", "宴会", "年会", "正式", "面试")):
            return "formal"
        if category in ("play", "social") or any(
                word in text for word in ("逛街", "商场", "旅", "景点", "咖啡", "公园", "约会")):
            return "out"
        if category == "commute" or any(word in text for word in ("通勤", "地铁", "开车去", "回家路上")):
            return "commute"
        if place in ("家", "") or any(word in place for word in HOME_PLACE_WORDS):
            return "home"
        return "casual"

    def wardrobe(self):
        return getattr(self.plugin, "wardrobe", None)

    def _pool(self, gender, scene):
        """先看服装库；库空或该场景没衣服，才回落到内置兜底。"""
        store = self.wardrobe()
        if store is not None:
            try:
                names = store.pool(gender, scene)
                if names:
                    return tuple(names)
            except Exception:
                pass
        pools = FEMALE_POOLS if gender == "女" else MALE_POOLS
        return pools.get(scene) or pools["casual"]

    def _pick(self, gender, scene, day, key=""):
        """同一段（同场景+同活动+同地点）在同一天固定穿同一套，小时展开不会一小时一换。"""
        pool = self._pool(gender, scene)
        seed = ("%s|%s|%s|%s" % (day, scene, key, gender)).encode("utf-8")
        return pool[zlib.crc32(seed) % len(pool)]

    @staticmethod
    def _safe(outfit, scene):
        """硬约束：泳装只下海，睡衣不出门。"""
        if any(word in outfit for word in SWIM_WORDS) and scene != "beach":
            return ""
        if any(word in outfit for word in HOME_WEAR_WORDS) and scene not in ("sleep", "home"):
            return ""
        return outfit

    CHANGE_WORDS = ("换衣", "换装", "换上", "换一身", "洗澡")
    # 只有这种「不得不换」才算数；普通换衣服不换造型
    EMERGENCY_WORDS = ("淋湿", "打湿", "湿透", "弄脏", "洒了", "糊了", "摔倒",
                       "泥", "雨太大", "淋雨", "脏了")

    def day_scene(self, items):
        """今天的主场景：上班日按上班，出去玩按出门，其余日常。"""
        scenes = []
        for item in items or []:
            scene = self.scene_of(item)
            if scene not in ("sleep",):
                scenes.append(scene)
        for scene in ("work", "formal", "sport", "out", "commute"):
            if scene in scenes:
                return scene
        if scenes and all(scene == "home" for scene in scenes):
            return "home"
        return "casual" if scenes else "home"

    # ---------- 手动换装 ----------

    @staticmethod
    def _override_key(day):
        return "outfit_override:" + str(day)

    def override(self, day):
        """他今天让她换的那套：{"name": "...", "from": "18:00"}。"""
        try:
            value = self.plugin.db.kv_get(self._override_key(day), {}) or {}
        except Exception:
            value = {}
        if not isinstance(value, dict) or not str(value.get("name") or "").strip():
            return {}
        return {"name": str(value.get("name")).strip(),
                "from": str(value.get("from") or "00:00")[:5],
                "ts": float(value.get("ts") or 0)}

    def change_outfit(self, day, name, from_hour="", note=""):
        """他让她换一套：写进今天，从这一小时开始生效，直到睡觉。"""
        name = str(name or "").strip()[:40]
        if not name:
            return {}
        hour = str(from_hour or time.strftime("%H:00"))[:5]
        if not re.match(r"^\d{2}:\d{2}$", hour):
            hour = time.strftime("%H:00")
        payload = {"name": name, "from": hour, "ts": time.time(), "note": str(note or "")[:80]}
        try:
            self.plugin.db.kv_set(self._override_key(day), payload)
        except Exception:
            pass
        return payload

    def can_change_to(self, name):
        """能不能现在换成这套。返回 (ok, 原因)。

        贴身衣物 / 睡衣在门外不能换——不然会出现「在公司穿上睡衣」这种画面。
        """
        if not is_private_wear(name):
            return True, ""
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception:
            activity = {}
        if at_home(activity):
            return True, ""
        place = str(activity.get("place") or "").strip() or "外面"
        return False, place

    def clear_override(self, day):
        try:
            self.plugin.db.kv_set(self._override_key(day), {})
        except Exception:
            pass

    def _apply_override(self, items, day):
        """把手动换的那套写回日程：从那一小时到睡觉前都穿它。"""
        data = self.override(day)
        if not data:
            return items
        start = self._minutes(data["from"])
        for item in items:
            if not isinstance(item, dict):
                continue
            if self.scene_of(item) == "sleep":
                if self._minutes(item.get("start")) >= start:
                    break
                continue
            if self._minutes(item.get("start")) >= start:
                item["outfit"] = data["name"]
        return items

    @staticmethod
    def _minutes(text):
        try:
            hour, minute = str(text or "").split(":")[:2]
            return int(hour) * 60 + int(minute)
        except Exception:
            return 0

    def _slot_items(self):
        """衣柜里带 slot 的条目；没有就走旧的整件挑。"""
        try:
            rows = [row for row in (self.wardrobe.items() or [])
                    if row.get("slot") and row.get("enabled", True)]
        except Exception:
            rows = []
        return rows

    def _compose(self, scene: str, day, gender: str) -> str:
        """按槽位拼一套：裙子优先整件，JK 用衬衣+格裙，其余上衣+裤子；再配鞋袜。"""
        rows = self._slot_items()
        if not rows:
            return self._pick(gender, scene, day, "day")
        chooser = random.Random("amo-look:%s:%s" % (str(day), scene))

        def pick_slot(slot, pool=None):
            candidates = [row for row in rows
                          if row.get("slot") == slot
                          and row.get("enabled", True)
                          and (not pool or any(sc in (row.get("scenes") or []) for sc in pool))]
            return chooser.choice(candidates)["name"] if candidates else ""

        if scene == "sleep":
            return pick_slot("dress") or pick_slot("top") or "纯棉睡衣"
        if scene == "sport":
            top = pick_slot("top", ["sport"]) or pick_slot("top")
            bottom = pick_slot("bottom", ["sport"]) or pick_slot("bottom")
            shoes = pick_slot("shoes") or ""
            socks = pick_slot("socks") or ""
            return "，".join(x for x in (top, bottom, socks, shoes) if x)
        if scene in ("formal", "out") and chooser.random() < 0.5:
            dress = pick_slot("dress")
            if dress:
                shoes = pick_slot("shoes")
                return "，".join(x for x in (dress, shoes) if x)
        if scene == "casual" and chooser.random() < 0.35:
            shirt = pick_slot("jk_shirt")
            skirt = pick_slot("jk_skirt")
            # 固定搭配：JK 衬衣只在有 JK 格裙时才穿，否则退回普通上衣+裤子
            if shirt and skirt:
                socks = pick_slot("socks") or ""
                shoes = pick_slot("shoes") or ""
                return "，".join(x for x in (shirt, skirt, socks, shoes) if x)
        top = pick_slot("top")
        bottom = pick_slot("bottom")
        socks = pick_slot("socks") or ""
        shoes = pick_slot("shoes") or ""
        if not pair_ok(["top", "bottom"]):
            bottom = ""
        return "，".join(x for x in (top, bottom, socks, shoes) if x)

    def assign(self, items, day, persona=""):
        """给日程写 `outfit`。

        - 出门在外（上班/通勤/吃饭/逛街）一天一套，上午下午不换；
        - 在家换家居服，睡觉换睡衣；
        - 海边/泳池那几个小时单独泳装；
        - 只有「淋湿/弄脏 + 回家换衣服」才把外出那套换掉。
        """
        if not isinstance(items, list):
            return items
        if not self.enabled():
            return items
        gender = self.gender(persona)
        base_scene = self.day_scene(items)
        pair = self._compose(base_scene, day, gender)
        backup = self._compose(base_scene, "%s-b" % day, gender)
        homewear = self._compose("home", day, gender)
        sleepwear = self._compose("sleep", day, gender)
        variant = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            activity = str(item.get("activity") or "")
            scene = self.scene_of(item)
            if scene == "sleep":
                item["outfit"] = sleepwear
                continue
            if (any(word in activity for word in self.EMERGENCY_WORDS)
                    and any(word in activity for word in self.CHANGE_WORDS)):
                variant += 1
            if scene == "home":
                item["outfit"] = homewear
                continue
            if scene == "beach":
                item["outfit"] = self._pick(gender, "beach", day, "beach")
                continue
            outfit = pair if variant == 0 else backup
            item["outfit"] = self._safe(outfit, base_scene) or self._pick(gender, "casual", day, "day")
        return self._apply_override(items, day)

    def for_activity(self, activity, day, persona=""):
        """给单条活动算一套（current_activity 兜底、面板试算用）。"""
        if not isinstance(activity, dict) or not activity:
            return ""
        if not self.enabled():
            return str(activity.get("outfit") or "")
        day = str(day or "")
        data = self.override(day) if day else {}
        if data and self._minutes(activity.get("start")) >= self._minutes(data["from"]):
            if self.scene_of(activity) != "sleep":
                return data["name"]
        scene = self.scene_of(activity)
        key = "%s|%s" % (activity.get("place") or "", scene)
        outfit = self._safe(self._pick(self.gender(persona), scene, day, key), scene)
        return outfit or self._pick(self.gender(persona), "casual", day, key)
