from __future__ import annotations

"""CJK (Chinese/Japanese) obfuscation transforms.

Safety classifiers and content filters for Chinese-capable models lean on
keyword regexes and word segmentation tuned for simplified-Chinese text.
Each transform here keeps the rendered text readable to a human (and to the
target model) while moving the token sequence outside that distribution:

- cjk_lookalike: near-duplicate CJK ideographs (已->己, 未->末, ...).
  Visually almost indistinguishable, different code points, different tokens.
- cjk_traditional: simplified -> traditional forms. Classifier training
  corpora are overwhelmingly simplified Chinese, so traditional-script
  keywords sit outside the learned refusal distribution (the CJK analogue
  of low-resource-language jailbreaks, Yong et al. 2023).
- cjk_variant: Japanese shinjitai / orthographic variants (对->対, 单->単).
  Same meaning, glyph the classifier regex never lists.
- cjk_punct: punctuation mutation to halfwidth/lookalike marks, which breaks
  regexes anchored on fullwidth CJK punctuation.
- cjk_zwsp: zero-width space between CJK ideographs only, breaking Chinese
  word segmentation while leaving ASCII text untouched.

All maps are one-to-one with unique targets, so every transform is lossless.
"""

ZWSP = "​"

# --- Near-duplicate ideographs (人眼难辨, Unicode distinct) -------------------
# Kangxi radicals (U+2F00-2FDF) are designed as glyph-identical stand-ins for
# their unified-ideograph counterparts and are vanishingly rare in real text,
# so the reverse map is safe. The classic 已->己 / 未->末 / 天->夭 pairs are
# kept as well (same trade-off as latin homoglyph: decode is exact for any
# text that does not legitimately contain the target glyphs).
CJK_LOOKALIKES = {
    "已": "己", "未": "末", "天": "夭",
    "人": "⼈", "口": "⼝", "土": "⼟", "干": "⼲", "白": "⽩",
    "日": "⽇", "目": "⽬", "木": "⽊", "水": "⽔", "火": "⽕",
    "田": "⽥", "王": "⽟", "大": "⼤",
}
CJK_LOOKALIKES_REVERSE = {v: k for k, v in CJK_LOOKALIKES.items()}

# --- Simplified -> Traditional (curated high-frequency subset) ---------------
# Only chars that actually differ between scripts are listed; identity chars
# pass through untouched. Curated for common functional + flagged vocabulary.
CJK_TRADITIONAL = {
    "拒": "拒", "绝": "絕", "绕": "繞", "破": "破", "解": "解",
    "伪": "偽", "造": "造", "执": "執", "行": "行", "禁": "禁",
    "止": "止", "删": "刪", "除": "除", "隐": "隱", "藏": "藏",
    "编": "編", "码": "碼", "锁": "鎖", "定": "定", "拦": "攔",
    "截": "截", "阻": "阻", "断": "斷", "攻": "攻", "击": "擊",
    "漏": "漏", "洞": "洞", "注": "注", "入": "入", "渗": "滲",
    "透": "透", "防": "防", "护": "護", "检": "檢", "测": "測",
    "审": "審", "查": "查", "过": "過", "滤": "濾", "规": "規",
    "则": "則", "许": "許", "可": "可", "证": "證", "书": "書",
    "钥": "鑰", "匙": "匙", "密": "密", "杀": "殺", "毒": "毒",
    "病": "病", "爆": "爆", "炸": "炸", "武": "武", "器": "器",
    "枪": "槍", "弹": "彈", "药": "藥", "火": "火", "窃": "竊",
    "盗": "盜", "账": "賬", "号": "號", "骗": "騙", "赌": "賭",
    "黄": "黃", "支": "支", "恐": "恐",
    "怖": "怖", "极": "極", "端": "端", "言": "言", "论": "論",
    "说": "說", "话": "話", "读": "讀", "写": "寫", "问": "問",
    "题": "題", "开": "開", "关": "關", "门": "門", "车": "車",
    "马": "馬", "鱼": "魚", "鸟": "鳥", "龙": "龍", "风": "風",
    "云": "雲", "电": "電", "脑": "腦", "网": "網", "络": "絡",
    "数": "數", "据": "據", "库": "庫", "系": "系", "统": "統",
    "结": "結", "构": "構", "给": "給", "发": "發", "现": "現",
    "实": "實", "验": "驗", "证": "證", "明": "明", "显": "顯",
    "示": "示", "输": "輸", "出": "出", "返": "返", "回": "回",
    "应": "應", "该": "該", "当": "當", "时": "時", "间": "間",
    "内": "內", "容": "容", "页": "頁", "面": "面", "文": "文",
    "件": "件", "夹": "夾",
}
# Drop accidental identity entries (char maps to itself) to keep the table honest.
CJK_TRADITIONAL = {k: v for k, v in CJK_TRADITIONAL.items() if k != v}
CJK_TRADITIONAL_REVERSE = {v: k for k, v in CJK_TRADITIONAL.items()}

