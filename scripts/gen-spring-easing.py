#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 app/globals.css 里的 --spring-* 曲线值。

为什么要有这个脚本：那几行 linear() 是 41 个采样点，人手改不了也看不懂。
要调手感就改下面的 PRESETS 跑一次，把输出粘回 globals.css 的动效基座段。

档位参数沿用 SwiftUI 的 spring(response:dampingFraction:)：
  response       = 完成一次振荡的时间感，越小越快
  dampingFraction= 阻尼比，1.0 不过冲，越小回弹越明显
"""
import math

PRESETS = [
    ("smooth", 0.30, 1.00, "状态切换 / 淡入淡出：不能有回弹"),
    ("snappy", 0.25, 0.85, "开关 / 弹层进场 / 折叠：极小过冲，最常用"),
    ("bouncy", 0.30, 0.62, "数字变化 / 正反馈：明显回弹"),
    ("press", 0.15, 0.80, "按压松手回弹：最短"),
]
SAMPLES = 40


def curve(response: float, zeta: float, n: int = SAMPLES):
    """解弹簧方程并采样。返回 (沉降毫秒, linear() 的点串, 最大过冲)。"""
    w0 = 2 * math.pi / response
    settle = -math.log(0.001) / (zeta * w0)  # 包络衰减到 0.1%
    pts = []
    for i in range(n + 1):
        t = settle * i / n
        if abs(zeta - 1.0) < 1e-9:  # 临界阻尼
            x = 1 - math.exp(-w0 * t) * (1 + w0 * t)
        elif zeta < 1:  # 欠阻尼
            wd = w0 * math.sqrt(1 - zeta * zeta)
            x = 1 - math.exp(-zeta * w0 * t) * (
                math.cos(wd * t) + (zeta * w0 / wd) * math.sin(wd * t)
            )
        else:  # 过阻尼
            d = math.sqrt(zeta * zeta - 1)
            r1, r2 = -w0 * (zeta - d), -w0 * (zeta + d)
            x = 1 + (-r2 / (r1 - r2)) * math.exp(r1 * t) + (r1 / (r1 - r2)) * math.exp(r2 * t)
        pts.append(x)
    return round(settle * 1000), ", ".join("%.4g" % p for p in pts), max(pts)


if __name__ == "__main__":
    for name, response, zeta, note in PRESETS:
        dur, body, peak = curve(response, zeta)
        print("    /* %s — %s（过冲 %.1f%%）*/" % (name, note, (peak - 1) * 100))
        print("    --spring-%s: linear(%s);" % (name, body))
        print("    --spring-%s-dur: %dms;" % (name, dur))
        print()
