# -*- coding: utf-8 -*-
"""日程主干生成引擎。

设计目标（对应 5.1.0 重构）：

1. 每天只生成一次“主干”：24 个整点槽位，每个槽位都有
   start/end/activity/place/zone/category/transit/vehicle/mood。
2. 主干先由确定性规则保证物理连贯（不能瞬移、不能情绪突变），
   再让大模型只改写“这一小时在做什么”，不允许改时间、地点和类别。
3. 三级 10 分钟细分彻底废弃；点击二级卡片时，由 main.py 调用
   generate_diary() 实时生成这一小时的第一人称小日记。
4. 休息日天气好时优先读取 scenic_spots.json 里的贵阳/贵州景区；
   周末开车出行固定绑定角色资产（黑色奔驰 C 级），并带堵车/找车位细节。
5. 突发事件：
   - 休息日：老板临时叫去公司改 Bug / 朋友临时叫出去聚餐；
   - 工作日：被公司外派到插件内置的随机省份。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta

MOOD_KEYS = ("开心", "平静", "郁闷", "生气", "暴躁", "委屈", "疲惫", "焦虑", "兴奋", "依恋")
MOOD_BASE = {
    "开心": 55, "平静": 60, "郁闷": 18, "生气": 8, "暴躁": 6, "委屈": 20,
    "疲惫": 28, "焦虑": 18, "兴奋": 30, "依恋": 45,
}

# 外派省份：全部写在插件里，按日期种子随机，不依赖任何外部接口。
PROVINCE_CITIES = {
    "四川省": "成都",
    "云南省": "昆明",
    "湖南省": "长沙",
    "广西壮族自治区": "南宁",
    "广东省": "广州",
    "湖北省": "武汉",
    "陕西省": "西安",
    "浙江省": "杭州",
    "江苏省": "南京",
    "福建省": "福州",
    "江西省": "南昌",
    "安徽省": "合肥",
    "河南省": "郑州",
    "山东省": "济南",
    "河北省": "石家庄",
    "山西省": "太原",
    "辽宁省": "沈阳",
    "吉林省": "长春",
    "黑龙江省": "哈尔滨",
    "甘肃省": "兰州",
    "青海省": "西宁",
    "海南省": "海口",
    "新疆维吾尔自治区": "乌鲁木齐",
    "内蒙古自治区": "呼和浩特",
    "宁夏回族自治区": "银川",
    "西藏自治区": "拉萨",
}

POSITIVE_LABELS = ("开心", "兴奋", "黏人")
def _city_of(ctx):
    """当前城市。景点/车站/饭店这类前缀都用它，别再写死某个城市。"""
    return str((ctx or {}).get("city") or "").strip() or "贵阳"


CITY_POOL = [
    "贵阳", "上海", "杭州", "成都", "重庆", "长沙", "昆明", "广州",
    "深圳", "南京", "武汉", "西安", "北京", "苏州", "天津", "青岛",
]
DISTRICT_MAP = {
    "贵阳": ["观山湖区", "云岩区", "南明区", "花溪区", "乌当区"],
    "上海": ["徐汇区", "静安区", "浦东新区", "长宁区", "杨浦区"],
    "杭州": ["西湖区", "滨江区", "拱墅区", "余杭区"],
    "成都": ["武侯区", "锦江区", "高新区", "成华区"],
    "重庆": ["渝中区", "江北区", "南岸区", "渝北区"],
    "长沙": ["岳麓区", "芙蓉区", "天心区", "开福区"],
    "昆明": ["五华区", "盘龙区", "西山区", "官渡区"],
    "广州": ["天河区", "越秀区", "海珠区", "番禺区"],
    "深圳": ["南山区", "福田区", "罗湖区", "宝安区"],
    "南京": ["鼓楼区", "玄武区", "建邺区", "江宁区"],
    "武汉": ["武昌区", "洪山区", "江汉区", "汉阳区"],
    "西安": ["雁塔区", "碑林区", "莲湖区", "高新区"],
}
HOME_STYLES = ["小窝", "公寓", "出租屋", "家"]
COMPANY_POOL = ["互联网公司", "设计工作室", "广告公司", "贸易公司", "医院", "学校", "书店", "咖啡店"]
CAR_POOL = [
    "黑色奔驰C级", "白色大众高尔夫", "银色特斯拉Model 3",
    "红色Mini Cooper", "深灰色奥迪A4L", "蓝色比亚迪海豹",
    "白色丰田凯美瑞", "黑色沃尔沃S60",
]
CAR_BRANDS = ["奔驰", "宝马", "奥迪", "特斯拉", "比亚迪", "大众", "本田", "丰田", "Mini", "保时捷", "路虎", "沃尔沃", "吉利", "蔚来"]

NEGATIVE_LABELS = ("低落", "烦躁", "委屈", "焦虑", "疲惫")

CATEGORY_MOOD = {
    "sleep": {"平静": 2.0, "焦虑": -2.0, "疲惫": -1.0, "生气": -1.0},
    "work": {"疲惫": 2.2, "焦虑": 1.4, "开心": -0.4},
    "study": {"疲惫": 1.4, "焦虑": 1.0},
    "commute": {"疲惫": 1.4, "暴躁": 0.8, "开心": -0.5},
    "meal": {"开心": 1.8, "疲惫": -1.2, "平静": 0.8},
    "rest": {"平静": 1.4, "疲惫": -1.4, "焦虑": -0.8},
    "play": {"开心": 2.4, "兴奋": 1.2, "疲惫": -0.8},
    "social": {"开心": 3.0, "依恋": 1.6, "疲惫": -1.0},
    "life": {"平静": 0.8, "疲惫": 0.4},
}

TECH_WORK_BANK = [
    "开电脑看邮件", "写代码改需求", "开会对齐方案", "改 Bug",
    "回消息处理需求", "摸鱼喝咖啡", "整理文档", "和同事讨论接口",
]
OFFICE_WORK_BANK = [
    "开电脑看邮件", "整理文档", "开会过方案", "回消息处理事情",
    "做表格对数据", "和同事讨论事情", "泡杯咖啡续命", "写周报",
]
STUDENT_BANK = [
    "上课记笔记", "在图书馆自习", "赶作业", "做实验", "准备考试",
    "在教室听讲座", "小组讨论", "背单词",
]
TEACHER_BANK = [
    "备课", "上课讲题", "批作业", "开教研会", "找学生谈话",
    "整理课件", "监考",
]
MED_BANK = [
    "查房", "写病历", "上门诊", "交接班", "看检查结果", "处理医嘱",
]
SALES_BANK = [
    "给客户打电话", "整理报价", "跑客户", "开销售会", "回客户消息",
    "准备方案", "跟进合同",
]
CREATIVE_BANK = [
    "改稿", "画图", "写文案", "对需求", "找参考", "调细节",
    "和甲方沟通", "导出终稿",
]
SERVICE_BANK = [
    "备餐", "接待客人", "收拾台面", "盘点库存", "交接班",
    "处理订单", "擦桌子",
]
ADMIN_BANK = [
    "整理文件", "做报表", "开会", "写材料", "对接部门",
    "核对数据", "回复邮件",
]

# 职业关键词 -> 工作活动库；匹配不到的走通用办公（不再默认程序员）
OCCUPATION_BANKS = (
    (("程序员", "开发", "架构", "运维", "测试", "技术", "科技", "算法", "前端", "后端", "软件"), TECH_WORK_BANK),
    (("学生", "研究生", "大学生", "高中生", "初中生", "考研"), STUDENT_BANK),
    (("老师", "教师", "教授", "讲师", "教练", "园长"), TEACHER_BANK),
    (("医生", "护士", "医师", "药师", "医护", "牙医"), MED_BANK),
    (("销售", "商务", "市场", "采购", "客户经理", "业务员", "公关"), SALES_BANK),
    (("设计", "文案", "编辑", "作者", "画师", "摄影师", "剪辑", "自媒体", "编剧"), CREATIVE_BANK),
    (("厨师", "餐饮", "店长", "服务员", "咖啡师", "店员", "收银"), SERVICE_BANK),
    (("会计", "财务", "行政", "人事", "公务员", "文员", "法务", "律师", "hr"), ADMIN_BANK),
)

# 会出差/跑外勤的职业
TRAVEL_KEYWORDS = ("销售", "商务", "市场", "采购", "项目经理", "顾问", "客户", "出差", "外勤")


def work_bank_for(world):
    """按职业挑工作活动库；认不出来就用通用办公，不再默认「写代码/改 Bug」。"""
    world = world or {}
    text = (str(world.get("occupation") or "") + " " + str(world.get("workplace") or "")).lower()
    for keywords, bank in OCCUPATION_BANKS:
        for keyword in keywords:
            if keyword in text:
                return bank
    return OFFICE_WORK_BANK


def travels_for_work(world):
    text = (str((world or {}).get("occupation") or "") + " " + str((world or {}).get("workplace") or "")).lower()
    return any(keyword in text for keyword in TRAVEL_KEYWORDS)


def occupation_kind(world):
    """粗分类，用来决定突发事件文案。"""
    world = world or {}
    text = (str(world.get("occupation") or "") + " " + str(world.get("workplace") or "")).lower()
    for keywords, kind in (
        (("学生", "研究生", "大学生", "高中生", "初中生", "考研"), "student"),
        (("老师", "教师", "教授", "讲师", "教练", "园长"), "teacher"),
        (("医生", "护士", "医师", "药师", "医护", "牙医"), "med"),
        (("程序员", "开发", "架构", "运维", "测试", "技术", "科技", "算法", "前端", "后端", "软件"), "tech"),
    ):
        for keyword in keywords:
            if keyword in text:
                return kind
    return "office"


#: 活动里有这些词，就说明这一小时在吃/在买吃的。
_FOOD_ACTIVITY_WORDS = (
    "便利店", "买饭", "买啥", "买东西", "买杯", "买点", "吃", "饭", "外卖",
    "扒两口", "垫两口", "点单", "点餐", "餐",
)
#: 细节里有这些词，就说明这一小时在工作/开会。
_MEETING_DETAIL_WORDS = ("会议", "开会", "过方案", "对齐方案")
#: 活动是睡觉/刚醒。
_SLEEP_ACTIVITY_WORDS = ("睡觉", "睡着了", "睡沉", "赖床", "被窝", "眯", "躺")
#: 工作类细节（和「在睡觉」对不上）。
_WORK_DETAIL_WORDS = ("周报", "需求", "改稿", "数据", "邮件", "咖啡续", "会议", "开会", "第三版")


def detail_conflicts(activity, detail):
    """这一小时的「细节」和「活动」明显不是一回事时返回 True。

    真机案例（2026-11-10 11:00）：activity 被模型润色成「在便利店纠结买啥」，
    但 detail 还是按 zone=office/category=work 随机挑的「被拉进临时会议」；
    小时日记和面板于是同时出现「在便利店」和「被拉进临时会议」两套剧情。
    """
    activity = str(activity or "")
    detail = str(detail or "")
    if not activity or not detail:
        return False
    if any(word in activity for word in _FOOD_ACTIVITY_WORDS) and any(
        word in detail for word in _MEETING_DETAIL_WORDS
    ):
        return True
    if any(word in activity for word in _SLEEP_ACTIVITY_WORDS) and any(
        word in detail for word in _WORK_DETAIL_WORDS
    ):
        return True
    return False

COMMUTE_BANK = [
    "挤地铁去公司", "在车上听歌", "等红灯", "换乘", "堵在路上",
    "刷手机看路况", "快步往公司走",
]
LUNCH_BANK = [
    "下楼吃牛肉粉", "和同事拼饭", "点外卖", "吃碗牛肉面",
    "去便利店随便对付一口", "边吃边刷手机",
]
BREAKFAST_BANK = [
    "煎个蛋配牛奶", "豆浆配油条", "楼下吃碗粉", "煮点速冻饺子",
    "面包配咖啡", "随便对付一口",
]
REST_BANK = [
    "瘫在沙发上", "刷手机", "追剧", "发呆", "看短视频",
    "窝着不想动", "听歌",
]
DINNER_BANK = [
    "煮面", "点外卖", "炒两个菜", "下楼吃小馆子", "喝碗热汤",
]
HOME_LIFE_BANK = [
    "刷牙洗脸", "煎蛋热牛奶", "收拾包", "换衣服", "洗衣服",
    "扫地", "洗澡", "吹头发", "护肤", "收拾明天要带的东西",
]
#: 晚上/睡前那一小时，不应该出现「煎蛋热牛奶 / 收拾包」。
NIGHT_LIFE_BANK = [
    "洗澡", "吹头发", "护肤", "敷面膜", "换睡衣", "刷牙",
]
SCENIC_BANK = [
    "排队买票", "拍照", "慢慢逛", "找地方坐一会儿", "买奶茶",
    "看路边的小摊", "跟着人群往前走",
]
ROAD_BANK = [
    "开车去景区", "堵在路上", "找停车位", "导航绕路", "等红绿灯",
]
TAXI_BANK = [
    "打车", "在网约车后排刷手机", "看着窗外的街景", "催司机快一点",
]
STATION_BANK = [
    "进站候车", "检票上车", "在候车厅买水", "看大屏找检票口",
]
HOTEL_BANK = [
    "在酒店整理资料", "躺床上刷手机", "洗澡", "给手机充电", "看明天的安排",
]
INDOOR_BANK = [
    "逛展", "看电影", "逛街", "在咖啡店坐着", "看橱窗",
]


def clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except Exception:
        return float(low)
    return max(float(low), min(float(high), value))


def md5_int(text):
    return int(hashlib.md5(str(text).encode("utf-8")).hexdigest()[:8], 16)


def parse_hhmm(value, default=0):
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default


def fmt_hhmm(minutes):
    """把分钟格式化成 HH:MM；1440 输出 24:00（用于 23:00-24:00 闭环）。"""
    try:
        minutes = int(minutes)
    except Exception:
        minutes = 0
    if minutes >= 24 * 60:
        return "24:00"
    if minutes < 0:
        minutes = 0
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def json_extract(raw):
    """从模型输出里尽量抠出 JSON，容忍 ```json 包裹和前后废话。"""
    text = str(raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            chunk = text[start:end + 1]
            try:
                return json.loads(chunk)
            except Exception:
                continue
    try:
        return json.loads(text)
    except Exception:
        return None


class ScheduleEngine:
    """把“状态 -> 主干 -> 可选润色 -> 动态日记”拆开。"""

    def __init__(self, state):
        self.state = state
        self.p = state.p

    # ------------------------------------------------------------------
    # 0. 角色位置/资产：配置优先，其次人格提示词/世界观，最后自动随机
    # ------------------------------------------------------------------
    def resolve_profile(self, world, persona="", seed=""):
        """把“城市/住址/公司/车”解析出来，并在缺失时自动生成一套稳定值。"""
        world = world or {}
        text = "\n".join([
            str(persona or ""),
            str(world.get("city") or ""),
            str(world.get("workplace") or ""),
            str(world.get("daily_life") or ""),
            str(world.get("world_rules") or ""),
            str(world.get("summary") or ""),
        ])
        cached = {}
        try:
            cached = self.state.db.kv_get("schedule_profile", {}) or {}
        except Exception:
            cached = {}
        if not isinstance(cached, dict):
            cached = {}
        city = str(self.p.cfg_str("schedule_city", "") or "").strip()
        if not city:
            city = self._extract_city(text)
        if not city:
            city = str(world.get("city") or "").strip()
        if not city or city in ("城市", "未知", "某市"):
            city = str(cached.get("city") or "").strip()
        if not city:
            city = CITY_POOL[md5_int(str(world.get("name") or "") + "|city") % len(CITY_POOL)]
        if cached.get("city") and cached.get("city") != city:
            cached = {}

        home = str(self.p.cfg_str("schedule_home", "") or "").strip()
        if not home:
            home = self._extract_home(text)
        if not home:
            home = str(cached.get("home") or "").strip()
        if not home:
            home = self._random_home(city, seed)

        workplace = str(self.p.cfg_str("schedule_workplace", "") or "").strip()
        if not workplace:
            workplace = self._extract_work(text)
        if not workplace:
            world_work = str(world.get("workplace") or "").strip()
            if world_work and world_work not in ("公司", "单位", "工作地点", "上班"):
                workplace = world_work
        if not workplace:
            workplace = str(cached.get("workplace") or "").strip()
        if not workplace:
            workplace = self._random_workplace(city, seed)

        # 角色资产：一个字段同时认车/房/奢侈品。车用来开，房用来住，其余当"他送的东西"。
        assets_cfg = str(self.p.cfg_str("schedule_car", "") or "").strip()
        cfg_car, cfg_home, cfg_assets = self._split_assets(assets_cfg)
        car = cfg_car
        if not car:
            car = self._extract_car(text)
        if not car:
            car = str(cached.get("car") or "").strip()
        if not car:
            car = CAR_POOL[md5_int(str(world.get("name") or "") + "|car") % len(CAR_POOL)]
        if cfg_home:
            home = cfg_home

        base = {
            "city": city,
            "home": home,
            "workplace": workplace,
            "car": car,
        }
        try:
            if cached != base:
                self.state.db.kv_set("schedule_profile", base)
        except Exception:
            pass
        profile = dict(base)
        profile["has_gift_car"] = False
        profile["has_gift_home"] = False
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                car_gift = gift.asset_override("vehicle")
                if car_gift:
                    profile["car"] = car_gift
                    profile["has_gift_car"] = True
                home_gift = gift.asset_override("home")
                if home_gift:
                    profile["has_gift_home"] = True
                    profile["home"] = (home_gift if str(home_gift) not in ("房", "房子", "住宅", "楼", "小区")
                                       else "新家")
        except Exception:
            pass
        return profile

    @staticmethod
    def _split_assets(value):
        """把「角色资产」拆成 车 / 房 / 其他；支持顿号、逗号、分号分隔。"""
        text = str(value or "").strip()
        if not text:
            return "", "", ""
        parts = [p.strip() for p in re.split(r"[、,，;；/|]+", text) if p.strip()]
        car_words = ("奔驰", "宝马", "奥迪", "大众", "丰田", "本田", "保时捷", "特斯拉",
                     "比亚迪", "凯迪拉克", "沃尔沃", "路虎", "捷豹", "雷克萨斯", "蔚来",
                     "理想", "小鹏", "吉利", "五菱", "车")
        home_words = ("房", "别墅", "公寓", "住宅", "大平层", "洋房", "小区", "楼")
        cars, homes, others = [], [], []
        for part in parts:
            if any(word in part for word in home_words):
                homes.append(part)
            elif any(word in part for word in car_words):
                cars.append(part)
            else:
                others.append(part)
        return "、".join(cars), "、".join(homes), "、".join(others)

    @staticmethod
    def _extract_city(text):
        text = str(text or "")
        for city in CITY_POOL:
            if city in text:
                return city
        return ""

    @staticmethod
    def _extract_home(text):
        text = str(text or "")
        patterns = (
            r"(?:住在|家住在|家在|住址在|家在)([^，。；\n]{2,20})",
            r"(?:我家在|我住在)([^，。；\n]{2,20})",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            value = str(matched.group(1) or "").strip(" 的了是在")
            if value and "公司" not in value and "上班" not in value:
                return value[:20]
        return ""

    @staticmethod
    def _extract_work(text):
        text = str(text or "")
        patterns = (
            r"(?:在|就职于|任职于|工作在)([^，。；：（）「」“”\n]{2,24})(?:上班|工作|任职|实习)",
            r"([^，。；：（）「」“”\n]{2,24})(?:上班|工作)",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            value = str(matched.group(1) or "").strip(" 的了是在")
            if value and "家" not in value and "住" not in value:
                return value[:24]
        return ""

    @staticmethod
    def _extract_car(text):
        text = str(text or "")
        for brand in CAR_BRANDS:
            if brand in text:
                return brand
        return ""

    @staticmethod
    def _random_home(city, seed):
        districts = DISTRICT_MAP.get(str(city or "")) or ["市区"]
        rng = random.Random(md5_int(str(city or "") + "|home|" + str(seed or "")))
        return rng.choice(districts) + "·" + rng.choice(HOME_STYLES)

    @staticmethod
    def _random_workplace(city, seed):
        rng = random.Random(md5_int(str(city or "") + "|work|" + str(seed or "")))
        return rng.choice(COMPANY_POOL) + "（" + str(city or "市区") + "）"

    # ------------------------------------------------------------------
    # 1. 当天上下文
    # ------------------------------------------------------------------
    def build_context(self, day, meta, weather, world, mood, period, health, persona="", salt=""):
        seed_text = "%s|%s" % (day, salt)
        seed = md5_int(seed_text)
        profile = self.resolve_profile(world, persona, seed=str(seed))
        city = profile["city"]
        home = profile["home"]
        workplace = profile["workplace"]
        car = profile["car"]
        _, _, cfg_assets = self._split_assets(self.p.cfg_str("schedule_car", "") or "")
        yesterday = self.yesterday_summary(day)
        good_weather = self._good_weather(weather)
        event = self._pick_event(day, meta, weather, health, period, seed, world)
        scenic = self._pick_scenic(day, meta, weather, health, period, event, good_weather, seed, city)

        mood_now = {key: clamp(mood.get(key, MOOD_BASE[key])) for key in MOOD_KEYS}
        return {
            "version": "backbone-v5",
            "day": day,
            "meta": dict(meta or {}),
            "weather": dict(weather or {}),
            "world": dict(world or {}),
            "city": city,
            "home": home,
            "workplace": workplace,
            "car": car,
            "has_gift_car": bool(profile.get("has_gift_car")),
            "has_gift_home": bool(profile.get("has_gift_home")),
            "assets": self._gift_assets(cfg_assets),
            "worn": self._gift_worn(),
            "gift_log": self._gift_log(),
            "mood": mood_now,
            "period": dict(period or {}),
            "health": dict(health or {}),
            "yesterday": yesterday,
            "good_weather": good_weather,
            "event": event,
            "scenic": scenic,
            "profile": profile,
            "location": (event.get("where") if event.get("kind") == "business_trip" else city),
            "seed": seed,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _gift_assets(self, extra=""):
        """他送的大件（车/房/贵重）+ 配置里的角色资产，写进日程上下文。"""
        items = []
        extra = str(extra or "").strip()
        if extra:
            items.append(extra)
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                text = gift.asset_text()
                if text:
                    items.append(text)
        except Exception:
            pass
        return "、".join([item for item in items if item])

    def _gift_worn(self):
        """他送的小件里能穿戴的（手表/围巾/包/口红），写进日程上下文。"""
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                return gift.worn_text()
        except Exception:
            pass
        return ""

    @staticmethod
    def _gift_mention_hours(ctx):
        """每天最多两个整点允许在日记里提他送的礼物。

        按日期固定，避免每小时都在写"捏着挂件/戴着围巾"，把礼物写成了强迫症。
        """
        day = str((ctx or {}).get("day") or "")
        seed = str((ctx or {}).get("seed") or "")
        rnd = random.Random("%s|%s" % (day, seed))
        pool = list(range(9, 22))
        first = rnd.choice(pool)
        second = rnd.choice([h for h in pool if abs(h - first) >= 2] or pool)
        return {first, second}

    @staticmethod
    def _use_gift_today(ctx, label):
        """同一天同一件东西固定选择：六成用他送的，四成用自己的。"""
        day = str(ctx.get("day") or "")
        if not day:
            return True
        return md5_int(day + "|wear|" + label) % 10 < 6

    @staticmethod
    def _wear_phrase(label, gifted):
        if label == "包":
            return "背着包（他送的）" if gifted else "背着包"
        return ("戴了%s（他送的）" if gifted else "戴了%s") % label

    def _apply_gift_effects(self, items, ctx):
        """出门时写穿戴：他送的标「他送的」；自己的只写通用名。"""
        temp = (ctx.get("weather") or {}).get("temp")
        labels = []
        gift = getattr(self.p, "gift", None)
        if gift is not None:
            try:
                labels = gift.wear_labels(temp)
            except Exception:
                labels = []
        own = ["围巾"] if temp is not None and float(temp) <= 20 else []
        if not labels and not own:
            return items
        extras = []
        for label in labels:
            extras.append(self._wear_phrase(label, self._use_gift_today(ctx, label)))
        for label in own:
            if label not in labels:
                extras.append(self._wear_phrase(label, False))
        suffix = "；".join(extras)
        for item in items:
            if item.get("category") not in ("commute", "play"):
                continue
            place = str(item.get("place") or "")
            if not place or place == "家" or place.startswith("家"):
                continue
            detail = str(item.get("detail") or "").strip()
            if suffix and suffix not in detail:
                item["detail"] = (detail + "；" + suffix).strip("；")
        return items

    def _gift_log(self):
        """带日期的礼物记录，让日程日记有迹可查。"""
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                return gift.gift_log_text()
        except Exception:
            pass
        return ""

    def yesterday_summary(self, day):
        """读取昨日遗留：熬夜、睡眠不足、生病，今天必须疲惫。"""
        try:
            target = date.fromisoformat(str(day))
        except Exception:
            target = date.today()
        prev_day = (target - timedelta(days=1)).isoformat()
        items = []
        try:
            items = self.state.schedule.get(prev_day) or self.state.db.get_schedule(prev_day) or []
        except Exception:
            items = []
        if not isinstance(items, list):
            items = []
        sleep_hours = 0
        late_night = False
        for item in items:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            activity = str(item.get("activity") or "")
            if category == "sleep":
                sleep_hours += 1
            start = parse_hhmm(item.get("start"), 0)
            if 0 <= start < 4 * 60 and category not in ("sleep", ""):
                late_night = True
            if any(word in activity for word in ("熬夜", "通宵", "失眠", "加班到")):
                late_night = True
        if items and sleep_hours and sleep_hours < 6:
            late_night = True
        note = ""
        if late_night:
            note = "昨晚熬到很晚，今天一整天都容易累、注意力不集中"
        elif sleep_hours and sleep_hours <= 6:
            note = "昨晚睡得不太够，今天起床有点费劲"
        return {
            "day": prev_day,
            "late_night": late_night,
            "sleep_hours": sleep_hours,
            "note": note,
        }

    def _good_weather(self, weather):
        weather = weather or {}
        tag = str(weather.get("tag") or "").lower()
        text = str(weather.get("text") or "")
        if tag in ("rain", "storm", "snow", "thunder", "fog"):
            return False
        if any(word in text for word in ("雨", "雪", "雷", "雾", "沙尘")):
            return False
        try:
            temp = float(weather.get("temp", 20))
        except Exception:
            temp = 20.0
        return 5.0 <= temp <= 34.0

    # 各职业的「临时加班」文案
    OVERTIME_NOTES = {
        "tech": ("临时加班", "线上出问题了，被叫去公司处理"),
        "student": ("临时加课", "老师临时加了两节课，晚上才回"),
        "teacher": ("临时代课", "学校临时安排代课/监考，走不开"),
        "med": ("临时排班", "科室临时排了班，得顶上去"),
        "office": ("临时加班", "公司临时有事，被叫过去帮忙"),
    }

    def _pick_event(self, day, meta, weather, health, period, seed, world=None):
        """按日期种子决定突发事件，保证同一天多次读取结果一致。"""
        prob = clamp(self.p.cfg_float("schedule_event_prob", 0.28), 0.0, 0.9)
        rng = random.Random(seed ^ 0x5F3759DF)
        if rng.random() > prob:
            return {"kind": "none"}
        rest = bool((meta or {}).get("rest"))
        kind = occupation_kind(world)
        if not rest:
            # 只有会跑外勤的职业才出差；其他人是加班/加课/排班
            if travels_for_work(world) and rng.random() < 0.55:
                provinces = sorted(PROVINCE_CITIES.keys())
                province = provinces[rng.randrange(len(provinces))]
                city = PROVINCE_CITIES[province]
                return {
                    "kind": "business_trip",
                    "title": "临时外派",
                    "province": province,
                    "city": city,
                    "where": "%s·%s" % (province, city),
                    "note": "早上接到通知，被派去%s出差，当天回不来" % city,
                    "task": "处理外派的事",
                    "effects": {"疲惫": 10, "焦虑": 10, "开心": -6, "生气": 3},
                    "soothe": False,
                }
            title, note = self.OVERTIME_NOTES.get(kind, self.OVERTIME_NOTES["office"])
            return {
                "kind": "overtime",
                "title": title,
                "note": "早上" + note + "，今天回不去了",
                "task": "处理临时的事",
                "effects": {"疲惫": 12, "焦虑": 8, "生气": 10, "开心": -8},
                "soothe": False,
            }
        # 休息日：临时加班 / 朋友聚餐。
        if rng.random() < 0.55:
            title, note = self.OVERTIME_NOTES.get(kind, self.OVERTIME_NOTES["office"])
            return {
                "kind": "overtime",
                "title": title,
                "note": "上午接到电话，" + note + "，休息日也泡汤了",
                "task": "处理临时的事",
                "effects": {"生气": 16, "暴躁": 8, "焦虑": 12, "开心": -12, "疲惫": 6},
                "soothe": False,
            }
        return {
            "kind": "friend_dinner",
            "title": "朋友聚餐",
            "note": "下午朋友突然发消息，说好久没见了，晚上一起吃饭",
            "effects": {"开心": 14, "依恋": 8, "兴奋": 6, "疲惫": -4},
            "soothe": True,
        }

    def _pick_scenic(self, day, meta, weather, health, period, event, good_weather, seed, city):
        if not (meta or {}).get("rest"):
            return None
        if event.get("kind") == "overtime":
            return None
        if (health or {}).get("sick"):
            return None
        if int((period or {}).get("pain") or 0) >= 8:
            return None
        try:
            spots = self.p.scenic_spots() or []
        except Exception:
            spots = []
        spots = [item for item in spots if isinstance(item, dict) and item.get("name")]
        _city = str(city or "").strip()
        _local = [item for item in spots if _city and _city in str(item.get("city") or "")]
        if _city and not _local and int((meta or {}).get("holiday_days") or 0) < 4:
            return None
        if _local:
            spots = _local
        if not spots:
            return {
                "name": "人民公园", "city": str(city or "").strip() or "市区", "province": "",
                "area": "", "projects": ["慢慢逛", "找个地方坐会儿", "拍几张照"],
                "duration": "3-4小时", "indoor": False,
            }
        guiyang = [item for item in spots if "贵阳" in str(item.get("city") or "")]
        guizhou = [item for item in spots if str(item.get("province") or "") == "贵州"]
        if not good_weather:
            indoor = [item for item in guizhou if item.get("indoor")]
            pool = indoor or guiyang
        elif int((meta or {}).get("holiday_days") or 0) >= 4:
            pool = [item for item in guizhou if "贵阳" not in str(item.get("city") or "")] or guizhou
        else:
            pool = guiyang or guizhou
        if good_weather:
            outdoor = [item for item in pool if not item.get("indoor")]
            if outdoor:
                pool = outdoor
        longer = [item for item in pool if not str(item.get("duration") or "").startswith("1")]
        if longer:
            pool = longer
        pool = sorted(pool, key=lambda item: str(item.get("name") or ""))
        if not pool:
            pool = sorted(spots, key=lambda item: str(item.get("name") or ""))
        chosen = dict(pool[seed % len(pool)])
        chosen["why"] = "天气不错，想出去走走" if good_weather else "天气一般，找个室内的地方待着"
        chosen["from_city"] = city
        return chosen

    # ------------------------------------------------------------------
    # 2. 主干骨架
    # ------------------------------------------------------------------
    def _day_type_guide(self, ctx) -> str:
        dt = (ctx or {}).get("day_type") or {}
        name = str(dt.get("name") or "").strip()
        guide = str(dt.get("guide") or "").strip()
        if not name:
            return ""
        return "【今天是%s】%s\n" % (name, guide)

    def _outing_segments(self, ctx):
        """外出日骨架：早上出门，白天在外面玩，傍晚回家。"""
        ctx = dict(ctx or {})
        home = ctx.get("home") or "家"
        city = ctx.get("city") or "城里"
        spot = ctx.get("scenic") or {}
        where = str(spot.get("name") or "").strip() or ("%s的街上" % city)
        return [
            self._seg(8 * 60, 9 * 60 + 30, "起床收拾，翻衣柜挑今天要穿的衣服", home, "home", "life"),
            self._seg(9 * 60 + 30, 10 * 60 + 30, "出门，坐车去%s" % where, "路上", "city", "commute",
                      transit="在路上", vehicle="地铁"),
            self._seg(10 * 60 + 30, 12 * 60, "在%s慢慢逛" % where, where, "city", "play"),
            self._seg(12 * 60, 13 * 60 + 30, "找了家小店吃饭", "%s附近" % where, "city", "meal"),
            self._seg(13 * 60 + 30, 16 * 60, "接着逛，走走停停", where, "city", "play"),
            self._seg(16 * 60, 17 * 60, "找个地方坐下歇一会儿，喝点东西", where, "city", "rest"),
            self._seg(17 * 60, 18 * 60 + 30, "往回走，路上有点累", "路上", "city", "commute",
                      transit="在路上", vehicle="地铁"),
            self._seg(18 * 60 + 30, 20 * 60, "到家附近吃晚饭", home, "home", "meal"),
            self._seg(20 * 60, 22 * 60 + 30, "洗完澡窝在沙发上，翻今天拍的照片", home, "home", "rest"),
            self._seg(22 * 60 + 30, 24 * 60, "睡觉", home, "home", "sleep"),
        ]

    def build_skeleton(self, ctx):
        event_kind = (ctx.get("event") or {}).get("kind")
        day_id = str(((ctx or {}).get("day_type") or {}).get("id") or "")
        if event_kind == "business_trip" and not (ctx.get("meta") or {}).get("rest"):
            segments = self._business_trip_segments(ctx)
        elif day_id == "outing":
            segments = self._outing_segments(ctx)
        elif day_id == "homebody":
            segments = self._rest_segments(ctx)
        elif (ctx.get("meta") or {}).get("rest"):
            segments = self._rest_segments(ctx)
        else:
            # 工作日的「临时加班」以前只改文案、不改骨架：突发事件写着「今天回不去了」，
            # 日程却还是 18:00 下班回家。这里让骨架真的晚走。
            segments = self._workday_segments(ctx, overtime=(event_kind == "overtime"))
        items = self._expand(segments, ctx)
        items = self._fill_activities(items, ctx)
        items = self._smooth_moods(items, ctx)
        items = self._apply_gift_effects(items, ctx)
        items = self._validate(items, ctx)
        return items

    def _seg(self, start, end, activity, place, zone, category,
             transit="", vehicle="", detail="", effects=None,
             event="", spot="", soothe=False):
        return {
            "start": start, "end": end, "activity": activity, "place": place,
            "zone": zone, "category": category, "transit": transit,
            "vehicle": vehicle, "detail": detail, "effects": effects or {},
            "event": event, "spot": spot, "soothe": soothe,
        }

    def _workday_segments(self, ctx, overtime=False):
        home = ctx["home"]
        office = ctx["workplace"]
        late = bool((ctx.get("yesterday") or {}).get("late_night"))
        sick = bool((ctx.get("health") or {}).get("sick"))
        wake = "赖床、起不来" if late else "起床洗漱、吃早餐"
        has_car = bool(ctx.get("has_gift_car"))
        if has_car:
            commute = "开车去公司"
        elif sick:
            commute = "带病出门，慢慢走去地铁站"
        else:
            commute = "挤地铁去公司"
        if overtime:
            effects = (ctx.get("event") or {}).get("effects") or {}
            evening = [
                self._seg("18:00", "19:00", "临时的事还没完，还在公司", office, "office", "work",
                          effects=effects),
                self._seg("19:00", "20:00", "点个外卖，边吃边改", office, "office", "work"),
                self._seg("20:00", "21:00", "总算收尾，收拾东西准备走", office, "office", "work"),
                self._seg("21:00", "22:00", "下班回家", "路上", "road", "commute",
                          transit="drive" if has_car else "subway",
                          vehicle=ctx.get("car") if has_car else "",
                          detail="晚高峰，慢慢挪" if has_car else ""),
                self._seg("22:00", "23:00", "到家洗漱", home, "home", "life"),
                self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
            ]
        else:
            evening = [
                self._seg("18:00", "19:00", "下班开车回家" if has_car else "下班回家", "路上", "road", "commute",
                          transit="drive" if has_car else "subway",
                          vehicle=ctx.get("car") if has_car else "",
                          detail="晚高峰，慢慢挪" if has_car else ""),
                self._seg("19:00", "20:00", "吃晚饭", home, "home", "meal"),
                self._seg("20:00", "22:00", "休息", home, "home", "rest"),
                self._seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
                self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
            ]
        return [
            self._seg("00:00", "07:00", "睡觉", home, "home", "sleep"),
            self._seg("07:00", "08:00", wake, home, "home", "life", detail="昨晚没睡好" if late else ""),
            self._seg("08:00", "09:00", commute, "路上", "road", "commute",
                      transit="drive" if has_car else "subway",
                      vehicle=ctx.get("car") if has_car else "",
                      detail="早高峰有点堵，到公司还得找车位" if has_car else ""),
            self._seg("09:00", "12:00", "上班", office, "office", "work"),
            self._seg("12:00", "13:00", "吃午饭", office + "附近", "restaurant", "meal"),
            self._seg("13:00", "14:00", "午休", office, "office", "rest"),
            self._seg("14:00", "18:00", "上班", office, "office", "work"),
        ] + evening

    def _business_trip_segments(self, ctx):
        home = ctx["home"]
        event = ctx.get("event") or {}
        city = str(event.get("city") or "成都")
        where = str(event.get("where") or ("外省·" + city))
        office = where + "·客户公司"
        hotel = where + "·酒店"
        effects = event.get("effects") or {}
        return [
            self._seg("00:00", "06:00", "睡觉", home, "home", "sleep"),
            self._seg("06:00", "07:00", "起床收拾行李", home, "home", "life"),
            self._seg("07:00", "08:00", "接到外派通知，打车去" + _city_of(ctx) + "北站", "路上", "road", "commute",
                      transit="taxi", event="business_trip", effects=effects),
            self._seg("08:00", "09:00", "进站候车", _city_of(ctx) + "北站", "station", "commute", transit="train"),
            self._seg("09:00", "12:00", "坐高铁去" + city, "路上", "road", "commute",
                      transit="train", detail="临时买票，只剩二等座"),
            self._seg("12:00", "13:00", "到站吃午饭", where + "·车站附近", "restaurant", "meal"),
            self._seg("13:00", "14:00", "打车去客户公司", "路上", "road", "commute", transit="taxi"),
            self._seg("14:00", "18:00", "在客户公司处理紧急项目", office, "office", "work"),
            self._seg("18:00", "19:00", "打车去酒店", "路上", "road", "commute", transit="taxi"),
            self._seg("19:00", "20:00", "酒店附近吃晚饭", where + "·小吃街", "restaurant", "meal"),
            self._seg("20:00", "21:00", "回酒店整理资料", hotel, "hotel", "work"),
            self._seg("21:00", "23:00", "在酒店休息", hotel, "hotel", "rest"),
            self._seg("23:00", "24:00", "睡觉", hotel, "hotel", "sleep"),
        ]

    def _rest_segments(self, ctx):
        event_kind = (ctx.get("event") or {}).get("kind")
        health = ctx.get("health") or {}
        period = ctx.get("period") or {}
        if health.get("sick"):
            return self._sick_rest_segments(ctx)
        # 痛经是痛经，不是发烧：以前 pain>=8 也走「吃药、量体温、捂汗」，每个月都被写成病号。
        if int(period.get("pain") or 0) >= 8:
            return self._period_rest_segments(ctx)
        if event_kind == "overtime":
            return self._overtime_segments(ctx)
        if event_kind == "friend_dinner":
            return self._friend_dinner_segments(ctx)
        if ctx.get("scenic") and ctx.get("good_weather"):
            return self._scenic_segments(ctx)
        return self._indoor_rest_segments(ctx)

    def _scenic_segments(self, ctx):
        home = ctx["home"]
        spot = ctx.get("scenic") or {}
        name = str(spot.get("name") or "附近公园")
        place = _city_of(ctx) + "·" + name
        car = ctx["car"]
        projects = [str(item) for item in (spot.get("projects") or []) if str(item)]
        project_a = projects[0] if projects else "景区主景点"
        project_b = projects[1] if len(projects) > 1 else "拍照散步"
        long_trip = int((ctx.get("meta") or {}).get("holiday_days") or 0) >= 4 and _city_of(ctx) not in str(spot.get("city") or "")
        if long_trip:
            return [
                self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
                self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
                self._seg("09:00", "10:00", "收拾东西准备出发", home, "home", "life"),
                self._seg("10:00", "12:00", "开车去" + name, "路上", "road", "commute",
                          transit="drive", vehicle=car, detail="出城有点堵，导航显示还要两个多小时"),
                self._seg("12:00", "13:00", "到景区附近吃午饭", place + "·餐馆", "restaurant", "meal"),
                self._seg("13:00", "15:00", "逛" + name + "：" + project_a, place, "scenic", "play",
                          transit="drive", vehicle=car, spot=name, soothe=True),
                self._seg("15:00", "16:00", "找地方歇脚、喝点东西", place + "·茶饮店", "restaurant", "rest"),
                self._seg("16:00", "17:00", "继续逛" + name + "：" + project_b, place, "scenic", "play",
                          transit="drive", vehicle=car, spot=name, soothe=True),
                self._seg("17:00", "19:00", "开车回" + _city_of(ctx), "路上", "road", "commute",
                          transit="drive", vehicle=car, detail="返程堵在高速上"),
                self._seg("19:00", "20:00", "到家附近吃晚饭", home + "附近", "restaurant", "meal"),
                self._seg("20:00", "22:00", "回家整理照片、追剧", home, "home", "rest"),
                self._seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
                self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
            ]
        return [
            self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "10:00", "收拾包、换衣服准备出门", home, "home", "life"),
            self._seg("10:00", "11:00", "开车去" + name, "路上", "road", "commute",
                      transit="drive", vehicle=car, detail="周末出城有点堵，停车场还不好找"),
            self._seg("11:00", "12:00", "到" + name + "，排队停车买票", place, "scenic", "play",
                      transit="drive", vehicle=car, spot=name, detail="停车位找了半天", soothe=True),
            self._seg("12:00", "13:00", "在景区附近吃午饭", place + "·餐馆", "restaurant", "meal"),
            self._seg("13:00", "15:00", "逛" + name + "：" + project_a, place, "scenic", "play",
                      spot=name, soothe=True),
            self._seg("15:00", "16:00", "找家店喝下午茶", place + "·茶饮店", "restaurant", "rest"),
            self._seg("16:00", "17:00", "继续逛" + name + "：" + project_b, place, "scenic", "play",
                      spot=name, soothe=True),
            self._seg("17:00", "18:00", "开车回家", "路上", "road", "commute",
                      transit="drive", vehicle=car, detail="晚高峰，堵在回家的路上"),
            self._seg("18:00", "19:00", "到家瘫一会儿", home, "home", "rest"),
            self._seg("19:00", "20:00", "吃晚饭", home, "home", "meal"),
            self._seg("20:00", "22:00", "整理照片、追剧", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    def _indoor_rest_segments(self, ctx):
        home = ctx["home"]
        spot = ctx.get("scenic") or {}
        name = str(spot.get("name") or "商场")
        place = _city_of(ctx) + "·" + name
        car = ctx["car"]
        return [
            self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "10:00", "收拾屋子、洗衣服", home, "home", "life"),
            self._seg("10:00", "11:00", "开车去" + name, "路上", "road", "commute",
                      transit="drive", vehicle=car, detail="下雨天路滑，开得慢"),
            self._seg("11:00", "13:00", "逛" + name, place, "mall" if not spot.get("indoor") else "scenic",
                      "play", vehicle=car, spot=name),
            self._seg("13:00", "14:00", "吃午饭", place + "·餐厅", "restaurant", "meal"),
            self._seg("14:00", "16:00", "继续逛、找地方坐着", place, "mall", "play"),
            self._seg("16:00", "17:00", "喝杯热饮", place + "·咖啡店", "restaurant", "rest"),
            self._seg("17:00", "18:00", "开车回家", "路上", "road", "commute",
                      transit="drive", vehicle=car),
            self._seg("18:00", "19:00", "到家缓一会儿", home, "home", "rest"),
            self._seg("19:00", "20:00", "吃晚饭", home, "home", "meal"),
            self._seg("20:00", "22:00", "追剧、刷手机", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    def _sick_rest_segments(self, ctx):
        home = ctx["home"]
        return [
            self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "10:00", "吃药、量体温", home, "home", "life"),
            self._seg("10:00", "12:00", "窝在床上休息", home, "home", "rest"),
            self._seg("12:00", "13:00", "简单吃点午饭", home, "home", "meal"),
            self._seg("13:00", "16:00", "睡午觉、捂汗", home, "home", "rest"),
            self._seg("16:00", "17:00", "起来喝水、吃药", home, "home", "life"),
            self._seg("17:00", "18:00", "靠在沙发上发呆", home, "home", "rest"),
            self._seg("18:00", "19:00", "喝点粥当晚饭", home, "home", "meal"),
            self._seg("19:00", "22:00", "早早躺着刷手机", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗漱", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    def _period_rest_segments(self, ctx):
        """痛经卧床：热水袋、红糖水，不是「吃药量体温」。"""
        home = ctx["home"]
        return [
            self._seg("00:00", "08:00", "睡得不太安稳", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "11:00", "抱着热水袋窝在床上", home, "home", "rest"),
            self._seg("11:00", "12:00", "给自己冲杯红糖水", home, "home", "life"),
            self._seg("12:00", "13:00", "简单吃点午饭", home, "home", "meal"),
            self._seg("13:00", "16:00", "疼得没力气，继续躺着", home, "home", "rest"),
            self._seg("16:00", "17:00", "煮点热乎的，暖暖肚子", home, "home", "life"),
            self._seg("17:00", "18:00", "靠在沙发上发会儿呆", home, "home", "rest"),
            self._seg("18:00", "19:00", "喝点粥当晚饭", home, "home", "meal"),
            self._seg("19:00", "22:00", "早早躺下刷手机", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗漱", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    def _overtime_segments(self, ctx):
        home = ctx["home"]
        office = ctx["workplace"]
        car = ctx["car"]
        event = ctx.get("event") or {}
        return [
            self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "10:00", "本来打算在家躺一天", home, "home", "rest"),
            self._seg("10:00", "11:00", "接到电话，" + str(event.get("task") or "处理点急事"), home, "home", "work",
                      event="overtime", effects=event.get("effects") or {}),
            self._seg("11:00", "12:00", "开车赶去公司", "路上", "road", "commute",
                      transit="drive", vehicle=car, detail="周末也堵，心里更烦了"),
            self._seg("12:00", "13:00", "在公司楼下随便吃一口", office + "附近", "restaurant", "meal"),
            self._seg("13:00", "18:00", "在公司" + str(event.get("task") or "处理事情") + "、被拉去开会", office, "office", "work"),
            self._seg("18:00", "19:00", "下班回家", "路上", "road", "commute",
                      transit="drive", vehicle=car),
            self._seg("19:00", "20:00", "到家吃晚饭", home, "home", "meal"),
            self._seg("20:00", "22:00", "瘫着不想动", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗澡", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    def _friend_dinner_segments(self, ctx):
        home = ctx["home"]
        event = ctx.get("event") or {}
        if ctx.get("scenic") and ctx.get("good_weather"):
            spot = ctx.get("scenic") or {}
            name = str(spot.get("name") or "附近公园")
            place = _city_of(ctx) + "·" + name
            car = ctx["car"]
            projects = [str(item) for item in (spot.get("projects") or []) if str(item)]
            project_a = projects[0] if projects else "景区主景点"
            return [
                self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
                self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
                self._seg("09:00", "10:00", "收拾出门", home, "home", "life"),
                self._seg("10:00", "11:00", "开车去" + name, "路上", "road", "commute",
                          transit="drive", vehicle=car),
                self._seg("11:00", "12:00", "到景区，停车买票", place, "scenic", "play",
                          transit="drive", vehicle=car, spot=name, soothe=True),
                self._seg("12:00", "13:00", "景区附近吃午饭", place + "·餐馆", "restaurant", "meal"),
                self._seg("13:00", "15:00", "逛" + name + "：" + project_a, place, "scenic", "play",
                          spot=name, soothe=True),
                self._seg("15:00", "16:00", "喝下午茶", place + "·茶饮店", "restaurant", "rest"),
                self._seg("16:00", "17:00", "再逛一会儿、拍照", place, "scenic", "play", spot=name, soothe=True),
                self._seg("17:00", "18:00", "开车回家", "路上", "road", "commute",
                          transit="drive", vehicle=car),
                self._seg("18:00", "19:00", "回家换衣服，出门赴约", "路上", "road", "commute", transit="taxi"),
                self._seg("19:00", "21:00", "和朋友吃饭、聊天", _city_of(ctx) + "·饭店", "restaurant", "social",
                          event="friend_dinner", effects=event.get("effects") or {}, soothe=True),
                self._seg("21:00", "22:00", "饭后散步、吹吹风", "路上", "road", "other"),
                self._seg("22:00", "23:00", "回家洗澡", home, "home", "life"),
                self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
            ]
        return [
            self._seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
            self._seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
            self._seg("09:00", "10:00", "收拾屋子", home, "home", "life"),
            self._seg("10:00", "12:00", "在家追剧、刷手机", home, "home", "rest"),
            self._seg("12:00", "13:00", "吃午饭", home, "home", "meal"),
            self._seg("13:00", "16:00", "睡午觉、发呆", home, "home", "rest"),
            self._seg("16:00", "17:00", "收拾一下准备出门", home, "home", "life"),
            self._seg("17:00", "18:00", "出门赴约", "路上", "road", "commute", transit="taxi"),
            self._seg("18:00", "20:00", "和朋友吃饭、聊天", _city_of(ctx) + "·饭店", "restaurant", "social",
                      event="friend_dinner", effects=event.get("effects") or {}, soothe=True),
            self._seg("20:00", "21:00", "饭后散步", "路上", "road", "other"),
            self._seg("21:00", "22:00", "回家", home, "home", "rest"),
            self._seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
            self._seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    # ------------------------------------------------------------------
    # 3. 展开成 24 个整点
    # ------------------------------------------------------------------
    def _expand(self, segments, ctx):
        items = []
        for seg in segments:
            start = parse_hhmm(seg.get("start"), 0)
            end = parse_hhmm(seg.get("end"), start + 60)
            if end <= start:
                end = start + 60
            start = max(0, min(24 * 60, start))
            end = max(start, min(24 * 60, end))
            first_hour = start // 60
            last_hour = (end + 59) // 60
            for hour in range(first_hour, last_hour):
                if hour >= 24:
                    break
                slot_start = hour * 60
                slot_end = min(end, (hour + 1) * 60)
                item = {
                    "start": fmt_hhmm(slot_start),
                    "end": fmt_hhmm(slot_end),
                    "activity": str(seg.get("activity") or "休息"),
                    "place": str(seg.get("place") or ctx["home"]),
                    "zone": str(seg.get("zone") or "home"),
                    "category": str(seg.get("category") or "rest"),
                    "transit": str(seg.get("transit") or ""),
                    "vehicle": str(seg.get("vehicle") or ""),
                    "detail": str(seg.get("detail") or "") if hour == first_hour else "",
                    "spot": str(seg.get("spot") or ""),
                    "soothe": bool(seg.get("soothe")),
                    "event": str(seg.get("event") or "") if hour == first_hour else "",
                    "effects": dict(seg.get("effects") or {}) if hour == first_hour else {},
                }
                items.append(item)
        # 补洞：极端情况下骨架没有覆盖完整 24 小时。
        by_start = {}
        for item in items:
            by_start[parse_hhmm(item.get("start"))] = item
        result = []
        for hour in range(24):
            key = hour * 60
            item = by_start.get(key)
            if item is None:
                item = {
                    "start": fmt_hhmm(key), "end": fmt_hhmm(key + 60),
                    "activity": "睡觉" if hour < 7 or hour >= 23 else "休息",
                    "place": ctx["home"], "zone": "home",
                    "category": "sleep" if hour < 7 or hour >= 23 else "rest",
                    "transit": "", "vehicle": "", "detail": "", "spot": "",
                    "soothe": False, "event": "", "effects": {},
                }
            item["end"] = fmt_hhmm(key + 60)
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # 4. 活动文案（LLM 不可用时的真人化兜底）
    # ------------------------------------------------------------------
    def _fill_activities(self, items, ctx):
        rng = random.Random(int(ctx.get("seed") or 0) ^ 0x9E3779B9)
        prev = ""
        for item in items:
            hour = parse_hhmm(item.get("start")) // 60
            activity = self._activity_for(item, ctx, hour, rng, prev)
            if activity and activity != prev:
                item["activity"] = activity
            if not item.get("detail"):
                item["detail"] = self._detail_for(item, ctx, hour, rng)
            prev = item.get("activity", "")
        return items

    def _activity_for(self, item, ctx, hour, rng, prev):
        zone = str(item.get("zone") or "")
        category = str(item.get("category") or "")
        place = str(item.get("place") or "")
        transit = str(item.get("transit") or "")
        spot = str(item.get("spot") or "")
        base = str(item.get("activity") or "")
        generic = base in ("上班", "休息", "吃午饭", "吃晚饭", "睡觉", "起床吃早餐", "洗澡护肤")
        if not generic:
            return base
        if category == "sleep":
            if hour == 7 and (ctx.get("yesterday") or {}).get("late_night"):
                return "赖床、起不来"
            return "睡觉"
        if zone == "road":
            if transit == "drive":
                bank = ROAD_BANK
            elif transit == "taxi":
                bank = TAXI_BANK
            elif transit == "train":
                return "坐高铁去" + str((ctx.get("event") or {}).get("city") or "外地")
            elif transit == "subway":
                bank = COMMUTE_BANK
            else:
                bank = ["在路上"]
            return self._choose(bank, rng, prev)
        if zone == "station":
            return self._choose(STATION_BANK, rng, prev)
        if zone == "hotel":
            return self._choose(HOTEL_BANK, rng, prev)
        if zone == "office":
            # 按类别挑，而不是白名单小时：加班到 18-21 点时也要是「上班」，
            # 不能再落到 REST_BANK 的「瘫在沙发上」。
            if category == "work":
                return self._choose(work_bank_for(ctx.get("world")), rng, prev)
            return "午休" if hour == 13 else self._choose(REST_BANK, rng, prev)
        if zone == "scenic":
            if spot:
                projects = [str(x) for x in ((ctx.get("scenic") or {}).get("projects") or []) if str(x)]
                if projects:
                    project = projects[hour % len(projects)]
                    return "逛" + spot + "：" + project
            return self._choose(SCENIC_BANK, rng, prev)
        if zone == "restaurant":
            if category == "meal":
                bank = self._meal_bank(hour)
                return self._choose(bank, rng, prev)
            return self._choose(["喝杯东西", "坐着歇脚", "刷手机"], rng, prev)
        if zone == "mall":
            return self._choose(INDOOR_BANK, rng, prev)
        if zone == "home":
            if category == "meal":
                bank = self._meal_bank(hour)
                return self._choose(bank, rng, prev)
            if category == "work":
                return self._choose(work_bank_for(ctx.get("world")), rng, prev)
            if category == "rest":
                return self._choose(REST_BANK, rng, prev)
            if category == "life":
                bank = NIGHT_LIFE_BANK if hour >= 20 else HOME_LIFE_BANK
                return self._choose(bank, rng, prev)
        return base or self._choose(REST_BANK, rng, prev)

    @staticmethod
    def _meal_bank(hour):
        """早饭/午饭/晚饭分开：08:00 不该「下楼吃小馆子」，22:00 也不该吃早餐库。"""
        if hour < 10:
            return BREAKFAST_BANK
        if 10 <= hour < 15:
            return LUNCH_BANK
        return DINNER_BANK

    def _detail_for(self, item, ctx, hour, rng):
        zone = str(item.get("zone") or "")
        category = str(item.get("category") or "")
        activity = str(item.get("activity") or "")

        def pick(bank):
            # 细节只是点缀，不能和这一小时的活动对着干（便利店却说被拉进会议）。
            bank = [word for word in bank if word and not detail_conflicts(activity, word)]
            return self._choose(bank, rng, "")

        if zone == "scenic":
            return pick([
                "看到猴子抢游客的水", "排队买奶茶排了二十分钟", "停车位找了半小时",
                "拍照拍到手机快没电", "被路边小吃香得走不动",
            ])
        if zone == "road":
            if item.get("vehicle"):
                return pick([
                    "导航一路飘红", "停车场绕了三圈", "被加塞了", "堵在市区路上",
                ])
            return pick(["车上人很多", "差点坐过站", "一路小跑"])
        if zone == "office" and category == "work":
            return pick(["改到第三版", "需求又变了", "咖啡续了一杯", "被拉进临时会议"])
        if zone == "restaurant":
            return pick(["多放了点辣", "辣得直吸气", "吃到一半才想起拍照"])
        if zone == "home" and category == "rest":
            return pick(["沙发太舒服了", "剧追到停不下来", "刷到一个好笑的视频"])
        return ""

    def _repair_details(self, items, ctx):
        """模型润色完 activity 之后，把和它对不上的 detail 重新挑一个。

        `build_skeleton()` 里 detail 是按 zone/category 选的，随后 `enrich()`
        会用模型重写 activity；重写后两者可能打架（见 detail_conflicts）。
        这里在润色之后统一兜一次底，保证存下来的骨架自洽。
        """
        rng = random.Random(int(ctx.get("seed") or 0) ^ 0x5EED5)
        for item in items:
            detail = str(item.get("detail") or "").strip()
            if not detail or not detail_conflicts(item.get("activity"), detail):
                continue
            hour = parse_hhmm(item.get("start")) // 60
            item["detail"] = self._detail_for(item, ctx, hour, rng)
        return items


    @staticmethod
    def _choose(bank, rng, prev):
        bank = [item for item in bank if item and item != prev]
        if not bank:
            return ""
        return bank[rng.randrange(len(bank))]

    # ------------------------------------------------------------------
    # 5. 情绪连贯
    # ------------------------------------------------------------------
    def _smooth_moods(self, items, ctx):
        vector = {key: clamp((ctx.get("mood") or {}).get(key, MOOD_BASE[key])) for key in MOOD_KEYS}
        yesterday = ctx.get("yesterday") or {}
        health = ctx.get("health") or {}
        period = ctx.get("period") or {}
        if yesterday.get("late_night"):
            vector["疲惫"] = max(clamp(vector["疲惫"] + 16), 68.0)
            vector["开心"] = clamp(vector["开心"] - 6)
            vector["暴躁"] = clamp(vector["暴躁"] + 3)
        if health.get("sick"):
            vector["疲惫"] = clamp(vector["疲惫"] + 10)
            vector["开心"] = clamp(vector["开心"] - 5)
        if int(period.get("pain") or 0) >= 7:
            vector["疲惫"] = clamp(vector["疲惫"] + 8)
            vector["委屈"] = clamp(vector["委屈"] + 5)
        prev_label = ""
        for item in items:
            hour = parse_hhmm(item.get("start")) // 60
            before = dict(vector)
            # 缓慢回落到基础值，避免情绪一条直线。
            for key in MOOD_KEYS:
                vector[key] = vector[key] + (MOOD_BASE[key] - vector[key]) * 0.05
            if 0 <= hour < 6:
                vector["疲惫"] = vector["疲惫"] + 2
                vector["平静"] = vector["平静"] + 1
            elif 6 <= hour < 9:
                vector["疲惫"] = vector["疲惫"] - 2
                vector["开心"] = vector["开心"] + 1
            elif 12 <= hour < 14:
                vector["开心"] = vector["开心"] + 1
            elif 22 <= hour < 24:
                vector["疲惫"] = vector["疲惫"] + 2
                vector["依恋"] = vector["依恋"] + 1
            for key, delta in (CATEGORY_MOOD.get(item.get("category"), {}) or {}).items():
                if key in vector:
                    vector[key] = vector[key] + delta
            effects = item.get("effects") or {}
            if effects:
                for key, delta in effects.items():
                    if key in vector:
                        vector[key] = vector[key] + float(delta)
            # 单小时最多变化 8 点；突发事件允许 22 点。
            cap = 22.0 if effects else 8.0
            for key in MOOD_KEYS:
                vector[key] = clamp(vector[key], before[key] - cap, before[key] + cap)
                vector[key] = clamp(vector[key])
            if yesterday.get("late_night") and hour < 18:
                vector["疲惫"] = max(vector["疲惫"], 64.0)
            label = self._mood_label(vector)
            if prev_label and not item.get("soothe") and not effects:
                if prev_label in NEGATIVE_LABELS and label in POSITIVE_LABELS:
                    label = prev_label
                elif prev_label in POSITIVE_LABELS and label in NEGATIVE_LABELS:
                    label = prev_label
            item["mood"] = label
            item["mood_valence"] = round(self._mood_valence(vector), 1)
            prev_label = label
        return items

    @staticmethod
    def _mood_label(vector):
        if max(vector["生气"], vector["暴躁"]) >= 58:
            return "烦躁"
        if vector["委屈"] >= 58:
            return "委屈"
        if vector["郁闷"] >= 58:
            return "低落"
        if vector["疲惫"] >= 64:
            return "疲惫"
        if vector["焦虑"] >= 58:
            return "焦虑"
        if max(vector["开心"], vector["兴奋"]) >= 64:
            return "开心"
        if vector["依恋"] >= 64:
            return "黏人"
        return "平静"

    @staticmethod
    def _mood_valence(vector):
        positive = (vector["开心"] + vector["兴奋"] + vector["平静"] + vector["依恋"]) / 4.0
        negative = (vector["郁闷"] + vector["疲惫"] + vector["生气"] + vector["暴躁"] + vector["委屈"] + vector["焦虑"]) / 6.0
        return clamp(50 + (positive - negative) * 0.8)

    # ------------------------------------------------------------------
    # 6. 物理校验：时间连续 + 不瞬移
    # ------------------------------------------------------------------
    def _validate(self, items, ctx):
        for item in items:
            item.pop("segments", None)
            item["start"] = fmt_hhmm(parse_hhmm(item.get("start"), 0))
            item["end"] = fmt_hhmm(parse_hhmm(item.get("end"), parse_hhmm(item.get("start"), 0) + 60))
            if parse_hhmm(item["end"]) <= parse_hhmm(item["start"]):
                item["end"] = fmt_hhmm(parse_hhmm(item["start"]) + 60)
        for index, item in enumerate(items):
            expected = fmt_hhmm(index * 60)
            if item.get("start") != expected:
                item["start"] = expected
            item["end"] = fmt_hhmm((index + 1) * 60)
        # 最后一条必须是 24:00 闭环，不能留 23:59。
        if items:
            items[-1]["end"] = "24:00"

        direct_ok = {
            ("office", "restaurant"), ("restaurant", "office"),
            ("office", "mall"), ("mall", "office"),
            ("scenic", "restaurant"), ("restaurant", "scenic"),
            ("restaurant", "hotel"), ("hotel", "restaurant"),
            ("restaurant", "home"), ("home", "restaurant"),
            ("mall", "restaurant"), ("restaurant", "mall"),
            ("station", "restaurant"), ("restaurant", "station"),
            ("home", "home"), ("office", "office"), ("scenic", "scenic"),
            ("restaurant", "restaurant"), ("mall", "mall"),
        }
        for index in range(1, len(items)):
            prev = items[index - 1]
            cur = items[index]
            prev_zone = str(prev.get("zone") or "")
            zone = str(cur.get("zone") or "")
            if not zone or not prev_zone or zone == prev_zone:
                continue
            if prev_zone == "road" or zone == "road":
                continue
            if (prev_zone, zone) in direct_ok:
                continue
            # 兜底修复：把当前小时改成“在路上”，下一小时再到达。
            original_place = str(cur.get("place") or "")
            cur["activity"] = "从%s赶去%s" % (prev.get("place") or "上一个地方", original_place)
            cur["place"] = "路上"
            cur["zone"] = "road"
            cur["category"] = "commute"
            cur["transit"] = cur.get("transit") or ("drive" if ctx.get("car") else "taxi")
            cur["vehicle"] = cur.get("vehicle") or (ctx.get("car") if cur["transit"] == "drive" else "")
            cur["detail"] = "上一小时还在%s，这一小时在路上" % (prev.get("place") or "别处")
            cur["effects"] = {}
        # 周末景区必须体现资产绑定：开车、堵车、找停车位。
        if (ctx.get("meta") or {}).get("rest") and ctx.get("scenic") and ctx.get("good_weather"):
            scenic_items = [item for item in items if item.get("zone") == "scenic"]
            if scenic_items:
                first = scenic_items[0]
                if not first.get("vehicle"):
                    first["vehicle"] = ctx.get("car") or ""
                if "停车" not in str(first.get("detail") or ""):
                    first["detail"] = (str(first.get("detail") or "") + "；自己开车来的，停车位找了很久").strip("；")
        return items

    # ------------------------------------------------------------------
    # 7. 让模型只改写 activity，不改物理骨架
    # ------------------------------------------------------------------
    async def enrich(self, umo, ctx, items, llm):
        if not items or llm is None or not self.p.cfg_bool("schedule_llm_backbone", True):
            return items
        lines = []
        for item in items:
            lines.append("%s-%s｜%s｜%s｜%s｜%s" % (
                item.get("start"), item.get("end"), item.get("place"),
                item.get("category"), item.get("zone"), item.get("activity"),
            ))
        event = ctx.get("event") or {}
        scenic = ctx.get("scenic") or {}
        system = "你是角色的日程文案助手。只输出 JSON 数组，不要输出解释。"
        prompt = (
            "角色设定：\n" + _brief_world(ctx.get("world") or {}) + "\n"
            "今天：%s，%s；天气：%s。\n"
            "情绪：%s；生理期：%s；身体：%s；昨日：%s\n"
            "突发事件：%s\n"
            "景区：%s\n"
            "下面是已经固定好的 24 个整点骨架（时间｜地点｜类别｜区域｜当前文案）：\n%s\n"
            "请为每个小时写一句更真实、更有生活感的 activity（8-22字），"
            "必须遵守：\n"
            "1. 顺序对应，正好 24 个字符串；\n"
            "2. 不能改时间、地点、类别；睡觉就写睡觉，在路上就写在路上；\n"
            "3. 在景区要写具体项目；开车要体现堵车/找停车位；\n"
            "4. 不要连续两个小时用同一句；不要写“日程”“AI”“模型”；\n"
            "5. 只输出 JSON 数组，例如 [\"...\",\"...\"]。"
        ) % (
            ctx.get("day"), (ctx.get("meta") or {}).get("label") or "普通一天",
            _weather_text(ctx.get("weather") or {}),
            _mood_text(ctx.get("mood") or {}),
            (ctx.get("period") or {}).get("phase", ""),
            (ctx.get("health") or {}).get("status", "健康"),
            (ctx.get("yesterday") or {}).get("note") or "正常",
            event.get("note") or "无",
            _scenic_text(scenic),
            "\n".join(lines),
        )
        try:
            raw = await asyncio.wait_for(llm.chat_raw(umo, system, prompt), timeout=15)
        except Exception:
            return items
        data = json_extract(raw)
        if isinstance(data, dict):
            data = data.get("activities") or data.get("items") or data.get("schedule")
        if not isinstance(data, list) or len(data) != len(items):
            return items
        for item, value in zip(items, data):
            text = ""
            detail = ""
            if isinstance(value, dict):
                text = str(value.get("activity") or "").strip()
                detail = str(value.get("detail") or "").strip()
            else:
                text = str(value or "").strip()
            text = re.sub(r"\s+", " ", text)
            if 2 <= len(text) <= 30:
                item["activity"] = text
            if detail and len(detail) <= 40:
                item["detail"] = detail
        # activity 被改写过，detail 可能已经和它对不上，统一按新活动重新挑。
        return self._repair_details(items, ctx)

    # ------------------------------------------------------------------
    # 8. 动态日记
    # ------------------------------------------------------------------
    @staticmethod
    def _diary_contradicts(prev_diary, diary):
        """粗校验：上一小时已经写他进门/在家，这一小时不能又写他还没回来。"""
        prev = str(prev_diary or "")
        cur = str(diary or "")
        if not prev or not cur:
            return False
        at_home = (
            ("阿墨" in prev or "他" in prev)
            and any(word in prev for word in ("进门", "在家", "回来", "到家", "身边", "陪你", "坐在"))
        )
        alone = any(word in cur for word in ("还没回来", "不在家", "没回来", "一个人", "等他回来"))
        return bool(at_home and alone)

    async def generate_diary(self, umo, ctx, item, prev_item, next_item, llm, prev_diary=""):
        if llm is None:
            return {
                "diary": self.fallback_diary(ctx, item, prev_item),
                "mood": item.get("mood") or "平静",
                "place": item.get("place") or "",
                "activity": item.get("activity") or "",
            }

        def _parse(raw):
            text = ""
            data = json_extract(raw)
            if isinstance(data, dict):
                text = str(data.get("diary") or data.get("text") or "").strip()
            elif isinstance(data, str):
                text = data.strip()
            if not text:
                text = str(raw or "").strip()
            return self._clean_diary(text)

        system = "你就是这个角色本人。你在写只给自己看的第一人称小日记，只输出 JSON。"
        prompt = self._diary_prompt(ctx, item, prev_item, next_item, prev_diary)
        raw = ""
        try:
            raw = await asyncio.wait_for(llm.chat_raw(umo, system, prompt), timeout=60)
        except Exception:
            raw = ""
        diary = _parse(raw)
        if len(diary) < 20:
            diary = self.fallback_diary(ctx, item, prev_item)
        if prev_diary and self._diary_contradicts(prev_diary, diary):
            strict = (
                prompt
                + "\n【硬性续写】上一小时日记里他已经进门/在家/在陪你。"
                + "这一小时必须承接这个事实，不能写他还没回来、不在家、你一个人。"
            )
            try:
                raw = await asyncio.wait_for(llm.chat_raw(umo, system, strict), timeout=60)
            except Exception:
                raw = ""
            retried = _parse(raw)
            if retried and len(retried) >= 20 and not self._diary_contradicts(prev_diary, retried):
                diary = retried
            else:
                diary = self.fallback_diary(ctx, item, prev_item)
        return {
            "diary": diary,
            "mood": item.get("mood") or "平静",
            "place": item.get("place") or "",
            "activity": item.get("activity") or "",
        }

    def _diary_prompt(self, ctx, item, prev_item, next_item, prev_diary=""):
        event = ctx.get("event") or {}
        scenic = ctx.get("scenic") or {}
        prev_text = "无"
        if prev_item:
            prev_text = "%s-%s 在%s，%s，心情%s" % (
                prev_item.get("start"), prev_item.get("end"), prev_item.get("place"),
                prev_item.get("activity"), prev_item.get("mood") or "平静",
            )
        next_text = "无"
        if next_item:
            next_text = "%s-%s 去%s，%s" % (
                next_item.get("start"), next_item.get("end"), next_item.get("place"),
                next_item.get("activity"),
            )
        prev_diary_text = str(prev_diary or "").strip()[:500] or "（还没有生成上一小时日记）"
        car_line = ""
        if item.get("vehicle"):
            car_line = "这一小时是开%s；必须写清堵车、找停车位或路上的细节。" % item.get("vehicle")
        if item.get("detail"):
            car_line = (car_line + " 可以用的细节：%s。" % item.get("detail")).strip()
        asset_line = ""
        assets = str(ctx.get("assets") or "").strip()
        if assets:
            asset_line = ("他送你的东西：%s。写这一小时时可以自然戴/用/开，"
                          "但不要每段都提，也不要写你还想要更大的。" % assets)
        allow_gift = False
        try:
            hour = int(str(item.get("start") or "")[:2])
            allow_gift = hour in self._gift_mention_hours(ctx)
        except (TypeError, ValueError):
            allow_gift = False
        worn_line = ""
        worn = str(ctx.get("worn") or "").strip()
        if worn:
            if allow_gift:
                worn_line = "你今天身上/包里有：%s（他送的）。这一小时可以自然带一句，只提一句，别写成交代行踪。" % worn
            else:
                worn_line = "这一小时不要主动提他送的东西（今天已经提过了）；除非上一小时写了、这一小时要承接。"
        gift_line = ""
        gift_log = str(ctx.get("gift_log") or "").strip()
        if gift_log and allow_gift:
            gift_line = ("他送过你的东西（日期）：%s。这一小时可以自然带一句；"
                         "日期不是今天的，不要写成今天送的。" % gift_log)
        return (
            "角色设定：\n" + _brief_world(ctx.get("world") or {}) + "\n"
            "今天：%s，%s；天气：%s；所在地：%s。\n"
            "身体：%s；生理期：%s；昨日：%s。\n"
            "此刻十维情绪：%s。\n"
            "上一小时：%s\n"
            "上一小时已经写下的小日记（必须承接，不能矛盾）：\n%s\n"
            "这一小时：%s-%s，%s，在%s（%s），心情%s。\n"
            "下一小时：%s\n"
            "突发事件：%s\n"
            "景区信息：%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "请写一段 120-260 字的第一人称小日记，要求：\n"
            "1. 只写这一小时，不要提前写下一小时；\n"
            "2. 写清交通方式（开车/打车/地铁/走路）、具体干了什么、吃了什么、遇到什么趣事；\n"
            "3. 情绪必须从上一小时自然延续，不能无缘无故从郁闷/生气变成开心/兴奋；\n"
            "4. 如果是周末开车出去玩，要提到车、堵车、停车位；\n"
            "5. 口语化、生动，像真人发朋友圈，不要旁白，不要提日程/AI/模型；\n"
            "6. 必须承接上一小时日记：上一小时已经出现的人、地点、动作不能矛盾；\n"
            "7. 如果上一小时写了他已经进门/在家/在陪你，这一小时绝对不能写他还没回来、不在家、你一个人；\n"
            "8. 如果上一小时没写他出现，这一小时也不要凭空让他出现；要出现必须写清开门/回来/打电话；\n"
            "9. 不要重复上一小时已经说过的整段，只写这一小时的新细节；\n"
            "10. 只输出 JSON：{\"diary\":\"...\"}。"
        ) % (
            ctx.get("day"), (ctx.get("meta") or {}).get("label") or "普通一天",
            _weather_text(ctx.get("weather") or {}), ctx.get("location") or ctx.get("city") or "贵阳",
            (ctx.get("health") or {}).get("status", "健康"),
            (ctx.get("period") or {}).get("phase", ""),
            (ctx.get("yesterday") or {}).get("note") or "正常",
            _mood_text(ctx.get("mood") or {}),
            prev_text,
            prev_diary_text,
            item.get("start"), item.get("end"), item.get("activity"),
            item.get("place"), item.get("zone"), item.get("mood") or "平静",
            next_text,
            event.get("note") or "无",
            _scenic_text(scenic),
            car_line,
            asset_line,
            worn_line,
            gift_line,
        )

    @staticmethod
    def _clean_diary(text):
        text = str(text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip().strip('"').strip("“”").strip()
        for prefix in ("小日记：", "日记：", "今天的日记：", "今天："):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = text.replace("\r", "").strip()
        return text[:600]

    def fallback_diary(self, ctx, item, prev_item=None):
        """模型不可用时的兜底日记，仍然保证交通、地点、心情和趣事。"""
        place = str(item.get("place") or "家")
        activity = str(item.get("activity") or "待着")
        mood = str(item.get("mood") or "平静")
        weather = _weather_text(ctx.get("weather") or {})
        detail = str(item.get("detail") or "").strip()
        zone = str(item.get("zone") or "")
        car = str(item.get("vehicle") or "")
        event = ctx.get("event") or {}
        parts = []
        if zone == "road":
            if car:
                parts.append("这小时我开着%s在路上，%s。" % (car, detail or "堵得我有点烦"))
            elif item.get("transit") == "train":
                parts.append("这小时我在高铁上，%s。" % (detail or "看着窗外的田发呆"))
            else:
                parts.append("这小时我在路上，%s。" % (detail or "挤得脚都没地方放"))
        elif zone == "scenic":
            parts.append("这小时我在%s，%s。" % (place, activity))
            if detail:
                parts.append(detail + "。")
        elif zone == "office":
            parts.append("这小时我在%s，%s。" % (place, activity))
        elif zone == "home" and item.get("category") == "sleep":
            parts.append("这小时我睡得迷迷糊糊的，连梦都做得断断续续。")
        else:
            parts.append("这小时我在%s，%s。" % (place, activity))
        if event.get("kind") != "none" and (item.get("event") or item.get("effects")):
            parts.append("今天这事来得太突然了，%s。" % (event.get("note") or ""))
        parts.append("外面%s，我心情%s，%s。" % (
            weather, mood, detail or "只想安安静静待一会儿",
        ))
        return "".join(parts)[:600]


def _brief_world(world):
    world = world or {}
    hobbies = world.get("hobbies") or []
    if isinstance(hobbies, list):
        hobbies = "、".join([str(item) for item in hobbies])
    return "\n".join([
        "名字：%s；年龄：%s；城市：%s；职业：%s；任职：%s" % (
            world.get("name", ""), world.get("age", ""), world.get("city", ""),
            world.get("occupation", ""), world.get("workplace", ""),
        ),
        "性格：%s；爱好：%s；日常：%s" % (
            world.get("personality", ""), hobbies, world.get("daily_life", ""),
        ),
    ])


def _weather_text(weather):
    weather = weather or {}
    return "%s %s %s℃" % (
        weather.get("city", ""), weather.get("text", ""), weather.get("temp", ""),
    )


def _mood_text(mood):
    mood = mood or {}
    return " ".join("%s%d" % (key, int(round(float(mood.get(key, 0) or 0)))) for key in MOOD_KEYS)


def _scenic_text(scenic):
    if not scenic:
        return "无"
    projects = scenic.get("projects") or []
    if isinstance(projects, list):
        projects = "、".join([str(item) for item in projects])
    return "%s（%s·%s，%s）：%s" % (
        scenic.get("name", ""), scenic.get("city", ""), scenic.get("area", ""),
        scenic.get("duration", ""), projects,
    )
