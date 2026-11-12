# -*- coding: utf-8 -*-
"""照片分享引擎：旅游 / 逛街 / 周末 / 日常 / 早起穿搭。

她按日程过日子，这里只做一件事：在合适的「场景时刻」按配置概率，用万象画卷
（OmniDraw）生成一张照片发给他——要么是当地的街景/风景，要么是她自己的自拍。

- 概率都是 0-100 的整数，面板「照片」页可调；
- 每类时刻每天只掷一次骰子（``photo_roll:<日期>:<类别>:<地点>``），不会每 30 秒重掷；
- 每天总数受 ``photo_daily_cap`` 限制；
- 穿搭只在工作日早上出门那段时间触发，并且**一定是自拍**；
- 旅游/逛街/周末/日常按 ``photo_selfie_ratio`` 决定这张是自拍还是街景。

发送不依赖聊天事件：用 ``context.send_message(umo, chain)`` 主动发到最近活跃的会话。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import random
import time
import urllib.request

from astrbot.api import logger

try:  # 统一时区：容器/服务器常在 UTC 跑
    from .clock import now as _clock_now, today_str
except ImportError:  # 直接按文件加载时
    try:
        from clock import now as _clock_now, today_str
    except ImportError:  # pragma: no cover - 只在不完整的加载方式下走到
        from datetime import datetime as _dt

        def _clock_now(*args, **kwargs):
            return _dt.now()

        def today_str(*args, **kwargs):
            return _clock_now().date().isoformat()


try:  # 主模块有被吞异常计数，能复用就复用（既有的 amo_observability）
    from .amo_observability import note as _note_swallowed
except ImportError:
    try:
        from amo_observability import note as _note_swallowed
    except ImportError:
        def _note_swallowed(where, exc):
            logger.debug("[amo] %s 已忽略: %s", where, exc)


def now_ts():
    """与主模块同义；这里只是避免 import main 造成循环依赖。"""
    return time.time()


def quiet_now(spec):
    """免打扰时段：优先复用主模块的判断，拿不到再用同一套区间逻辑兜底。"""
    try:
        from . import main as _main
    except ImportError:
        _main = None
    fn = getattr(_main, "quiet_now", None)
    if callable(fn):
        try:
            return bool(fn(spec))
        except Exception:
            return False
    try:
        start, end = str(spec).split("-", 1)
        begin, finish = _hhmm(start), _hhmm(end)
    except Exception:
        return False
    current = _clock_now().hour * 60 + _clock_now().minute
    if begin <= finish:
        return begin <= current < finish
    return current >= begin or current < finish


def _hhmm(text):
    hour, minute = str(text).strip().split(":")[:2]
    return int(hour) * 60 + int(minute)


try:
    from astrbot.api.message_components import Image
except ImportError:  # 老版本/兼容路径
    try:
        from astrbot.api.event.components import Image
    except Exception:  # pragma: no cover
        Image = None

try:
    from astrbot.core.message.message_event_result import MessageChain
except Exception:  # pragma: no cover - 单测会注入桩
    MessageChain = None

GENERATE_TIMEOUT_SECONDS = 180
_MAX_IMAGE_BYTES = 16 * 1024 * 1024

TRAVEL_WORDS = ("旅游", "旅行", "景区", "景点", "古镇", "海边", "爬山", "公园", "游乐园")
SHOPPING_WORDS = ("逛街", "商场", "专柜", "步行街")
OUTFIT_CATEGORY = ("commute", "work")

# 同一天所有自拍都用同一套穿搭；按日期稳定挑选，换场景也不换衣服
OUTFIT_POOL = (
    "米色针织衫配牛仔裤",
    "白色衬衫配深色半裙",
    "浅灰卫衣配运动裤",
    "奶油色开衫配直筒裤",
    "黑色小高领配卡其色半裙",
    "牛仔外套配白色T恤和长裤",
    "浅蓝衬衫配米白阔腿裤",
    "粉色卫衣配牛仔裙",
    "燕麦色毛衣配深色半裙",
    "条纹长袖配浅色牛仔裤",
)


def _int_in(value, low, high, default):
    try:
        number = int(float(value))
    except Exception:
        return default
    return max(low, min(high, number))


PHOTO_INTENT_WORDS = (
    "拍照", "拍张", "拍个", "拍给我", "拍来看", "照片", "自拍",
    "看看你", "看看你在", "你在哪", "在哪呢",
)
PHOTO_PLACE_WORDS = (
    "公园", "商场", "咖啡", "学校", "公司", "家里", "街上", "海边", "餐厅",
    "超市", "地铁", "床上", "办公室", "图书馆", "电影院", "游乐园", "动物园",
    "植物园", "江边", "河边", "山上", "健身房", "教室", "宿舍", "路边", "小区",
)


class PhotoEngine:
    VIEWS = ("front", "side", "full")
    VIEW_LABELS = {"front": "正面", "side": "侧面", "full": "全身"}
    def __init__(self, plugin):
        self.plugin = plugin
        self._busy = False
        self._omni = None
        self._omni_checked = 0.0
        self._last_check = 0.0
        self._outfit_day = ""
        self._outfit_text = ""
        self._stats = {"sent": 0, "failed": 0, "rolled": 0}

    def _spawn(self, coro):
        try:
            spawned = self.plugin._spawn(coro)
            if spawned is not None:
                return spawned
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._spawn", _amo_exc)
        try:
            import asyncio

            return asyncio.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return None

    # ---------- 配置 ----------

    def _cfg_bool(self, key, default=False):
        try:
            return bool(self.plugin.cfg_bool(key, default))
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._cfg_bool", _amo_exc)
            return default

    def _cfg_int(self, key, default=0):
        try:
            return int(self.plugin.cfg_int(key, default))
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._cfg_int", _amo_exc)
            return default

    def _cfg_str(self, key, default=""):
        try:
            return str(self.plugin.cfg_str(key, default))
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._cfg_str", _amo_exc)
            return default

    @property
    def enabled(self):
        return self._cfg_bool("photo_enable", False)

    @property
    def debug(self):
        return self._cfg_bool("photo_debug", False)

    def _prob(self, key, default):
        return _int_in(self._cfg_int(key, default), 0, 100, default)

    # ---------- 日期 / 计数 ----------

    def _count_key(self, day):
        return "photo_count:%s" % day

    def today_count(self):
        try:
            return int(self.plugin.db.kv_get(self._count_key(today_str()), 0) or 0)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.today_count", _amo_exc)
            return 0

    def _bump_count(self):
        try:
            self.plugin.db.kv_set(self._count_key(today_str()), self.today_count() + 1)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._bump_count", _amo_exc)

    # ---------- 收件人 ----------

    def _owner_uid_ok(self, uid, profile):
        raw = self._cfg_str("photo_owner_ids", "")
        owners = {item.strip() for item in raw.replace("，", ",").split(",") if item.strip()}
        if owners:
            # 明确配了名单就只认名单，不再按关系放行
            return bool(uid) and uid in owners
        try:
            if uid and uid in getattr(self.plugin, "admin_uids", set()):
                return True
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._owner_uid_ok", _amo_exc)
        return str((profile or {}).get("relation") or "") == "相恋"

    def _profiles(self):
        try:
            rows = self.plugin.db.proactive_profiles(limit=50) or []
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._profiles", _amo_exc)
            rows = []
        picked = []
        for profile in rows:
            uid = str(profile.get("uid") or "")
            if not uid:
                continue
            if self._owner_uid_ok(uid, profile):
                picked.append(profile)
        if picked:
            return picked
        # 明确配了 photo_owner_ids 但一个都没匹配上：宁可不发，也不发给别人
        if self._cfg_str("photo_owner_ids", "").strip():
            return []
        # 没配名单、也没有相恋/管理员：只发她的主页私聊，不要发给陌生私聊
        home_umo = ""
        try:
            getter = getattr(self.plugin, "_first_private_umo", None)
            if callable(getter):
                home_umo = str(getter() or "")
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._profiles", _amo_exc)
        if not home_umo:
            return []
        return [row for row in rows if str(row.get("private_umo") or "") == home_umo]

    def _target_umo(self, profile):
        try:
            return str(self.plugin._pick_proactive_umo(profile) or "")
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._target_umo", _amo_exc)
            return str(profile.get("private_umo") or "")

    # ---------- 时刻判断 ----------

    def _now_parts(self):
        now = _clock_now()
        return now.weekday(), now.hour * 60 + now.minute

    def _activity(self):
        try:
            return self.plugin.state.current_activity() or {}
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._activity", _amo_exc)
            return {}

    def _worn_text(self):
        return ""

    def _candidates(self):
        """当前这一刻有哪些可分享的场景；返回 [(kind, scene, prob, key)]。"""
        activity = self._activity()
        act = str(activity.get("activity") or "")
        place = str(activity.get("place") or "")
        zone = str(activity.get("zone") or "")
        category = str(activity.get("category") or "")
        weekday, minutes = self._now_parts()
        blob = act + place + zone
        out = []

        if weekday < 5 and 7 * 60 <= minutes <= 9 * 60 + 30 and (
            zone == "road" or category in OUTFIT_CATEGORY or "上班" in blob or "通勤" in blob
        ):
            out.append(("outfit", "", self._prob("photo_outfit_prob", 70), "outfit"))

        scenic = zone == "scenic" or any(word in blob for word in TRAVEL_WORDS)
        mall = zone == "mall" or any(word in blob for word in SHOPPING_WORDS)
        if scenic:
            out.append(("travel", "%s·%s" % (place, act) if place else act,
                        self._prob("photo_travel_prob", 60), "travel:" + (place or act)))
        elif mall:
            out.append(("shopping", place or act, self._prob("photo_shopping_prob", 40), "shopping:" + (place or act)))

        if weekday >= 5 and 10 * 60 <= minutes <= 20 * 60:
            out.append(("weekend", "", self._prob("photo_weekend_prob", 50), "weekend"))

        if 9 * 60 <= minutes <= 21 * 60:
            # 有明确场景（旅游/逛街/周末）时不再补一张泛泛的日常照
            if not out:
                out.append(("daily", "", self._prob("photo_daily_prob", 25), "daily"))
        return out

    def _roll_key(self, kind, key):
        return "photo_roll:%s:%s:%s" % (today_str(), kind, key or "-")

    # ---------- 主循环 ----------

    def _cache_dir(self):
        base = os.path.dirname(str(getattr(self.plugin.db, "path", "") or ""))
        if not base:
            # 兜底也必须落在插件数据目录（不写插件安装目录、不写 cwd）
            plugin_dir = str(getattr(self.plugin, "plugin_dir", "") or "")
            name = os.path.basename(plugin_dir) or "Astrbot_Amo_forever"
            parent = os.path.dirname(plugin_dir)
            base = os.path.join(parent, "plugin_data", name) if parent else os.getcwd()
        path = os.path.join(base, "photo_cache")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._cache_dir", _amo_exc)
        return path

    def cleanup_cache(self):
        """只清理生图缓存；模板、聊天记录不动。"""
        days = self._cfg_int("photo_cache_days", 7)
        if days <= 0:
            return 0
        try:
            last = float(self.plugin.db.kv_get("photo_cache_cleanup", 0) or 0)
        except Exception:
            last = 0
        if time.time() - last < 3600:
            return 0
        cutoff = time.time() - days * 86400
        removed = 0
        cache_dir = self._cache_dir()
        try:
            for name in os.listdir(cache_dir):
                path = os.path.join(cache_dir, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                        os.remove(path)
                        removed += 1
                except Exception:
                    pass
            self.plugin.db.kv_set("photo_cache_cleanup", time.time())
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.cleanup_cache", _amo_exc)
        if removed:
            logger.info("[amo] 清理旧生图缓存 %d 张（保留 %d 天）" % (removed, days))
        return removed

    async def tick(self):
        try:
            self.cleanup_cache()
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.tick", _amo_exc)
        if not self.enabled or self._busy:
            return
        now = time.monotonic()
        if now - self._last_check < 20:
            return
        self._last_check = now
        try:
            if quiet_now(self._cfg_str("photo_quiet_hours", "23:00-07:00")):
                return
            cap = max(0, self._cfg_int("photo_daily_cap", 4))
            if self.today_count() >= cap:
                return
            profiles = self._profiles()
            if not profiles:
                return
            for kind, scene, prob, key in self._candidates():
                roll_key = self._roll_key(kind, key)
                try:
                    if self.plugin.db.kv_get(roll_key, 0):
                        continue
                    self.plugin.db.kv_set(roll_key, 1)
                except Exception as _amo_exc:
                    _note_swallowed("photo_engine.PhotoEngine.tick", _amo_exc)
                    continue
                self._stats["rolled"] += 1
                if random.random() * 100 >= prob:
                    if self.debug:
                        logger.info("[amo] 照片：%s 掷骰没中（%d%%）" % (kind, prob))
                    continue
                profile = random.choice(profiles)
                self._busy = True
                # 生图要几十秒，不能卡在 30 秒一轮的 tick 里；发完再放开
                if self._spawn(self._run_share(kind, scene, profile)) is None:
                    self._busy = False
                return
        except Exception as exc:
            logger.debug("[amo] 照片任务失败: %s" % exc)

    async def _run_share(self, kind, scene, profile):
        try:
            if not self.enabled:
                return
            cap = max(0, self._cfg_int("photo_daily_cap", 4))
            if self.today_count() >= cap:
                return
            await self._share(kind, scene, profile)
        finally:
            self._busy = False

    # ---------- 生成 / 发送 ----------

    @staticmethod
    def _clean_place(place):
        """日程里的 place 有时是「他桌面上」这种动作描述，不适合当拍照地点。"""
        place = str(place or "").strip()
        if not place:
            return ""
        if "桌" in place or place.startswith("他") or place.startswith("她"):
            return "家里"
        if len(place) > 16:
            return place[:16]
        return place

    def outfit_today(self):
        """今天的固定穿搭：同一天所有自拍都穿这一套，场景变了也不换。"""
        day = today_str()
        if self._outfit_day == day and self._outfit_text:
            return self._outfit_text
        key = "photo_outfit:" + day
        try:
            cached = str(self.plugin.db.kv_get(key, "") or "")
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.outfit_today", _amo_exc)
            cached = ""
        if cached:
            self._outfit_day = day
            self._outfit_text = cached
            return cached
        chooser = random.Random("amo-outfit:" + day)
        text = chooser.choice(OUTFIT_POOL)
        try:
            temp = float((getattr(self.plugin.state, "weather", {}) or {}).get("temp") or 0)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.outfit_today", _amo_exc)
            temp = 0.0
        if temp and temp <= 12:
            text += "，外面套了件大衣"
        elif temp and temp >= 28:
            text += "，天热穿得清爽"
        worn = self._worn_text()
        if worn:
            text += "，" + worn
        try:
            self.plugin.db.kv_set(key, text)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.outfit_today", _amo_exc)
        self._outfit_day = day
        self._outfit_text = text
        return text

    def _prompt_for(self, kind, scene, activity):
        prefix = self._cfg_str("photo_prompt_prefix", "手机随手拍，真实自然，生活感，")
        place = self._clean_place(activity.get("place"))
        act = str(activity.get("activity") or "")
        if kind == "outfit":
            return "自拍，穿着%s，在%s，自然光，手机前置摄像头，生活感" % (
                self.outfit_today(), place or "家门口"
            )
        if kind == "travel":
            return (prefix + (scene or act or "风景区") + "，风景照，自然光").strip("，")
        if kind == "shopping":
            return (prefix + (scene or "商场街边") + "，街景，生活感").strip("，")
        if kind == "weekend":
            return (prefix + (act or "周末出门走走") + "，街景，生活感").strip("，")
        return (prefix + (act or "日常生活") + ("，在" + place if place else "")).strip("，")

    def _selfie_prompt_for(self, kind, scene, activity):
        place = self._clean_place(activity.get("place"))
        act = str(activity.get("activity") or "")
        if kind == "travel":
            where = scene or place or "景点"
        elif kind == "shopping":
            where = scene or place or "商场"
        else:
            where = place or "家附近"
        return "自拍，穿着%s，在%s，%s，自然光，手机前置摄像头，生活感" % (
            self.outfit_today(), where, act or "随手拍"
        )

    def _find_omni(self):
        now = time.monotonic()
        if self._omni is not None and now - self._omni_checked < 60:
            return self._omni
        self._omni_checked = now
        self._omni = None
        try:
            context = getattr(self.plugin, "context", None)
            getter = getattr(context, "get_registered_star", None) if context else None
            if getter is None:
                return None
            meta = getter("astrbot_plugin_omnidraw")
            instance = getattr(meta, "star_cls", None) if meta else None
            if instance is not None and hasattr(instance, "generate_images_for_plugin"):
                self._omni = instance
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._find_omni", _amo_exc)
        return self._omni

    def _selfie_ready(self, omni):
        """她能不能出「自拍」：看万象画卷里有没有她的形象。

        不同版本的 OmniDraw 把形象放在不同地方（踩过坑：只认老字段时，
        新版照样有形象，但这里判成「没有」→ 自拍被降级成街景）：
        - 老版：``plugin_config.persona_ref_image`` / ``persona_base_prompt``；
        - 新版：``plugin_config.personas``（每项带 ``ref_images`` / 基底提示词），
          配置里落成 JSON 的 ``persona_config``；
        - 都没有时，看我们自己 ``templates/`` 里有没有三视图。
        """
        try:
            conf = getattr(omni, "plugin_config", None)
            if conf is not None:
                for key in ("persona_ref_image", "persona_base_prompt"):
                    if str(getattr(conf, key, "") or "").strip():
                        return True
                for profile in (getattr(conf, "personas", None) or []):
                    for key in ("ref_images", "persona_ref_image", "ref_image"):
                        value = getattr(profile, key, None)
                        if isinstance(value, (list, tuple, set)):
                            if any(str(item).strip() for item in value):
                                return True
                        elif str(value or "").strip():
                            return True
                    if str(getattr(profile, "persona_base_prompt", "") or "").strip():
                        return True
                raw = str(getattr(conf, "persona_config", "") or "").strip()
                if raw:
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = {}
                    if isinstance(data, dict):
                        active = str(data.get("active_persona_id") or "")
                        for profile in (data.get("profiles") or []):
                            if not isinstance(profile, dict):
                                continue
                            if active and str(profile.get("id") or "") not in ("", active):
                                continue
                            if (str(profile.get("persona_ref_image") or "").strip()
                                    or str(profile.get("persona_base_prompt") or "").strip()):
                                return True
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._selfie_ready", _amo_exc)
        # 最后看我们自己的模板：OmniDraw 那边没配形象时，三视图仍然是可用的参考
        try:
            return bool(self.persona_refs())
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._selfie_ready", _amo_exc)
            return False

    def _pick_selfie(self, kind):
        if kind == "outfit":
            return True
        ratio = self._prob("photo_selfie_ratio", 50)
        return random.random() * 100 < ratio

    async def _generate(self, omni, prompt, selfie):
        args = {"prompt": prompt, "count": 1, "record_usage": True}
        if selfie:
            args["mode"] = "selfie"
        try:
            result = await asyncio.wait_for(
                omni.generate_images_for_plugin(**args), timeout=GENERATE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("[amo] 照片生成超时（%d 秒）" % GENERATE_TIMEOUT_SECONDS)
            return None
        except Exception as exc:
            logger.warning("[amo] 照片生成失败（%s）: %s" % ("自拍" if selfie else "街景", exc))
            return None
        if isinstance(result, dict) and result.get("success") and result.get("images"):
            return result["images"][0]
        message = ""
        if isinstance(result, dict):
            message = str(result.get("message") or "")
        logger.warning("[amo] 照片没出来：%s" % (message or "未知原因"))
        return None

    @staticmethod
    def _image_component(item):
        if Image is None:
            return None
        data_url = str(item.get("data_url") or "")
        if data_url:
            payload = data_url.split(",", 1)[1] if "," in data_url else data_url
            try:
                return Image.fromBase64(payload)
            except Exception as _amo_exc:
                _note_swallowed("photo_engine.PhotoEngine._image_component", _amo_exc)
        path = str(item.get("file_path") or "")
        if path:
            try:
                return Image.fromFileSystem(path)
            except Exception as _amo_exc:
                _note_swallowed("photo_engine.PhotoEngine._image_component", _amo_exc)
        url = str(item.get("url") or item.get("image_url") or "")
        if url.startswith("http"):
            try:
                return Image.fromURL(url)
            except Exception as _amo_exc:
                _note_swallowed("photo_engine.PhotoEngine._image_component", _amo_exc)
        return None

    async def _send(self, umo, item):
        if not umo or MessageChain is None:
            return False
        component = self._image_component(item)
        if component is None:
            return False
        try:
            await self.plugin.context.send_message(umo, MessageChain([component]))
            return True
        except Exception as exc:
            logger.warning("[amo] 照片发送失败: %s" % exc)
            return False

    async def _generate_with(self, omni, profile, prompt, selfie):
        """有万象画卷就用它；没装就退回生图插件（Astrbot_Amo_Image）。"""
        if omni is not None:
            return await self._generate(omni, prompt, selfie)
        helper = getattr(self.plugin, "_image_bytes", None)
        if not callable(helper):
            logger.warning("[amo] 没有万象画卷，也没有生图插件，照片发不出去。")
            return None
        data = await helper(prompt, self._target_umo(profile), "")
        if not data:
            logger.warning("[amo] 生图插件没出图：%s" % prompt)
            return None
        return {"data_url": "data:image/png;base64," + base64.b64encode(data).decode()}

    async def _share(self, kind, scene, profile):
        activity = self._activity()
        omni = self._find_omni()
        if omni is None:
            logger.info("[amo] 没装万象画卷，改用生图插件出图。")
        selfie = self._pick_selfie(kind)
        if selfie and omni is not None and not self._selfie_ready(omni):
            selfie = False
        prompt = self._selfie_prompt_for(kind, scene, activity) if selfie else self._prompt_for(kind, scene, activity)
        if self._cfg_bool("photo_dry_run", False):
            logger.info("[amo] 照片（dry-run）%s：%s" % ("自拍" if selfie else "街景", prompt))
            return False
        item = await self._generate_with(omni, profile, prompt, selfie)
        if not item and selfie:
            # 自拍链路失败（没参考图/节点不支持）→ 退回普通图，别让这一次白掷
            item = await self._generate_with(
                omni, profile, self._prompt_for(kind, scene, activity), False)
        if not item:
            self._stats["failed"] += 1
            return False
        item = await self._localize(item)
        umo = self._target_umo(profile)
        if not await self._send(umo, item):
            self._stats["failed"] += 1
            return False
        self._bump_count()
        self._stats["sent"] += 1
        logger.info("[amo] 照片已分享（%s/%s）：%s" % (kind, "自拍" if selfie else "街景", prompt))
        return True

    async def share_now(self, kind="daily"):
        """面板「测试」/``/amo photo test``：无视概率，立刻按类别发一张。"""
        if not self.enabled:
            return "照片功能没开（photo_enable=false）。"
        if self._busy:
            return "还在画上一张，等它出来。"
        profiles = self._profiles()
        if not profiles:
            return "没有可发送的会话（先和他聊一句）。"
        activity = self._activity()
        kind = str(kind or "daily").strip() or "daily"
        scene = str(activity.get("place") or "") or "日常"
        if self._cfg_bool("photo_dry_run", False):
            if kind == "outfit":
                prompt = self._selfie_prompt_for(kind, scene, activity)
            else:
                prompt = self._prompt_for(kind, scene, activity)
            logger.info("[amo] 照片（dry-run）%s：%s" % (kind, prompt))
            return "🧪 dry-run：%s" % prompt
        self._busy = True
        try:
            ok = await self._share(kind, scene, random.choice(profiles))
        finally:
            self._busy = False
        return "✅ 发了一张（%s）" % kind if ok else "❌ 没发出去，看日志"

    def template_dir(self):
        """角色模板保存目录：默认插件目录下 templates/（跟着插件备份）。"""
        raw = self._cfg_str("photo_template_dir", "").strip()
        if raw:
            path = raw if os.path.isabs(raw) else os.path.join(str(self.plugin.plugin_dir), raw)
        else:
            path = os.path.join(str(self.plugin.plugin_dir), "templates")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.template_dir", _amo_exc)
        return path

    def _cfg_json(self, key):
        raw = self._cfg_str(key, "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _template_map(self):
        """三个视角各自的模板：{front/side/full: path}。"""
        data = self._cfg_json("photo_persona_refs")
        if not data:
            legacy = self._cfg_str("photo_persona_ref", "").strip()
            if legacy and os.path.exists(legacy):
                data = {"front": legacy}
        result = {
            view: path for view, path in data.items()
            if view in self.VIEWS and path and os.path.exists(path)
        }
        if result:
            return result
        # 配置里的文件丢了：按文件名把剩下的模板认回来，别把侧/全身当成正面
        recovered = {}
        try:
            root = self.template_dir()
            for name in os.listdir(root):
                lower = name.lower()
                if not lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                if "_side" in lower:
                    view = "side"
                elif "_full" in lower:
                    view = "full"
                elif "_front" in lower or lower.startswith("amo_persona."):
                    view = "front"
                else:
                    continue
                recovered.setdefault(view, os.path.join(root, name))
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._template_map", _amo_exc)
        return recovered

    def _save_template_map(self, mapping):
        try:
            self.plugin.config["photo_persona_refs"] = json.dumps(mapping, ensure_ascii=False)
            first = mapping.get("front") or next(iter(mapping.values()), "")
            self.plugin.config["photo_persona_ref"] = first
            if hasattr(self.plugin.config, "save_config"):
                self.plugin.config.save_config()
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._save_template_map", _amo_exc)

    def _enabled_map(self):
        data = self._cfg_json("photo_persona_enabled")
        result = {view: True for view in self.VIEWS}
        for view in self.VIEWS:
            result[view] = bool(data.get(view, True))
        return result

    def _save_enabled(self, mapping):
        try:
            self.plugin.config["photo_persona_enabled"] = json.dumps(mapping, ensure_ascii=False)
            if hasattr(self.plugin.config, "save_config"):
                self.plugin.config.save_config()
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._save_enabled", _amo_exc)

    def _kv_json(self, key):
        try:
            raw = self.plugin.db.kv_get(key, "{}") or "{}"
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_kv_json(self, key, data):
        try:
            self.plugin.db.kv_set(key, json.dumps(data, ensure_ascii=False))
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._save_kv_json", _amo_exc)

    def _stored_candidates(self):
        data = self._kv_json("photo_candidates")
        result = {}
        for view, item in (data or {}).items():
            if view not in self.VIEWS or not isinstance(item, dict):
                continue
            path = str(item.get("file") or "")
            if not path or not os.path.exists(path):
                continue
            result[view] = {
                "url": str(item.get("url") or ""),
                "file": path,
                "preview": self.preview_data_url({"file_path": path}),
            }
        return result

    def candidate(self, view):
        return self._stored_candidates().get(str(view or "").strip().lower()) or {}

    def set_candidate(self, view, item):
        if not isinstance(item, dict):
            return
        view = str(view or "").strip().lower()
        if view not in self.VIEWS:
            return
        data = self._kv_json("photo_candidates")
        data[view] = {
            "url": str(item.get("url") or ""),
            "file": str(item.get("file_path") or ""),
            "ts": time.time(),
        }
        self._save_kv_json("photo_candidates", data)

    def clear_candidate(self, view):
        view = str(view or "").strip().lower()
        data = self._kv_json("photo_candidates")
        if view in data:
            data.pop(view, None)
            self._save_kv_json("photo_candidates", data)

    def template_info(self):
        root = self.template_dir()
        plugin_dir = os.path.abspath(str(getattr(self.plugin, "plugin_dir", "") or ""))
        inside = bool(plugin_dir) and os.path.abspath(root).startswith(plugin_dir)
        files = []
        try:
            files = [name for name in os.listdir(root) if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        except Exception:
            files = []
        mapping = self._template_map()
        enabled = self._enabled_map()
        templates = {}
        for view in self.VIEWS:
            path = mapping.get(view, "")
            templates[view] = {
                "path": path,
                "preview": self.preview_data_url({"file_path": path}) if path else "",
                "enabled": bool(enabled.get(view, True)),
            }
        current = self.persona_ref()
        info = {
            "root": root, "inside_plugin": inside, "count": len(files),
            "current": current, "templates": templates,
            "candidates": self._stored_candidates(),
        }
        info["preview"] = templates.get("front", {}).get("preview", "")
        return info

    def persona_refs(self):
        mapping = self._template_map()
        if not mapping:
            # 老版本只存了一张：按「正面」迁移
            try:
                root = self.template_dir()
                files = [
                    os.path.join(root, name) for name in os.listdir(root)
                    if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ]
                if files:
                    mapping = {"front": max(files, key=os.path.getmtime)}
                    self._save_template_map(mapping)
            except Exception as _amo_exc:
                _note_swallowed("photo_engine.PhotoEngine.persona_refs", _amo_exc)
        enabled = self._enabled_map()
        refs = []
        for view in self.VIEWS:
            path = mapping.get(view)
            if path and enabled.get(view, True):
                refs.append(path)
        return refs

    def persona_ref(self):
        refs = self.persona_refs()
        return refs[0] if refs else ""

    def preview_data_url(self, item, size=512):
        """给面板预览用的小图（data URL），避免 <img> 直接连中转站。"""
        if not isinstance(item, dict):
            return ""
        path = str(item.get("file_path") or "")
        if not path or not os.path.exists(path):
            return ""
        try:
            from PIL import Image as PILImage

            with PILImage.open(path) as image:
                image.thumbnail((size, size))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=82)
            return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.preview_data_url", _amo_exc)
            return ""

    async def _localize(self, item):
        """把远端图片先落到本地，避免发送时 task1.65535.space 偶发连不上。"""
        if not isinstance(item, dict):
            return item
        if item.get("data_url"):
            return item
        path = str(item.get("file_path") or "")
        if path and os.path.exists(path):
            return item
        url = str(item.get("url") or item.get("image_url") or "")
        if not url.startswith("http"):
            return item
        cache_dir = self._cache_dir()
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine._localize", _amo_exc)
            return item
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        for _ in range(3):
            try:
                payload, content_type = await asyncio.to_thread(self._fetch_image, url)
                if "png" in content_type or payload[:8] == b"\x89PNG\r\n\x1a\n":
                    ext = ".png"
                elif "webp" in content_type or payload[:4] == b"RIFF":
                    ext = ".webp"
                else:
                    ext = ".jpg"
                target = os.path.join(cache_dir, digest + ext)
                with open(target, "wb") as handle:
                    handle.write(payload)
                copied = dict(item)
                copied["file_path"] = target
                return copied
            except Exception as _amo_exc:
                _note_swallowed("photo_engine.PhotoEngine._localize", _amo_exc)
                await asyncio.sleep(2)
        return item

    @staticmethod
    def _fetch_image(url):
        """线程里把图片读完再回来；事件循环里 read() 会把整条链路卡住。"""
        with urllib.request.urlopen(url, timeout=60) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            payload = response.read(_MAX_IMAGE_BYTES + 1)
        if len(payload) > _MAX_IMAGE_BYTES:
            raise ValueError("图片超过 %d MB，丢弃" % (_MAX_IMAGE_BYTES // (1024 * 1024)))
        return payload, content_type

    async def generate_custom(self, prompt, refs=None):
        """按提示词生成一张（可选带角色模板参考图），不发送。"""
        omni = self._find_omni()
        prompt = str(prompt or "").strip()
        if omni is None or not prompt:
            return None
        if refs is None:
            ref = self.persona_ref()
            refs = [ref] if ref else []
        refs = [item for item in refs if item]
        args = {"prompt": prompt, "count": 1, "event": None, "record_usage": False}
        if refs:
            args["refs"] = refs
            args["allow_local_refs"] = True
        try:
            result = await omni.generate_images_for_plugin(**args)
        except Exception as exc:
            logger.warning("[amo] 自定义生图失败: %s" % exc)
            result = None
        if not isinstance(result, dict) or not result.get("success"):
            # 中转偶发 502：等 3 秒重试一次
            await asyncio.sleep(3)
            try:
                result = await omni.generate_images_for_plugin(**args)
            except Exception as exc:
                logger.warning("[amo] 自定义生图重试失败: %s" % exc)
                return None
        if not isinstance(result, dict) or not result.get("success"):
            message = result.get("message") if isinstance(result, dict) else ""
            logger.warning("[amo] 自定义生图没出图: %s" % (message or "未知原因"))
            return None
        images = result.get("images") or []
        return await self._localize(images[0]) if images else None

    def _place_words(self):
        words = list(PHOTO_PLACE_WORDS)
        extra = self._cfg_str("draw_scene_keywords", "")
        for item in extra.replace("，", ",").split(","):
            item = item.strip()
            if item and item not in words:
                words.append(item)
        return words

    def _place_from_text(self, text):
        text = str(text or "")
        for word in self._place_words():
            if word in text:
                return word
        return ""

    def _recent_place(self):
        """看最近聊天里她自己说的地点，比如「我在公园散步」。"""
        uid = ""
        try:
            profiles = self._profiles()
            if profiles:
                uid = str(profiles[0].get("uid") or "")
        except Exception:
            uid = ""
        if not uid:
            return ""
        try:
            rows = self.plugin.db.messages_by_uid(uid, 30) or []
        except Exception:
            return ""
        words = self._place_words()
        for row in reversed(rows):
            if str(row.get("role") or "") != "bot":
                continue
            content = str(row.get("content") or "")
            for word in words:
                if word in content:
                    return word
        return ""

    def _scene_place(self):
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception:
            return ""
        place = str(activity.get("place") or "").strip()
        if "桌" in place or place.startswith(("他", "她")):
            return "家里"
        return place[:16]

    def smart_prompt(self, text):
        """面板输入像「拍照给我看看」时，自动补上她最近说的地点 + 今天的穿搭。"""
        raw = str(text or "").strip()
        if not any(word in raw for word in PHOTO_INTENT_WORDS):
            return raw
        concrete = raw
        for word in PHOTO_INTENT_WORDS + ("照片", "给我", "看看", "你", "吧", "呀", "啊", "嘛",
                                          "呢", "吗", "？", "?", "，", ",", "。", "！", "!"):
            concrete = concrete.replace(word, "")
        concrete = concrete.strip()
        if len(concrete) >= 4:
            # 已经描述了具体画面（如「在公园和狗狗玩」），保留原样
            return raw
        place = self._place_from_text(raw) or self._recent_place() or self._scene_place() or "家里"
        parts = ["自拍"]
        outfit = self.outfit_today()
        if outfit:
            parts.append("穿着" + outfit)
        parts.append("在" + place)
        parts.extend([
            "自然光", "手机前置摄像头", "生活感",
            "人物长相参考模板，衣服颜色和款式以文字为准，不要照搬模板里的衣服",
        ])
        return "，".join(parts)

    async def generate_prompt(self, prompt, send=False):
        """面板「按提示词生成」：画一张；send=True 时同时发到最近会话。"""
        text = self.smart_prompt(prompt)
        if text and not any(word in text for word in (
            "穿", "衣服", "裙", "衬衫", "毛衣", "外套", "卫衣", "裤", "围巾", "帽子",
        )):
            outfit = self.outfit_today()
            if outfit:
                text = "穿着%s，%s" % (outfit, text)
        if text and not any(word in text for word in ("二次元", "动漫", "插画")):
            prefix = self._cfg_str("photo_prompt_prefix", "").strip()
            if prefix:
                text = prefix + text
        if text and "不要照搬模板里的衣服" not in text:
            # 参考图只借长相，衣服必须按文字来，否则会照搬模板图里的穿搭
            text += "；人物长相参考模板，衣服颜色和款式以文字描述为准，不要照搬模板里的衣服"
        item = await self.generate_custom(text)
        if item and send:
            profiles = self._profiles()
            umo = self._target_umo(profiles[0]) if profiles else ""
            if umo:
                await self._send(umo, item)
        return item

    async def persona_sheet(self, view):
        """角色三视图：正面 / 侧面 / 全身。"""
        prompts = {
            "front": "角色设定图·正面：同一角色的正面站姿半身，二次元动漫风格，纯白背景，"
                     "五官清晰对称，蓝发蓝眼，鲸鱼鳍耳，日常服装，正对镜头",
            "side": "角色设定图·侧面：同一角色的侧面站姿半身，二次元动漫风格，纯白背景，"
                    "侧脸清晰，蓝发蓝眼，鲸鱼鳍耳，日常服装",
            "full": "角色设定图·全身：同一角色的正面全身站姿，二次元动漫风格，纯白背景，"
                    "从头到脚完整可见，蓝发蓝眼，鲸鱼鳍耳，日常服装",
        }
        refs = self.persona_refs()
        return await self.generate_custom(prompts.get(str(view), prompts["front"]), refs=refs)

    def _omni_native_config(self):
        try:
            base = os.path.dirname(str(self.plugin.db.path))
            data_root = os.path.dirname(os.path.dirname(base))
            return os.path.join(data_root, "config", "astrbot_plugin_omnidraw_config.json")
        except Exception:
            return ""

    def _sync_omni_refs(self):
        refs = self.persona_refs()
        omni = self._find_omni()
        if omni is None:
            return
        cfg = getattr(omni, "plugin_config", None)
        if cfg is not None:
            try:
                cfg.persona_ref_image = refs[0] if refs else ""
                cfg.persona_ref_images = list(refs)
                for profile in getattr(cfg, "personas", []) or []:
                    try:
                        profile.ref_images = list(refs)
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("[amo] 更新万象画卷内存人设失败: %s" % exc)
        paths = [getattr(omni, "config_path", ""), self._omni_native_config()]
        for persist in paths:
            if not persist or not os.path.exists(persist):
                continue
            try:
                data = json.load(open(persist, encoding="utf-8-sig"))
                persona = data.get("persona_config") or {}
                persona["persona_ref_image"] = list(refs)
                for profile in (persona.get("profiles") or []):
                    profile["persona_ref_image"] = list(refs)
                data["persona_config"] = persona
                json.dump(data, open(persist, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            except Exception as exc:
                logger.warning("[amo] 写万象画卷人设失败(%s): %s" % (os.path.basename(persist), exc))

    async def adopt_persona(self, url, view="front"):
        """把选中的三视图存成对应视角的模板，以后生图都用它。"""
        url = str(url or "").strip()
        if not url:
            return "缺少图片地址"
        omni = self._find_omni()
        if omni is None:
            return "没找到万象画卷"
        target_dir = self.template_dir()
        if url.startswith("http"):
            try:
                with await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=90)) as response:
                    payload = response.read()
                    content_type = str(response.headers.get("Content-Type") or "").lower()
            except Exception as exc:
                return "下载模板失败：%s" % exc
        elif os.path.isfile(url):
            try:
                payload = await asyncio.to_thread(lambda: open(url, "rb").read())
            except Exception as exc:
                return "读取本地模板失败：%s" % exc
            content_type = ""
        else:
            return "只支持 http 或本地图片"
        if "png" in content_type or payload[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif "webp" in content_type or payload[:4] == b"RIFF":
            ext = ".webp"
        else:
            ext = ".jpg"
        view = str(view or "front").strip().lower()
        if view not in self.VIEWS:
            view = "front"
        target = os.path.join(target_dir, "amo_persona_%s%s" % (view, ext))
        temp = target + ".tmp"
        try:
            with open(temp, "wb") as handle:
                handle.write(payload)
            for name in os.listdir(target_dir):
                if (name.startswith("amo_persona_" + view) and not name.endswith(".tmp")
                        and os.path.join(target_dir, name) != target):
                    try:
                        os.remove(os.path.join(target_dir, name))
                    except Exception:
                        pass
            os.replace(temp, target)
        except Exception as exc:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except Exception:
                pass
            return "保存模板失败：%s" % exc
        mapping = self._template_map()
        mapping[view] = target
        self._save_template_map(mapping)
        enabled = self._enabled_map()
        enabled[view] = True
        self._save_enabled(enabled)
        self._sync_omni_refs()
        label = self.VIEW_LABELS.get(view, view)
        return "✅ 已保存%s模板：%s" % (label, target)

    def set_template_enabled(self, view, enabled):
        view = str(view or "").strip().lower()
        if view not in self.VIEWS:
            return "未知视角"
        if view not in self._template_map():
            return "这个视角还没有模板"
        flags = self._enabled_map()
        flags[view] = bool(enabled)
        self._save_enabled(flags)
        self._sync_omni_refs()
        label = self.VIEW_LABELS.get(view, view)
        return "✅ %s模板已%s" % (label, "启用" if enabled else "停用")

    async def delete_persona(self, view=""):
        """删除某个视角（或全部）的角色模板。"""
        view = str(view or "").strip().lower()
        mapping = self._template_map()
        removed = []
        if view in self.VIEWS:
            targets = [mapping.pop(view, "")]
        else:
            targets = list(mapping.values())
            mapping = {}
        for path in targets:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    removed.append(path)
            except Exception:
                pass
        self._save_template_map(mapping)
        enabled = self._enabled_map()
        if view in self.VIEWS:
            enabled[view] = False
        else:
            enabled = {item: False for item in self.VIEWS}
        self._save_enabled(enabled)
        self._sync_omni_refs()
        label = self.VIEW_LABELS.get(view, "全部")
        return "✅ 已删除%s模板" % label if removed else "当前没有可删除的%s模板" % label

    def status_text(self):
        lines = [
            "📷 照片：%s%s" % ("开" if self.enabled else "关", "（dry-run）" if self._cfg_bool("photo_dry_run", False) else ""),
            "概率：穿搭 %d%%｜旅游 %d%%｜逛街 %d%%｜周末 %d%%｜日常 %d%%" % (
                self._prob("photo_outfit_prob", 70), self._prob("photo_travel_prob", 60),
                self._prob("photo_shopping_prob", 40), self._prob("photo_weekend_prob", 50),
                self._prob("photo_daily_prob", 25),
            ),
            "自拍占比：%d%%｜每天上限：%d｜今天已发：%d" % (
                self._prob("photo_selfie_ratio", 50), self._cfg_int("photo_daily_cap", 4), self.today_count(),
            ),
            "今日穿搭：" + self.outfit_today(),
            "万象画卷：%s" % ("已连接" if self._find_omni() is not None else "没找到"),
            "统计：发 %d｜失败 %d｜掷骰 %d" % (
                self._stats["sent"], self._stats["failed"], self._stats["rolled"],
            ),
        ]
        return "\n".join(lines)
