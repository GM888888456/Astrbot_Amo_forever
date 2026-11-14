# -*- coding: utf-8 -*-
"""本能模式：身体只给标签，不给台词；兜底与老路径不受影响。"""

import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as term  # noqa: E402


class FakeDB:
    def __init__(self, meal=None):
        self.meal = meal or {}

    def kv_get(self, key, default=None):
        return self.meal if key == "last_meal" else default


async def _noop():
    return None


def _fake(satiety=7.0, hydration=20.0, hungry_at=30.0, starving_at=5.0,
          instinct=True, meal=None, menu="", spawns=None):
    fake = types.SimpleNamespace(
        _vitals=lambda: {"enabled": True, "satiety": satiety, "hydration": hydration,
                         "hungry_at": hungry_at, "starving_at": starving_at},
        cfg_bool=lambda key, default=False: instinct if key == "instinct_mode" else default,
        db=FakeDB(meal),
        _food_menu=lambda limit=6: menu,
        _maybe_hunger_sick=_noop,
        _maybe_auto_meal=_noop,
    )

    def _spawn(coro):
        try:
            coro.close()
        except Exception:
            pass
        if spawns is not None:
            spawns.append(coro)

    fake._spawn = _spawn
    # 未绑定方法要绑回 fake 上，否则 self._body_tag_block 找不到
    fake._body_tag_block = lambda *a: term.HumanCorePlugin._body_tag_block(fake, *a)
    return fake


def test_instinct_mode_returns_body_tag_only():
    text = term.HumanCorePlugin._vitals_hint(_fake(), None)
    assert "[Body:" in text
    assert "Hunger=93" in text and "Thirst=80" in text
    assert "ts=" in text
    assert "胃里发空" not in text and "【状态" not in text


def test_instinct_mode_keeps_last_meal_fact():
    meal = {"ts": time.time() - 600, "dish": "番茄炒蛋"}
    text = term.HumanCorePlugin._vitals_hint(_fake(meal=meal), None)
    assert "Last_Meal=番茄炒蛋" in text
    assert "分钟前" in text


def test_instinct_mode_menu_only_when_hungry():
    hungry = term.HumanCorePlugin._vitals_hint(
        _fake(satiety=20, menu="番茄炒蛋 12"), None)
    assert "现在能吃的" in hungry
    full = term.HumanCorePlugin._vitals_hint(
        _fake(satiety=80, hydration=80, menu="番茄炒蛋 12"), None)
    assert "现在能吃的" not in full


def test_old_mode_still_uses_sentences():
    text = term.HumanCorePlugin._vitals_hint(_fake(instinct=False), None)
    assert "【状态：饥饿" in text
    assert "[Body:" not in text


def test_starving_spawns_fallback_in_both_modes():
    for instinct in (True, False):
        spawns = []
        fake = _fake(satiety=3, starving_at=10, instinct=instinct, spawns=spawns)
        term.HumanCorePlugin._vitals_hint(fake, None)
        assert len(spawns) == 2, instinct


def test_missing_vitals_returns_empty():
    fake = types.SimpleNamespace(_vitals=lambda: {})
    assert term.HumanCorePlugin._vitals_hint(fake, None) == ""


def test_disabled_vitals_returns_empty():
    fake = types.SimpleNamespace(_vitals=lambda: {"enabled": False, "satiety": 10})
    assert term.HumanCorePlugin._vitals_hint(fake, None) == ""


def _money_fake(cash=50.0, savings=0.0, owed=200.0, instinct=True):
    fake = types.SimpleNamespace(
        _money_pool=lambda: (cash, savings),
        cfg_bool=lambda key, default=False: instinct if key == "instinct_mode" else default,
        state=types.SimpleNamespace(finance={"owed": owed}),
    )
    return fake


def test_instinct_mode_wallet_tag():
    text = term.HumanCorePlugin._money_line(_money_fake())
    assert "[Wallet: Cash=50, Savings=0, Total=50, Debt=200" in text
    assert "ts=" in text
    assert "【钱】" not in text


def test_instinct_mode_keeps_money_rule():
    text = term.HumanCorePlugin._money_line(_money_fake(cash=50, savings=1000))
    assert "[Wallet:" in text
    assert "别跟任何人开口要钱" in text


def test_old_mode_money_sentence():
    text = term.HumanCorePlugin._money_line(_money_fake(instinct=False))
    assert "【钱】你卡里还有" in text
    assert "[Wallet:" not in text


def test_wallet_rounds_decimals():
    text = term.HumanCorePlugin._money_line(_money_fake(cash=12.345, savings=0.5, owed=0))
    assert "Cash=12.35" in text or "Cash=12.34" in text
    assert "Debt=0" in text
