"""小红书招聘（job.xiaohongshu.com）自建门户适配器（直连公开 JSON 接口，零浏览器）。

门户 JS 公开 POST `https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition`
（json: pageNum + pageSize + recruitType=social|campus|intern）返回明文 JSON（无需登录/签名）：
  {"statusCode":200,"data":{"total":N,"list":[{positionId, positionName, duty,
   qualification, workplace("上海市，北京市"), jobType, jobProjectName, publishTime}]}}
逐岗稳定详情页 = `https://job.xiaohongshu.com/{social|campus}/position/{positionId}`
（id-only；live render-verify 过：social/20317 与 campus/19387 均渲染出本岗标题+正文，过质量门）。
company 恒为「小红书」（自建门户，无张冠李戴风险）。intern 渠道与 campus 高度重叠，
按 positionId 去重，首见渠道优先（social→campus→intern）。
"""
import json
from typing import Optional

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# recruitType → 详情页路由前缀（intern 共用 campus 路由）
_CHANNEL_PATH = {"social": "social", "campus": "campus", "intern": "campus"}
# recruitType → 三桶分类信号（normalizer 同口径）
_CHANNEL_LABEL = {"social": "社会招聘", "campus": "校园招聘", "intern": "实习"}


class XiaohongshuAdapter(PlaywrightAdapter):
    """小红书自建门户 job.xiaohongshu.com。source_url 填
    `https://job.xiaohongshu.com/`，adapter 内部遍历 social/campus/intern 三渠道。"""

    name = "xiaohongshu"
    company_name = "小红书"
    official_hosts = ("job.xiaohongshu.com",)

    _API = "https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition"
    _DETAIL = "https://job.xiaohongshu.com/{path}/position/{id}"
    _PAGE_SIZE = 50
    _MAX_PAGES = 20   # 50×20=1000/渠道 封顶（社招实有 ~862）
    posts_keys = ("data.list",) + PlaywrightAdapter.posts_keys

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json",
            "Referer": "https://job.xiaohongshu.com/",
            "Origin": "https://job.xiaohongshu.com",
        }
        collected = []
        seen_ids = set()
        channel_totals = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for channel in ("social", "campus", "intern"):
                got = 0
                total: Optional[int] = None
                for page in range(1, self._MAX_PAGES + 1):
                    try:
                        resp = client.post(self._API, json={
                            "pageNum": page, "pageSize": self._PAGE_SIZE,
                            "recruitType": channel,
                        })
                        resp.raise_for_status()
                        payload = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    data = payload.get("data") or {}
                    if total is None:
                        total = _int_or_none(data.get("total"))
                    rows = data.get("list") or []
                    if not rows:
                        break
                    fresh = []
                    for row in rows:
                        pid = row.get("positionId")
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                        row["_channel"] = channel
                        fresh.append(row)
                    if fresh:
                        collected.append({"data": {"list": fresh}})
                    got += len(rows)
                    if total and got >= total:
                        break
                if total is not None:
                    channel_totals.append(total)
        if not collected:
            raise RuntimeError("xiaohongshu: empty pageQueryPosition (job.xiaohongshu.com)")
        if len(channel_totals) == 3:
            self.reported_total = sum(channel_totals)
        self.fetch_complete = (
            self.reported_total is not None and len(seen_ids) >= self.reported_total
        )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        pid = _first(post, ("positionId",))
        title = _first(post, ("positionName", "name"))
        if not (pid and title):
            return None
        duty = _first(post, ("duty",))
        qual = _first(post, ("qualification",))
        summary = (duty + ("\n\n【任职资格】\n" + qual if qual else "")).strip() or None
        channel = post.get("_channel") or "social"
        jd_url = self._DETAIL.format(path=_CHANNEL_PATH.get(channel, "social"), id=pid)
        # workplace 形如「上海市，北京市」，取首城作主地点
        workplace = _first(post, ("workplace",))
        location = workplace.split("，")[0].strip() if workplace else None
        return RawJob(
            company=self.company_name,
            title=title,
            location=location or None,
            job_type=_CHANNEL_LABEL.get(channel) or _first(post, ("jobType",)) or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
