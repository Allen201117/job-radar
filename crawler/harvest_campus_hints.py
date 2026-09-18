"""从公开校招汇总页抓「公司名 → 网申链接」，写回 targets 文件的 campus_url_hint 字段。

定位：给车道 3（hint）**喂线索**的离线工具，不是抓取管道的一部分。
默认 dry-run，只打印；`--write` 才改 targets 文件。

🚩 线索不是入口，也不是证据：
  · 抓回来的链接**一律不入库**，只写进 targets 的 hint 字段，入库前照样走
    fingerprint → 归属核验 → probe 探活 → 真抓回读健康岗（与搜索车道同一道门）；
  · 第三方招聘平台域名（BOSS / 智联 / 前程无忧 / 猎聘…）命中即丢，
    由 campus_hints.is_allowed_hint 统一判定，这里不另写一份名单；
  · **只覆盖空的 hint**，不覆盖已有值 —— 已有值可能是人工核实过的，
    被一个未经核实的聚合站链接盖掉是净损失（`--overwrite` 才强制覆盖）。

用法：
    python3 harvest_campus_hints.py --source https://www.givemeoc.com/
    python3 harvest_campus_hints.py --source <url> --write
"""
import argparse
import json
import re
from html import unescape
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

import campus_hints


_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 20
# 「这条链接看着像网申入口吗」。只做粗筛，精筛在下游那几道门上。
_APPLY_RE = re.compile(
    r"(校园招聘|校招|网申|招聘|campus|recruit|careers?|jobs?|apply)", re.I)


def extract_pairs(html, base_url):
    """纯函数：汇总页 HTML → [(公司名, 链接)]。不发网络，可直接夹具单测。

    判据刻意保守 —— **锚文本本身当公司名**（聚合站几乎都是「公司名 → 官方网申」这种结构）。
    锚文本太短/太长、或链接不像网申入口的一律不要：宁可少收几条线索，
    也不要把「查看详情」「点击这里」这种通用锚文本当成公司名喂进车道 3
    （那会让 hint_for 精确匹配永远打不中，白占一条车道的退避窗口）。
    """
    try:
        anchors = HTMLParser(str(html or "")).css("a")
    except Exception:  # noqa: BLE001
        return []
    out, seen = [], set()
    for anchor in anchors:
        href = unescape(str(anchor.attributes.get("href") or "").strip())
        name = str(anchor.text(separator=" ", strip=True) or "").strip()
        if not href or not name or not (2 <= len(name) <= 20):
            continue
        url = urljoin(base_url, href)
        if not campus_hints.is_allowed_hint(url):
            continue
        if not _APPLY_RE.search(url) and not _APPLY_RE.search(name):
            continue
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def merge_into_targets(rows, pairs, *, overwrite=False):
    """纯函数：把 (公司名, 链接) 合并进 targets 行，返回 (新行列表, 改动条数)。

    只按**公司名精确同名**落位（与 campus_hints.hint_for 同口径：子串匹配会让
    「京东」吃到「京东方」的链接，那是张冠李戴红线）。匹配不到的线索直接丢，
    不新增 targets 行 —— targets 是「我们决定要覆盖哪些公司」的清单，
    不该被一个聚合站的抓取结果扩张。
    """
    table = {}
    for name, url in pairs:
        table.setdefault(name.strip(), url)
    changed = 0
    out = []
    for row in rows or []:
        row = dict(row)
        for key in ("company", "cn"):
            name = str(row.get(key) or "").strip()
            hint = table.get(name)
            if not hint:
                continue
            if row.get("campus_url_hint") and not overwrite:
                break
            if row.get("campus_url_hint") != hint:
                row["campus_url_hint"] = hint
                row["campus_evidence"] = "聚合站线索（未核实，入库前仍过探活+归属核验）"
                changed += 1
            break
        out.append(row)
    return out, changed


def fetch(url, *, client=None):
    own = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": _UA})
    try:
        response = own.get(url)
        return response.text if response.status_code == 200 else ""
    except Exception as exc:  # noqa: BLE001
        print(f"[hints] 取 {url} 失败：{type(exc).__name__}: {str(exc)[:120]}")
        return ""
    finally:
        if client is None:
            own.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="校招汇总页 → targets 的 campus_url_hint")
    parser.add_argument("--source", action="append", required=True,
                        help="公开校招汇总页 URL，可重复")
    parser.add_argument("--targets", default=campus_hints.TARGETS_FILE)
    parser.add_argument("--write", action="store_true", help="真的写回 targets 文件")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有 hint（默认只补空的）")
    args = parser.parse_args(argv)

    pairs = []
    for source in args.source:
        found = extract_pairs(fetch(source), source)
        print(f"[hints] {source} → 候选 {len(found)} 条")
        pairs.extend(found)

    with open(args.targets, encoding="utf-8") as handle:
        rows = json.load(handle)
    merged, changed = merge_into_targets(rows, pairs, overwrite=args.overwrite)
    print(f"[hints] 命中 targets 行 {changed} 条（write={args.write}）")
    for row in merged:
        if row.get("campus_evidence", "").startswith("聚合站线索"):
            print(f"    {row.get('company')}  →  {row.get('campus_url_hint')}")
    if args.write and changed:
        with open(args.targets, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=1)
        print(f"[hints] 已写回 {args.targets}")


if __name__ == "__main__":
    main()
