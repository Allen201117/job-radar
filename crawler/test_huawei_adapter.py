"""华为 adapter：抓全判定必须逐渠道算，否则 list-absence 撤岗永远跑不起来。

2026-07-28 实测：同一个岗会同时出现在多个 jobType 渠道（社招 4 条全部与实习渠道重复 →
三渠道 totalRows 之和 13、去重后唯一 jobId 只有 9）。旧写法
`fetch_complete = len(seen_ids) >= sum(channel_totals)` 拿**去重数**比**求和数**，
结构上永远为 False → 依赖它的 sweep_absent_jobs 一次都没跑过：
华为官网真实在招只剩 9 个岗，库里却压着 460 个 active 下不了架
（其中 440 个 enrich_checked_at 为 NULL，从未被探活）。
不打真实网络：mock httpx.Client。
"""
import json
import unittest

from adapters.huawei import HuaweiAdapter


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """按 jobType 返回可配的 (totalRows, jobId 列表)，支持分页。"""

    def __init__(self, channels):
        self.channels = channels
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def get(self, url):
        self.calls.append(url)
        job_type = url.split("jobType=")[1]
        page = int(url.split("curPage=")[1].split("&")[0])
        size = int(url.split("pageSize=")[1].split("&")[0])
        total, ids = self.channels[job_type]
        chunk = ids[(page - 1) * size: page * size]
        return _FakeResp({
            "pageVO": {"totalRows": total},
            "result": [{"jobId": i, "jobname": f"岗位 {i}"} for i in chunk],
        })


def _run(adapter, channels):
    import adapters.huawei as mod
    client = _FakeClient(channels)
    orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: client
    try:
        raw = adapter.fetch("https://career.huawei.com/reccampportal/portal5/social-recruitment.html")
    finally:
        mod.httpx.Client = orig
    return raw, client


class HuaweiFetchCompleteTest(unittest.TestCase):
    def test_complete_even_when_channels_share_job_ids(self):
        """跨渠道重复不该把「抓全了」判成「没抓全」——这正是旧实现的结构性 bug。"""
        adapter = HuaweiAdapter()
        _run(adapter, {"1": (4, [1, 2, 3, 4]),
                       "2": (0, []),
                       "3": (9, [1, 2, 3, 4, 5, 6, 7, 8, 9])})
        self.assertTrue(adapter.fetch_complete,
                        "三个渠道各自都抓到自报总数 = 抓全了，不能因为跨渠道去重就判 False")
        self.assertEqual(adapter.reported_total, 13)

    def test_incomplete_when_a_channel_is_short(self):
        """某渠道没抓到自报总数（接口异常/翻页封顶）→ 必须 False，否则 absence 会误杀活岗。"""
        adapter = HuaweiAdapter()
        _run(adapter, {"1": (4, [1, 2, 3, 4]),
                       "2": (0, []),
                       "3": (50, [10, 11, 12])})   # 自报 50 只给 3 条
        self.assertFalse(adapter.fetch_complete)

    def test_absence_liveness_must_stay_off(self):
        """🚫 立碑：华为**绝不能**开 list-absence 撤岗。

        2026-07-29 曾据「列表接口只返 13 条、库里 460 个 active」推断其余都是死岗并开了它。
        逐个核验后全错：用 getJobDetail/newHr 把 460 个岗一个个查了一遍，**460 个全在招**
        （例 jobId=30153 列表里查不到，详情接口照样返完整岗位名+正文）。
        列表接口返的是筛选过的子集 → 缺席 ≠ 撤岗。开了它，等存量降到列表规模 2 倍以内、
        50% 安全闸不再拦，就会成批删掉在招岗。撤岗只能靠逐岗 enrich._detail_huawei。"""
        self.assertFalse(HuaweiAdapter.supports_absence_liveness)

    def test_all_channels_are_queried(self):
        adapter = HuaweiAdapter()
        _, client = _run(adapter, {"1": (1, [1]), "2": (1, [2]), "3": (1, [3])})
        for job_type in ("1", "2", "3"):
            self.assertTrue(any(f"jobType={job_type}" in u for u in client.calls),
                            f"渠道 {job_type} 没被抓")


if __name__ == "__main__":
    unittest.main()
