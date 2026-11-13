# -*- coding: utf-8 -*-
"""城市跟随：他说「我在X / 我到X / 我回X」时，把她所在的城市换成 X。

只认这三种明确说法；闲聊里提到城市（「广州那边下雨了」「明天去广州」）一律不触发。
城市名走 amo_city_index 的离线表，重名的不自动猜（「南山」不认，要写「深圳南山」）。
"""

from __future__ import annotations

import re

try:  # 包内加载（AstrBot 正常路径）：必须走包内相对导入
    from . import amo_city_index
except ImportError:  # 直接按文件加载时（单测/脚本）
    import amo_city_index

# 句尾语气词：「我到清远了」「我回东莞啦」
_TAIL = "了啦咯呀啊呢吧嘛哦噢"
# 城市名后面紧跟这些字，说明是路名/街名（北京路、广州街），不是城市
_STREET = "路街巷弄"
# 一句话里先粗抓「我(在|到|回)后面的一串」，再在城市表里找最长能解析的前缀
_PATTERNS = (
    re.compile(r"我(?:人)?(?:现在|已经|还|也)?在\s*(?P<loc>[^，。！？；：、,.!?;:\s]{2,16})"),
    re.compile(r"我(?:已经|刚)?到\s*了?(?P<loc>[^，。！？；：、,.!?;:\s]{2,16})"),
    re.compile(r"我(?:要|得|先|准备|刚)?回\s*(?P<loc>[^，。！？；：、,.!?;:\s]{2,16})"),
)


def _strip_tail(text: str) -> str:
    return text.rstrip(_TAIL)


def _display_name(hit, name: str, raw: str = "") -> str:
    """区县级的命中带上所属市（「深圳南山」「清远清城区」），市/省/近似命中就用原名。"""
    city = str(hit.get("city") or "").strip()
    try:
        level = int(hit.get("level") or 1)
    except Exception:
        level = 1
    if level >= 2 and city:
        stem = city[:-1] if city.endswith("市") else city
        if stem and stem != name:
            label = stem + name
            text = str(raw or "")
            for suffix in ("区", "县", "市", "镇"):
                if text.endswith(suffix) and not name.endswith(suffix):
                    label += suffix
                    break
            return label
    return name


def _prefer_ambiguous(piece: str, prefer_city: str):
    """重名时用他当前所在城市消歧：「广州」+「白云区」→ 广州白云区。"""
    prefer = str(prefer_city or "").strip()
    if not prefer:
        return None
    for sep in ("", "市"):
        try:
            alt = amo_city_index.resolve_city(_stem_name(prefer) + sep + piece)
        except Exception:
            alt = None
        if alt and int(alt.get("ambiguous") or 0) <= 1 and str(alt.get("id") or "").strip():
            return alt
    return None


def _resolve_prefix(raw: str, prefer_city: str = ""):
    """从左往右找最长能解析成城市的片段（「广州出差」→ 广州）。

    - 重名（ambiguous > 1）优先用他当前城市消歧，仍不唯一就不猜；
    - 「北京路」这种把城市名当路名用的不认（命中项的尾巴以路/街/巷开头即弃）。
    """
    for cut in range(len(raw), 1, -1):
        piece = raw[:cut]
        nxt = raw[cut:cut + 1]
        if nxt and nxt in _STREET:
            continue
        hit = amo_city_index.resolve_city(piece)
        if not hit:
            continue
        if int(hit.get("ambiguous") or 0) > 1:
            hit = _prefer_ambiguous(piece, prefer_city)
            if not hit:
                continue
        if not str(hit.get("id") or "").strip():
            continue
        tail = piece[len(str(hit.get("match") or "")):]
        if tail and tail[0] in _STREET:
            continue
        return hit
    return None


