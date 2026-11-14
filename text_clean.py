# -*- coding: utf-8 -*-
"""正文清洗：把模型当正文吐出来的控制标签去掉。

从 main.py 抽出来的（19,225 行那种大文件，先把这种纯函数、零依赖的块搬走）。

处理的几类脏东西：

- `<astrbot_execute_python>…` 这类框架标签（整块剥掉）
- `<astrbot_speak>` / `<text>` 之类的包裹标签
- `<thought>` / `<thinking>`：模型把思考标签当正文发出去（48 小时漏了 50 次）
- `<｜｜DSML｜｜ calls>`：工具调用的特殊标记
- 代码围栏
"""

from __future__ import annotations

import re

_PSEUDO_BLOCK_RE = re.compile(r"<astrbot_execute_python>.*?</astrbot_execute_python>", re.S | re.I)
_PSEUDO_TAG_RE = re.compile(r"</?(?:astrbot|amo)_[a-z_]+[^>]*>|</?text\b[^>]*>", re.I)
_THOUGHT_BLOCK_RE = re.compile(
    r"<(thought|thinking|reasoning|analysis)\b[^>]*>.*?</\1>", re.S | re.I)
_THOUGHT_TAG_RE = re.compile(r"</?(?:thought|thinking|reasoning|analysis)\b[^>]*>", re.I)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
_DSML_RE = re.compile(r"<[｜|][^<>]{0,120}>")
_DSML_BARE_RE = re.compile(r"[｜|]{2}\s*DSML\s*[｜|]{2}[^<\n]{0,40}", re.I)


def strip_pseudo_tags(text):
    """把框架控制标签从正文里剥掉。

    模型偶尔把 `<astrbot_execute_python>` 这类标签当正文输出，直接发出去就是
    「群里爆代码」。整块剥干净，代码围栏也一起删。
    """
    body = _DSML_RE.sub("", str(text or ""))
    body = _DSML_BARE_RE.sub("", body)
    body = _THOUGHT_BLOCK_RE.sub("", body)
    body = _THOUGHT_TAG_RE.sub("", body)
    body = _PSEUDO_BLOCK_RE.sub("", body)
    body = _PSEUDO_TAG_RE.sub("", body)
    body = _CODE_FENCE_RE.sub("", body)
    return body.strip()
