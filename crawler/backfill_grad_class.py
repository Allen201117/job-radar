"""回填薄卡遗留的岗位届别。

遗留的成因是：岗位初次入库时是没有正文的薄卡，届别抽取不到；之后 enrich 补上正文，
旧写入口却只更新 summary，没有重新写 grad_class。这个脚本只补仍为 NULL 且能从
标题、岗位类型或正文中抽出硬信号的在招岗位。

抽不出就留空，绝不按入库时间或上下文猜届别。猜错会把往届岗误标成当季，伤害投递判断。

用法：
    python3 crawler/backfill_grad_class.py
    python3 crawler/backfill_grad_class.py --limit 100
    python3 crawler/backfill_grad_class.py --apply --batch 2000
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_db  # noqa: E402
from grad_class import extract_grad_class  # noqa: E402


def positive_int(raw: str) -> int:
    """argparse 的正整数类型。"""
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return value


def fetch_candidates(cur, last_id, batch_size):
    """按主键游标取一批候选，更新期间不使用 OFFSET，避免候选集缩小后跳行。"""
    where = "status = 'active' and grad_class is null"
    params = []
    if last_id is not None:
        where += " and id > %s"
        params.append(last_id)
    params.append(batch_size)
    cur.execute(
        f"""
        select id, title, job_type, summary
        from jobs
        where {where}
        order by id
        limit %s
        """,
        params,
    )
    return cur.fetchall()


def backfill(conn, apply=False, limit=None, batch_size=2000):
    """扫描并按需回填，返回扫过、抽出、实际写入和届别分布。"""
    scanned = 0
    extracted = 0
    updated = 0
    distribution = Counter()
    last_id = None

    with conn.cursor() as cur:
        while limit is None or scanned < limit:
            request_size = batch_size if limit is None else min(batch_size, limit - scanned)
            rows = fetch_candidates(cur, last_id, request_size)
            if not rows:
                break
            for job_id, title, job_type, summary in rows:
                scanned += 1
                grad_class = extract_grad_class(title, job_type, summary)
                if grad_class is not None:
                    extracted += 1
                    distribution[grad_class] += 1
                    if apply:
                        cur.execute(
                            "update jobs set grad_class = %s where id = %s and grad_class is null",
                            [grad_class, job_id],
                        )
                        updated += cur.rowcount
                last_id = job_id
            if len(rows) < request_size:
                break

    return {
        "scanned": scanned,
        "extracted": extracted,
        "updated": updated,
        "distribution": distribution,
    }


def print_report(stats, apply):
    """打印 dry-run 与实际写入共用的简明报告。"""
    print(f"扫描候选：{stats['scanned']} 行")
    print(f"抽出届别：{stats['extracted']} 行")
    if apply:
        print(f"实际回填：{stats['updated']} 行")
    else:
        print(f"dry-run 预计回填：{stats['extracted']} 行（未写库）")
    print("\n届别分布：")
    if not stats["distribution"]:
        print("  无")
        return
    print(f"{'届别':>8}{'行数':>10}")
    for grad_class, count in sorted(stats["distribution"].items(), reverse=True):
        print(f"{grad_class:>8}{count:>10}")


def main():
    parser = argparse.ArgumentParser(description="回填正文已补齐但届别仍为空的在招岗位")
    parser.add_argument("--apply", action="store_true", help="真的写库；默认只 dry-run 报数")
    parser.add_argument("--limit", type=positive_int, help="最多处理前 N 个候选，便于小样本试跑")
    parser.add_argument("--batch", type=positive_int, default=2000, help="每批读取行数，默认 2000")
    args = parser.parse_args()

    if not jobs_db.enabled():
        print("JOBS_DATABASE_URL 未配置，退出（本脚本只对自建香港 jobs 库生效）")
        return 1

    # jobs_db.get_conn() 已经把连接设成 autocommit=True（见该函数注释），所以这里
    # 不需要显式 commit；**别照着别的脚本加 `with conn:`**——那会开一个显式事务、
    # 反而让 autocommit 语义变味。改动这段前先回去看 get_conn 怎么建的连接。
    conn = jobs_db.get_conn()
    try:
        stats = backfill(conn, apply=args.apply, limit=args.limit, batch_size=args.batch)
        print_report(stats, apply=args.apply)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