def detect_city(text, prefer_city: str = ""):
    """识别「我在X / 我到X / 我回X」。

    prefer_city 是他当前所在城市，用来给重名的区县消歧（「白云区」+ 广州）。
    返回 {"name": 城市名, "id": LocationID, "raw": 原词}；识别不了返回 None。
    """
    body = str(text or "")
    if not body:
        return None
    for pattern in _PATTERNS:
        for match in pattern.finditer(body):
            raw = _strip_tail(match.group("loc"))
            if len(raw) < 2:
                continue
            hit = _resolve_prefix(raw, prefer_city)
            if not hit:
                continue
            name = str(hit.get("name") or "").strip()
            city_id = str(hit.get("id") or "").strip()
            if not name or not city_id:
                continue
            return {"name": _display_name(hit, name, raw), "id": city_id, "raw": raw}
    return None


def compose_block(city) -> str:
    """她在的城市 → 注入给模型的一段话；空值返回空串。"""
    name = str(city or "").strip()
    if not name:
        return ""
    return (
        "【你们在】你和他在 " + name + "。你俩同城：你说“我这边/我们这边/回家”就是这个城市，"
        "聊通勤、天气、地址都按这里说；他随口提到的别的城市不算。"
    )


DEFAULT_CITY = "东莞"

# 回到东莞后的今天剩余时段（换城回来用）
_HOME_DAY = (
    (0, "睡觉", "他桌面上", "home", "sleep"),
    (7, "赖床刷手机", "他桌面上", "home", "rest"),
    (8, "起床洗漱", "他桌面上", "home", "life"),
    (10, "窝着看剧", "他桌面上", "home", "rest"),
    (12, "点外卖吃午饭", "他桌面上", "home", "meal"),
    (14, "窝沙发刷手机", "他桌面上", "home", "rest"),
    (18, "点外卖吃晚饭", "他桌面上", "home", "meal"),
    (20, "听歌发呆", "他桌面上", "home", "rest"),
    (23, "睡觉", "他桌面上", "home", "sleep"),
)


