"""香港 jobs 库可达性探针（CI guard job 用）。

存在的理由：抓取/巡检的矩阵分片在「够不着库」时是**软失败**的（记台账 + 退 0），
因为实测那多半只是该分片所在 runner 的出口 IP 被路径上掐掉（同一轮其余分片连得好好的），
重试无用、且队列幂等下一轮会补上 —— 不值得把整轮 CI 拖红成告警噪音。

代价是「库真的挂了」也会全绿。本探针就是补这个洞：在矩阵跑完后换一台干净 runner
亲自连一次库并跑一条 `select 1`，连不上才判定为真故障（退 1，整轮变红）。

诚实边界：探针用的是又一个随机出口 IP，所以它是很强的信号、不是数学证明。
每个软失败的分片都会在 ops_runs 台账里留 status=failed，运营看板可见真实损耗。
"""
import sys

import jobs_db


def main():
    try:
        conn = jobs_db.get_conn()
    except jobs_db.JobsDbUnreachable as exc:
        # 分片够不着可以放过，guard 够不着不行 —— 这已经不像「单个 IP 倒霉」了。
        print(f"✗ 香港 jobs 库不可达（建连重试预算已烧光）：{exc}")
        print("✗ 判定为真故障：矩阵分片的软失败不再算噪音，请查库/链路。")
        return 1

    with conn.cursor() as cur:
        cur.execute("select 1")
        cur.fetchone()
    conn.close()
    print("✓ 香港 jobs 库可达（本轮分片若有软失败，属单 runner 出口 IP 问题，非库故障）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
