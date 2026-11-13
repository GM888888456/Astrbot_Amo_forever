# -*- coding: utf-8 -*-
"""照片辅助：今日穿搭 + 图片落地缓存。

主动分享、场景概率、万象画卷人设/模板/参考图这一整套已经搬走了：

- **判定**在终端（`main.py` 的 ``_share_decision`` / ``draw_engine``，本地规则 + 心流）；
- **出图**在生图插件（``Astrbot_Amo_Image.draw_for``）；
- 这里只留两件被复用的小事：同一天所有自拍穿同一套衣服（``outfit_today``），
  以及把远端图片先落盘再发（``_localize``，避免发送时连不上图床）。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import urllib.request

from astrbot.api import logger

try:  # 统一时区：容器/服务器常在 UTC 跑
    from .clock import today_str
except ImportError:  # 直接按文件加载时
    try:
        from clock import today_str
    except ImportError:  # pragma: no cover - 只在不完整的加载方式下走到
        from datetime import datetime as _dt

        def today_str(*args, **kwargs):
            return _dt.now().date().isoformat()


try:  # 主模块有被吞异常计数，能复用就复用
    from .amo_observability import note as _note_swallowed
except ImportError:
    try:
        from amo_observability import note as _note_swallowed
    except ImportError:
        def _note_swallowed(where, exc):
            logger.debug("[amo] %s 已忽略: %s", where, exc)


_MAX_IMAGE_BYTES = 16 * 1024 * 1024

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


class PhotoEngine:
    """只管「今天穿什么」和「图先落地」，不做任何判定、不发消息。"""

    def __init__(self, plugin):
        self.plugin = plugin
        self._outfit_day = ""
        self._outfit_text = ""

    @property
    def enabled(self):
        """照片辅助是否可用（老配置 photo_enable 保留兼容，默认开）。"""
        try:
            return bool(self.plugin.cfg_bool("photo_enable", True))
        except Exception:
            return True

    # ---------- 今日穿搭 ----------

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
        try:
            self.plugin.db.kv_set(key, text)
        except Exception as _amo_exc:
            _note_swallowed("photo_engine.PhotoEngine.outfit_today", _amo_exc)
        self._outfit_day = day
        self._outfit_text = text
        return text

    # ---------- 图片落地 ----------

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

    async def _localize(self, item):
        """把远端图片先落到本地，避免发送时图床偶发连不上。"""
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
