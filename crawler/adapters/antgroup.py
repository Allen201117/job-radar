"""蚂蚁集团自建招聘门户适配器（零登录、零浏览器）。

talent.antgroup.com 是 UMI SPA，岗位数据走 hrcareersweb.antgroup.com 公开 JSON 接口
（2026-07-06 live 验证，无 ctoken/cookie 也放行）：
  - 社招：POST /api/social/position/search（channel=group_official_site，totalCount 分页）
  - 校招/实习：POST /api/campus/position/search（channel=campus_group_official_site）
pageSize 实测 ≤30 稳定（50 返回空）。列表行自带 description+requirement 作 summary。
逐岗详情页（live 验证可渲染标题+JD）：
  - 社招：talent.antgroup.com/off-campus-position?positionId={id}
  - 校招：talent.antgroup.com/campus-position?positionId={id}
⚠️ source_url 必须用根路径 https://talent.antgroup.com/（迁移 175）：社招详情页与列表页
/off-campus-position 同 host+path、仅差 ?positionId=，normalizer _url_key 忽略 query →
用列表页作 source_url 会把全部社招岗误判「jd_url equals source url」拦掉。
"""
import json
import re
from typing import List, Optional

import httpx

import must_apply
import normalizer
from .base import BaseAdapter, RawJob


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── 子公司归属派生（2026-09-04 加）─────────────────────────────────────────
# talent.antgroup.com 是蚂蚁系**全部业务线共用的同一个门户**，岗位标题用
# 「{业务线}-{岗位名}」自报归属。live 实测前缀分布（1604 岗）：
#   蚂蚁集团 630 / 蚂蚁国际 175 / 网商银行 92 / 蚂蚁数字科技 86 / OceanBase 58 /
#   研究型实习生 92 / 财富海外业务 27 / 蚂蚁消金 17 / 钱塘征信 7 / CTO 7 …
# 「网商银行」在必投清单（金融）里是**独立一条**、pattern `%网商银行%`，而此前库里
# 一个岗都没有 —— 那 92 个岗其实早在库里，只是全被记成「蚂蚁集团」。
#
# ⚠️ 两道**独立**门，缺一不可（照抄 netease 的 fail-safe 思路）：
#   ① `_DERIVABLE_SUBSIDIARIES` 白名单：只有人工核实过「确是独立法人实体、值得单独归属」
#      的业务线才允许派生。挡住「研究型实习生 / CTO / 产品经理」这类**根本不是公司名**的
#      前缀 —— 它们同样长得像「{X}-{岗位}」，纯靠正则会把 92 个实习岗打成一家叫
#      「研究型实习生」的公司。
#   ② 必投清单里**逐字存在**：派生出来的名字必须是清单规范名。清单哪天删掉「网商银行」，
#      派生自动关闭、那批岗回落「蚂蚁集团」，绝不会凭空造出一个库里没人认的公司名。
#
# ⚠️ 成立前提（2026-09-04 核实）：清单里「蚂蚁集团」pattern 是 `%蚂蚁%`，派生走 92 个岗后
# 母公司仍有 ~1512 个岗命中，**不会因为派生而掉成缺口**。往白名单加新业务线前必须重算这条。
_PARENT_COMPANY = "蚂蚁集团"
_DERIVABLE_SUBSIDIARIES = frozenset({"网商银行"})
_TITLE_PREFIX = re.compile(r"^\s*([^\s\-—－]{2,12})\s*[-—－]")


def _load_derivable_names() -> frozenset:
    """白名单 ∩ 必投清单规范名。读清单失败 → 空集合 → 派生整体关闭（全部回落母公司）。"""
    try:
        grouped = must_apply.by_industry()
    except Exception:  # noqa: BLE001 —— 清单读不到不许拖垮抓取，退化成「全记蚂蚁集团」
        return frozenset()
    listed = {
        (row.get("name") or "").strip()
        for companies in grouped.values()
        for row in companies
        if isinstance(row, dict)
    }
    return frozenset(name for name in _DERIVABLE_SUBSIDIARIES if name in listed)


# 模块级只算一次（清单是随仓库走的静态文件）。当前清单实测得到 {"网商银行"}。
_DERIVABLE_NAMES = _load_derivable_names()


