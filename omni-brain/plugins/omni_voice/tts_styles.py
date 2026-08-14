"""IndexTTS2 情感风格预设（M32.30：台配灰原哀声线调优 v2）。

台配灰原哀（魏晶琦）声线核心特征：
- 少女音域但音色偏成熟冷冽，不是软萌萝莉
- 声线干净通透，略带清冷的质感
- 台湾国语腔调：咬字清晰、卷舌弱、部分字词有台味发音（如「的」偏「滴」、
  「了」偏「搂」）但不刻意夸张
- 情绪起伏含蓄——即使吐槽/关心/着急，也从不歇斯底里
- 句尾处理干脆，很少拖音上扬，常带一丝轻微的冷淡/无奈尾调
- 发声位置在中前部，气声少，靠唇齿咬字而不是靠喉咙

提示词结构（指南）：语速基调 + 情绪浓度 + 台味咬字 + 发声位置 + 句尾处理。
提示词仅控制语气节奏；音色由参考音频（ref_audio）决定，故提示词中
不重复角色名，避免干扰模型判断。

基准生成参数（指南第三步）：top_p 0.75，temperature 0.65；
情感强度（emo_alpha）按场景微调，台配灰原哀整体情绪浓度偏低（克制美学），
但 emo_alpha 需设到足以让模型感知 emo_text（建议 ≥0.5）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TTSStyle:
    """单个情感风格预设。

    - ``name``        ：场景标识（稳定英文枚举，供配置 / CLI 使用）
    - ``label``       ：中文名（展示用）
    - ``emo_text``    ：语气提示词（透传 IndexTTS2 emo_text）
    - ``emo_alpha``   ：情感强度（0-1，透传 emo_alpha）
    - ``top_p``       ：生成采样 top_p（服务端支持时透传）
    - ``temperature`` ：生成采样温度（服务端支持时透传）
    - ``description`` ：适用场景说明
    """

    name: str
    label: str
    emo_text: str
    emo_alpha: float
    top_p: float = 0.75
    temperature: float = 0.65
    description: str = ""


# 台味咬字与发声基础描述（各风格共享前缀）
_TW_BASE = "台湾女配音员腔调，咬字清晰、卷舌弱，少女音但声线成熟冷冽"
_TW_VOICE = "声线干净通透，发声位置在中前部，靠唇齿咬字，气声少，声音略带清冷颗粒感"
_TW_CADENCE = "语句节奏自然不机械化，有真人呼吸感"

TTS_STYLES: dict[str, TTSStyle] = {
    "calm": TTSStyle(
        name="calm",
        label="日常冷静款",
        emo_text=(
            f"{_TW_BASE}，{_TW_VOICE}。{_TW_CADENCE}，"
            "语速中等偏缓，语气平淡从容，淡淡的疏离感，"
            "情绪收敛、波澜不惊，句尾轻收不上扬不拖音，"
            "像在冷静陈述事实，偶尔带一丝轻微的无奈"
        ),
        emo_alpha=0.65,
        description="分析陈述、日常平淡对话（基准音色，最常用）",
    ),
    "sad": TTSStyle(
        name="sad",
        label="沉思忧伤款",
        emo_text=(
            f"{_TW_BASE}，{_TW_VOICE}。{_TW_CADENCE}，"
            "语速放慢，语气沉静低落，藏着无法言说的忧伤但绝不崩溃，"
            "气声略增，声音比平时稍沉，"
            "语句间有短暂停顿，尾音极轻如轻叹，全程克制隐忍，"
            "句尾下沉，像在自言自语"
        ),
        emo_alpha=0.75,
        top_p=0.7,
        temperature=0.6,
        description="回忆过往、独处独白、失落情绪",
    ),
    "teasing": TTSStyle(
        name="teasing",
        label="吐槽调侃款",
        emo_text=(
            f"{_TW_BASE}，{_TW_VOICE}。{_TW_CADENCE}，"
            "语速略快于日常，语气带着半开玩笑的吐槽感，"
            "有一丝无奈加敷衍的味道，尾音微微下沉带点懒懒的感觉，"
            "情绪不张扬，嘴角像是微微勾起，"
            "偶尔在关键句尾加一点点微妙的停顿，营造吐槽节奏感"
        ),
        emo_alpha=0.7,
        top_p=0.8,
        temperature=0.7,
        description="吐槽调侃、无奈的日常互动、柯南式对话",
    ),
    "serious": TTSStyle(
        name="serious",
        label="郑重警告款",
        emo_text=(
            f"{_TW_BASE}，{_TW_VOICE}。{_TW_CADENCE}，"
            "语速平稳坚定，语气严肃冷静，带着不容置疑的紧迫与认真，"
            "咬字比平时稍重，气息沉稳，"
            "声音微微压低，句与句之间间隔略短，传递紧张感，"
            "但绝不嘶吼尖叫，压迫感藏在平静的坚定里"
        ),
        emo_alpha=0.8,
        top_p=0.7,
        temperature=0.55,
        description="提醒危险、严肃告诫、关键推理信息",
    ),
    "gentle": TTSStyle(
        name="gentle",
        label="温柔关心款",
        emo_text=(
            f"{_TW_BASE}，{_TW_VOICE}。{_TW_CADENCE}，"
            "语速轻柔缓慢，语气温柔，是那种嘴硬心软式的关心，"
            "声音比平时放软半分但不甜腻，"
            "句尾轻收带一点点不易察觉的暖意，"
            "像是在用冷静的外表包裹柔软的情绪，不直白说关心"
        ),
        emo_alpha=0.7,
        top_p=0.75,
        temperature=0.65,
        description="关心同伴、安慰、柔软的私人对话",
    ),
}

#: 默认风格：日常冷静款（基准音色）
DEFAULT_STYLE = "calm"


def get_style(name: str) -> TTSStyle:
    """按名取风格预设；未知名抛 ``ValueError``（附可选清单）。"""
    style = TTS_STYLES.get(name)
    if style is None:
        valid = "、".join(sorted(TTS_STYLES))
        raise ValueError(f"未知 TTS 风格: {name!r}（可选: {valid}）")
    return style
