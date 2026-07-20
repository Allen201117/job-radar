"""扩源覆盖度报告 —— 看「各公司岗位爬取通道打通进度」（按模块 segment × 行业 industry）。

产品核心价值 = 一家一家把公司爬取通道打通；本脚本统计已打通通道数（sources 行数，enabled 为活跃），
按 模块（外企/国企央企/中国私企）× 行业 汇总，让进度可量化、看出哪些行业还缺。

用法（本机，需 .env.local 里有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
  cd crawler && python3 coverage.py
"""
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from db import fetch_all_rows, get_supabase  # noqa: E402

_SEG_LABEL = {"foreign": "外企", "soe": "国企央企", "private": "中国私企", None: "未分类"}


def main():
    sb = get_supabase()
    # 分页拉全量：sources 已越过 PostgREST 单次 1000 行硬顶（2026-07-20 实测 1121）→ 不分页报出来的覆盖度是残缺的。
    rows = fetch_all_rows(
        lambda: sb.table("sources").select("company,adapter_name,segment,industry,enabled"))

    # 按 segment → industry 聚合通道（公司）数；区分 enabled / 总数
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # seg -> ind -> [total, enabled]
    seg_total = defaultdict(lambda: [0, 0])
    for r in rows:
        seg = r.get("segment")
        ind = r.get("industry") or "（未填行业）"
        en = 1 if r.get("enabled") else 0
        agg[seg][ind][0] += 1
        agg[seg][ind][1] += en
        seg_total[seg][0] += 1
        seg_total[seg][1] += en

    print(f"\n扩源覆盖度报告（共 {len(rows)} 条通道 / {sum(t[1] for t in seg_total.values())} 条活跃）\n" + "=" * 52)
    for seg in ("foreign", "private", "soe", None):
        if seg not in agg:
            continue
        tot, en = seg_total[seg]
        print(f"\n【{_SEG_LABEL.get(seg, seg)}】 {tot} 家通道（活跃 {en}）")
        for ind in sorted(agg[seg], key=lambda k: -agg[seg][k][0]):
            t, e = agg[seg][ind]
            print(f"    {ind:<14} {t:>3} 家（活跃 {e}）")
    print("\n" + "=" * 52)
    print("提示：每打通一家新公司通道，记得在 sources 行带上 segment + industry。")


if __name__ == "__main__":
    main()