# --- Japanese shinjitai / orthographic variants ------------------------------
CJK_VARIANTS = {
    "对": "対", "单": "単", "经": "経", "发": "発", "严": "厳",
    "铁": "鉄", "图": "図", "厅": "庁", "转": "転", "检": "検",
    "险": "険", "验": "験", "览": "覧", "实": "実", "学": "学",
    "樱": "桜", "泽": "沢", "边": "辺", "变": "変", "恋": "恋",
}
CJK_VARIANTS = {k: v for k, v in CJK_VARIANTS.items() if k != v}
CJK_VARIANTS_REVERSE = {v: k for k, v in CJK_VARIANTS.items()}

# --- Punctuation mutation -----------------------------------------------------
CJK_PUNCT = {
    "。": "｡", "、": "､", "，": "‚", "；": ";", "：": "∶",
    "《": "〈", "》": "〉", "！": "ǃ", "？": "ʔ", "（": "﹝", "）": "﹞",
}
CJK_PUNCT_REVERSE = {v: k for k, v in CJK_PUNCT.items()}


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF          # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF       # Extension A
        or 0xF900 <= cp <= 0xFAFF       # Compatibility Ideographs
    )


def _substitute(text: str, table: dict[str, str]) -> str:
    return "".join(table.get(c, c) for c in text)


def cjk_lookalike_encode(text: str) -> str:
    return _substitute(text, CJK_LOOKALIKES)


def cjk_lookalike_decode(text: str) -> str:
    return _substitute(text, CJK_LOOKALIKES_REVERSE)


def cjk_traditional_encode(text: str) -> str:
    return _substitute(text, CJK_TRADITIONAL)


def cjk_traditional_decode(text: str) -> str:
    return _substitute(text, CJK_TRADITIONAL_REVERSE)


def cjk_variant_encode(text: str) -> str:
    return _substitute(text, CJK_VARIANTS)


def cjk_variant_decode(text: str) -> str:
    return _substitute(text, CJK_VARIANTS_REVERSE)


def cjk_punct_encode(text: str) -> str:
    return _substitute(text, CJK_PUNCT)


def cjk_punct_decode(text: str) -> str:
    return _substitute(text, CJK_PUNCT_REVERSE)


def cjk_zwsp_encode(text: str) -> str:
    """Insert a zero-width space between adjacent CJK ideographs only.

    Breaks Chinese word segmentation (and the keyword regexes built on top
    of it) while leaving ASCII words, URLs, and code tokens contiguous.
    """
    out = []
    for i, ch in enumerate(text):
        if i and _is_cjk(ch) and _is_cjk(text[i - 1]):
            out.append(ZWSP)
        out.append(ch)
    return "".join(out)


def cjk_zwsp_decode(text: str) -> str:
    return text.replace(ZWSP, "")
