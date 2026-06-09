"""beisen 候选并发 job-confirm（多进程，每进程独立 playwright）。
discover_domestic.py 导出的 beisen_candidates.json（仅 tenant title-verified）逐家用真 BeisenAdapter
跑岗位抽取 + 质量门，只把**真返回岗位**的写迁移（老版可抽的入库；新版异构抽不出的自动丢弃）。

用法：python3 confirm_beisen_parallel.py beisen_candidates.json 110 [workers]
"""
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(__file__))
import probe  # noqa: E402


def _one(c):
    try:
        r = probe.probe_one(c, timeout=30)
    except Exception as e:
        r = {"ok": False, "valid": 0, "reason": f"{type(e).__name__}: {e}"}
    return {**c, "_valid": r.get("valid", 0), "_china": r.get("china", r.get("valid", 0)),
            "sample": r.get("sample", ""), "reason": r.get("reason", "")}


def main():
    cand_path = sys.argv[1]
    prefix = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    with open(cand_path, encoding="utf-8") as f:
        cands = json.load(f)
    print(f"[confirm-beisen] {len(cands)} 候选 × {workers} 进程 ...", flush=True)
    with Pool(workers) as p:
        results = p.map(_one, cands)

    passed = [r for r in results if r.get("_valid", 0) > 0]
    for r in sorted(results, key=lambda x: -x.get("_valid", 0)):
        flag = "✓" if r.get("_valid", 0) > 0 else "✗"
        chan = r["url"].rstrip("/").split("/")[-1]
        print(f"  {flag} {r['company'][:16]:18}{chan:8} {r.get('_valid',0):>4}  "
              f"{(r.get('sample') or r.get('reason',''))[:46]}", flush=True)

    won = sorted({r["company"] for r in passed})
    print(f"\n[confirm-beisen] 通过源行 {len(passed)} / 公司 {len(won)}：{', '.join(won)}")
    if passed:
        path = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                            f"{prefix}_seed_probed_sources.sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(probe.emit_sql(prefix, passed))
        print(f"[confirm-beisen] 已写 {os.path.relpath(path)}（{len(passed)} 源行）。")


if __name__ == "__main__":
    main()