def _derive_company(title) -> str:
    """岗位标题 → 必投清单规范名；派生不出返回 ""（调用方回落「蚂蚁集团」）。"""
    match = _TITLE_PREFIX.match(title if isinstance(title, str) else "")
    if not match:
        return ""
    prefix = match.group(1).strip()
    return prefix if prefix in _DERIVABLE_NAMES else ""


class AntGroupAdapter(BaseAdapter):
    name = "antgroup"
    company_name = "蚂蚁集团"

    API = "https://hrcareersweb.antgroup.com/api/{board}/position/search"
    SOCIAL_DETAIL = "https://talent.antgroup.com/off-campus-position?positionId={job_id}"
    CAMPUS_DETAIL = "https://talent.antgroup.com/campus-position?positionId={job_id}"
    PAGE_SIZE = 30  # 接口 live 实测：30 稳定返回，50 返回空
    MAX_PAGES = 80  # 30/页 → 封顶 2400 岗；当前社招 ~947 + 校招 ~328，余量充足

    _BOARDS = (
        ("social", "group_official_site"),
        ("campus", "campus_group_official_site"),
    )

    def _fetch_board(
        self,
        client: httpx.Client,
        board: str,
        channel: str,
    ) -> tuple[List[dict], Optional[int]]:
        rows: List[dict] = []
        total: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            payload = {
                "key": "", "regions": "", "categories": "", "subCategories": "",
                "bgCode": "", "socialQrCode": "",
                "pageIndex": page, "pageSize": self.PAGE_SIZE,
                "channel": channel, "language": "zh",
            }
            resp = client.post(self.API.format(board=board), json=payload)
            resp.raise_for_status()
            data = resp.json() or {}
            if total is None:
                total = _int_or_none(data.get("totalCount"))
            chunk = data.get("content") or []
            if not chunk:
                break
            rows.extend(chunk)
            if isinstance(total, int) and len(rows) >= total:
                break
            if len(chunk) < self.PAGE_SIZE:
                break
        return rows, total

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://talent.antgroup.com/",
            "Origin": "https://talent.antgroup.com",
        }
        out = {}
        totals: List[int] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for board, channel in self._BOARDS:
                rows, total = self._fetch_board(client, board, channel)
                out[board] = rows
                if total is not None:
                    totals.append(total)
        if not any(out.values()):
            raise RuntimeError("antgroup: empty position/search response")
        if len(totals) == len(self._BOARDS):
            self.reported_total = sum(totals)
        fetched = sum(len(rows) for rows in out.values())
        self.fetch_complete = (
            self.reported_total is not None and fetched >= self.reported_total
        )
        return json.dumps(out, ensure_ascii=False)

    @staticmethod
    def _experience_text(row: dict) -> Optional[str]:
        exp = row.get("experience")
        if not isinstance(exp, dict):
            return None
        low, high = exp.get("from"), exp.get("to")
        if isinstance(low, int) and isinstance(high, int):
            return f"{low}-{high}年"
        if isinstance(low, int) and low > 0:
            return f"{low}年以上"
        return None

    def _map_row(self, row: dict, board: str) -> Optional[RawJob]:
        job_id = str(row.get("id") or "").strip()
        title = str(row.get("name") or "").strip()
        if not (job_id and title):
            return None
        detail = self.SOCIAL_DETAIL if board == "social" else self.CAMPUS_DETAIL
        jd_url = detail.format(job_id=job_id)
        locations = [str(c).strip() for c in (row.get("workLocations") or []) if str(c).strip()]
        description = str(row.get("description") or "").strip()
        requirement = str(row.get("requirement") or "").strip()
        summary = (
            description + ("\n【任职要求】\n" + requirement if requirement else "")
        ).strip() or None
        if board == "social":
            job_type = "社招"
        else:
            job_type = "实习" if "实习" in title else "校招"
        return RawJob(
            company=_derive_company(title) or self.company_name,
            title=title,
            location="、".join(dict.fromkeys(locations)) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(row),
            experience=self._experience_text(row),
        )

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        seen = set()
        for board in ("social", "campus"):
            for row in data.get(board) or []:
                if not isinstance(row, dict):
                    continue
                job = self._map_row(row, board)
                if job is None or job.jd_url in seen:
                    continue
                seen.add(job.jd_url)
                jobs.append(job)
        return jobs
