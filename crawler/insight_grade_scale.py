"""公开讨论洞察的 1–5 档位口径与 LLM 输出收敛。

这里刻意只放纯函数：档位语义必须由同一份明确口径驱动，避免不同批次的
prompt 或写入脚本各自理解「加班多」「晋升快」。模型仅可映射原句；看不出
强弱就留空，宁缺毋滥。
"""
import json
import math
from typing import Any, Optional


GRADE_UNIT = "档"

# 这是可筛选值的唯一口径；prompt 会逐字带上对应主题的全部五档，不能让模型自行发挥。
GRADE_SCALES: dict[str, dict[int, str]] = {
    "overtime_level": {
        1: "准时下班 / 双休规律 / 明确反 996",
        2: "偶有加班，整体可控",
        3: "加班常见但不极端（说法里只说「有加班」「节奏快」）",
        4: "加班多 / 晚下班是常态 / 单休",
        5: "996 / 大小周 / 通宵常态",
    },
    "promotion_pace": {
        1: "晋升极难 / 天花板低 / 论资排辈",
        2: "偏慢 / 通道不清晰",
        3: "中等，与绩效挂钩",
        4: "通道清晰、有机会",
        5: "晋升快 / 内部提拔多 / 明确的培养路径",
    },
    "intern_experience": {
        1: "打杂 / 无带教 / 难转正 / 有负面反馈",
        2: "一般，转正不确定",
        3: "中等，有基本安排",
        4: "有带教、有真实项目",
        5: "带教完善 / 转正率高 / 有明确留用通道",
    },
}


def is_gradable(metric_key: str) -> bool:
    """只有三类说法层主题可映射档位，数值型主题继续走各自的正则抽取。"""
    return metric_key in GRADE_SCALES


def coerce_grade(value: Any) -> Optional[int]:
    """把模型返回值收敛为 1–5 的整数；无法判断时返回 None。

    绝不把 0、6 或脏文本 clamp 到边界档：那会把模型未判出的内容伪造成
    「最轻」或「最重」，直接误导筛选结果。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    grade = int(number)
    return grade if grade in (1, 2, 3, 4, 5) else None


def build_prompt(metric_key: str, items: list[dict]) -> list[dict]:
    """构造严格的映射 prompt；每个输入 item 的 i 与返回位置一一对应。"""
    if not is_gradable(metric_key):
        raise ValueError(f"metric_key is not gradable: {metric_key}")

    scale_lines = "\n".join(
        f"{grade} = {meaning}" for grade, meaning in GRADE_SCALES[metric_key].items()
    )
    records = [
        {"i": index, "content": str((item or {}).get("content") or "")}
        for index, item in enumerate(items or [])
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是严格的文本档位映射器。只可根据原句把内容映射到给定档位，"
                "不补充常识、不推断公司实际情况。原句看不出强弱时必须返回 null。\n"
                f"主题：{metric_key}\n"
                "档位定义（必须按此原样理解）：\n"
                f"{scale_lines}"
            ),
        },
        {
            "role": "user",
            "content": (
                "请逐条映射。只输出严格 JSON，不要 markdown 或解释："
                '{"grades":[{"i":序号,"g":档位或null}]}。\n'
                f"待处理内容：{json.dumps(records, ensure_ascii=False)}"
            ),
        },
    ]


def parse_response(payload: Any, batch_size: int) -> list[Optional[int]]:
    """按 i 归位解析模型输出，任何不确定项保留 None，绝不按列表位置猜。

    LLM 可能漏项或返回乱序；若改为按返回数组顺序写库，后半批公司会收到前一条
    公司的档位。因此仅接受合法、唯一且在范围内的 i，缺项与重复项一律不写。
    """
    try:
        size = int(batch_size)
    except (TypeError, ValueError):
        return []
    if size <= 0:
        return []

    result: list[Optional[int]] = [None] * size
    grades = payload.get("grades") if isinstance(payload, dict) else None
    if not isinstance(grades, list):
        return result

    seen: set[int] = set()
    duplicate_indexes: set[int] = set()
    for item in grades:
        if not isinstance(item, dict):
            continue
        index = item.get("i")
        # bool 是 Python 的 int 子类，但不是模型可用的序号。
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < size:
            continue
        if index in seen:
            duplicate_indexes.add(index)
            result[index] = None
            continue
        seen.add(index)
        result[index] = coerce_grade(item.get("g"))

    for index in duplicate_indexes:
        result[index] = None
    return result