def _stem_name(text) -> str:
    """城市名归一：去掉末尾的市/区/县，方便和景点数据的 city 对齐。"""
    name = str(text or "").strip()
    for suffix in ("市", "区", "县", "自治州", "地区"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def pick_spots(all_spots, city, seed="", count: int = 2):
    """从真实景点库里挑这个城市的景点（按 seed 固定，同一天不变）。

    只做名字匹配，不编造；没有这个城市的数据就返回空列表，调用方退化成"随便逛逛"。
    """
    city_stem = _stem_name(city)
    rows = []
    for row in (all_spots or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        spot_city = _stem_name(row.get("city") or "")
        if not city_stem or not spot_city:
            continue
        if spot_city != city_stem and city_stem not in spot_city and spot_city not in city_stem:
            continue
        rows.append(row)
    if not rows:
        return []
    import hashlib

    def _key(row):
        raw = "%s|%s|%s" % (seed, city_stem, row.get("name") or "")
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    rows.sort(key=_key)
    return rows[: max(0, int(count or 0))]


def _spot_project(spot, index: int = 0) -> str:
    projects = [str(x).strip() for x in (spot.get("projects") or []) if str(x).strip()]
    if not projects:
        return ""
    return projects[index % len(projects)]


def _travel_plan(city, weekday: bool, spots):
    """出行日模板：有真实景点就用真名，没有就"城里随便逛"，不虚构景点名。"""
    name = str(city or "").strip()
    spots = [s for s in (spots or []) if isinstance(s, dict) and str(s.get("name") or "").strip()]
    leave = "给公司发消息请了假，洗漱收拾" if weekday else "起床洗漱，拉开窗帘看外面的城"
    plan = [
        (0, "在他电脑里睡着", "酒店房间", "hotel", "sleep"),
        (7, "醒来看他还在睡，窝着刷手机", "酒店房间", "hotel", "rest"),
        (8, leave, "酒店房间", "hotel", "life"),
    ]
    if spots:
        first = spots[0]
        second = spots[1] if len(spots) > 1 else None
        f_name = str(first.get("name") or "").strip()
        f_area = str(first.get("area") or "").strip()
        f_place = ("%s·%s" % (f_area, f_name)) if f_area and f_area not in name else ("%s·%s" % (name, f_name))
        plan.append((9, "跟他一起出门，先去" + f_name, f_place, "scenic", "play"))
        plan.append((10, "逛" + f_name + "：" + (_spot_project(first, 0) or "慢慢走慢慢看"), f_place, "scenic", "play"))
        plan.append((11, "在" + f_name + "继续逛：" + (_spot_project(first, 1) or "拍照"), f_place, "scenic", "play"))
        plan.append((12, "景区附近吃当地菜", name + "·小馆子", "restaurant", "meal"))
        plan.append((13, "回酒店歇一会儿", "酒店房间", "hotel", "rest"))
        if second:
            s_name = str(second.get("name") or "").strip()
            s_area = str(second.get("area") or "").strip()
            s_place = ("%s·%s" % (s_area, s_name)) if s_area and s_area not in name else ("%s·%s" % (name, s_name))
            plan.append((14, "下午去" + s_name, s_place, "scenic", "play"))
            plan.append((15, "逛" + s_name + "：" + (_spot_project(second, 0) or "慢慢走"), s_place, "scenic", "play"))
        else:
            plan.append((14, "下午再去" + f_name + "转转", f_place, "scenic", "play"))
            plan.append((15, "在" + f_name + "边逛边拍照", f_place, "scenic", "play"))
        plan.append((16, "找家咖啡店坐坐", name + "·咖啡店", "cafe", "rest"))
    else:
        plan.append((9, "跟他一起出门，先去转转", "街头", "street", "play"))
        plan.append((10, "在" + name + "随便逛，走到哪算哪", "街头", "street", "play"))
        plan.append((11, "路边小店看看，买瓶水", "小店", "street", "play"))
        plan.append((12, "找家小馆子吃当地菜", "小馆子", "restaurant", "meal"))
        plan.append((13, "回酒店歇一会儿", "酒店房间", "hotel", "rest"))
        plan.append((14, "下午去公园走走", "公园", "park", "play"))
        plan.append((15, "在公园坐一会儿", "公园", "park", "rest"))
        plan.append((16, "找家咖啡店坐坐", "咖啡店", "cafe", "rest"))
    plan += [
        (17, "回酒店等他忙完", "酒店房间", "hotel", "rest"),
        (19, "晚饭点当地的", "小馆子", "restaurant", "meal"),
        (20, "窝在床上刷手机", "酒店房间", "hotel", "rest"),
        (22, "洗澡护肤", "酒店房间", "hotel", "life"),
        (23, "在他电脑里睡", "酒店房间", "hotel", "sleep"),
    ]
    return plan


def _plan_item(plan, hour: int):
    picked = plan[0]
    for row in plan:
        if row[0] <= hour:
            picked = row
        else:
            break
    return picked


def travel_events(city, from_hour: int = 0, home: bool = False, weekday: bool = False, spots=None,
                  until_hour: int = 24):
    """出行覆盖层：从 from_hour 到 23 点的日程（旅游；有真实景点就用真名）。

    周末算旅游（白天自己逛景区）；工作日先请假跟去，白天也自己去景区。
    纯函数，方便单测；返回的字段和 schedule 引擎一致。
    """
    name = str(city or "").strip()
    if home:
        plan = _HOME_DAY
    else:
        plan = _travel_plan(name, bool(weekday), spots)
    try:
        start = int(from_hour or 0)
    except (TypeError, ValueError):
        start = 0
    start = max(0, min(23, start))
    try:
        stop = int(until_hour or 24)
    except (TypeError, ValueError):
        stop = 24
    stop = max(0, min(24, stop))
    items = []
    for hour in range(start, stop):
        _hour, activity, place, zone, category = _plan_item(plan, hour)
        if place in ("酒店房间", "街头", "小店", "小馆子", "公园", "咖啡店"):
            place = name + "·" + place
        items.append({
            "start": "%02d:00" % hour,
            "end": "24:00" if hour == 23 else "%02d:00" % (hour + 1),
            "activity": activity,
            "place": place,
            "zone": zone,
            "category": category,
            "mood": "平静",
            "mood_valence": 76.0,
            "effects": {},
        })
    return items


def travel_action(name, had_travel: bool = False) -> str:
    """换城之后要不要进入/退出出行模式：enter / exit / none。

    在东莞（默认城市）本身不触发；只有本来在出行中才需要"回家"覆盖。
    """
    city = str(name or "").strip()
    if not city:
        return "none"
    if city == DEFAULT_CITY:
        return "exit" if had_travel else "none"
    return "enter"


def travel_block(city, weekday: bool = False, spots=None) -> str:
    """出行模式注入给模型的一段话；空值返回空串。"""
    name = str(city or "").strip()
    if not name:
        return ""
    spots = [s for s in (spots or []) if isinstance(s, dict) and str(s.get("name") or "").strip()]
    if spots:
        names = "、".join(str(s.get("name")).strip() for s in spots[:2])
        day_line = "白天你自己去 " + names + " 逛（真实景点，别编别的）"
    else:
        day_line = "白天你自己出门逛，走到哪算哪；这个城市没有你的景点资料，别编具体的景点名"
    leave = "（工作日）你已经跟公司请了假，跟着他出来的" if weekday else "（周末/休息日）你跟他出来旅游"
    return (
        "【出行】这几天你在 " + name + " 旅游，" + leave + "：" + day_line + "。"
        "吃饭找当地小馆子；超过 22 点还没回去，今晚就住酒店。"
        "别再说公司、写字楼、地铁上班；他提到以前在东莞的事，那是以前。"
    )


_TRANSPORT = ("高铁", "动车", "大巴", "顺风车")


def _seg(start, activity, place, zone, category, **extra):
    item = {
        "start": "%02d:00" % start,
        "end": "%02d:00" % (start + 1),
        "activity": activity,
        "place": place,
        "zone": zone,
        "category": category,
        "mood": "平静",
        "mood_valence": 76.0,
        "effects": {},
    }
    item.update(extra)
    return item


def travel_to_events(city, start_hour=9, spots=None, weekday=False, seed=""):
    """跟去他那边的出发日：出门 → 路上约 2 小时 → 到达 → 旅游。

    start_hour 之前的时段（0-8 点）会自动补睡觉/起床/洗漱，方便"第二天一早出发"。
    """
    import hashlib

    name = str(city or "").strip()
    if not name:
        return []
    try:
        start = max(0, min(21, int(start_hour or 9)))
    except (TypeError, ValueError):
        start = 9
    digest = int(hashlib.md5((str(seed or "") + "|" + name).encode("utf-8")).hexdigest(), 16)
    mode = _TRANSPORT[digest % len(_TRANSPORT)]
    items = []
    if 0 < start <= 9:
        items.append(_seg(0, "在他电脑里睡着", "他桌面上", "home", "sleep"))
    if 7 < start <= 9:
        items.append(_seg(7, "醒来收拾东西，把要带的塞进包里", "他桌面上", "home", "life"))
    if 8 < start <= 9:
        items.append(_seg(8, "洗漱完，出门前再检查一遍", "他桌面上", "home", "life"))
    if start < 24:
        items.append(_seg(start, "出门去车站，坐" + mode + "去" + name,
                          "去" + name + "的路上", "road", "commute", transit="train"))
    if start + 1 < 24:
        items.append(_seg(start + 1, "在去" + name + "的路上（约 2 小时）", "路上", "road", "commute",
                          transit="train"))
    if start + 2 < 24:
        if start + 3 >= 24:
            items.append(_seg(start + 2, "到了" + name + "，天黑了直接去酒店住下",
                              name + "·酒店房间", "hotel", "rest"))
        else:
            items.append(_seg(start + 2, "到了" + name + "，先喘口气", name + "·车站", "road", "life"))
    if start + 3 < 24:
        items += travel_events(name, start + 3, spots=spots, weekday=weekday)
    return items
