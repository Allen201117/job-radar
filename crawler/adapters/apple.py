import json
import time
import re
from urllib.parse import urlencode

import httpx
from typing import List, Optional

import normalizer
from geo import _GREATER_CHINA
from .base import BaseAdapter, PageResult, RawJob, exc_brief, paginate_all

# 列表行的 locations[].countryID 形如 "iso-country-USA"：Apple 自报的国家，ISO-3166-1 alpha-3。
# RawJob.country_code 要 alpha-2，所以带一张完整对照表（249 项，与 geo.ISO_ALPHA2_CODES 一一对应，单测钉着）。
# 这是结构化字段里的码，不是从地点文本里抠出来的三个字母，没有 workday 路径那种撞车问题（PHL = 费城）。
_COUNTRY_ID_RE = re.compile(r"iso-country-([A-Z]{3})")
_ISO3_TO_ISO2 = dict(pair.split(":") for pair in (
    "ABW:AW AFG:AF AGO:AO AIA:AI ALA:AX ALB:AL AND:AD ARE:AE ARG:AR ARM:AM ASM:AS ATA:AQ ATF:TF ATG:AG "
    "AUS:AU AUT:AT AZE:AZ BDI:BI BEL:BE BEN:BJ BES:BQ BFA:BF BGD:BD BGR:BG BHR:BH BHS:BS BIH:BA BLM:BL "
    "BLR:BY BLZ:BZ BMU:BM BOL:BO BRA:BR BRB:BB BRN:BN BTN:BT BVT:BV BWA:BW CAF:CF CAN:CA CCK:CC CHE:CH "
    "CHL:CL CHN:CN CIV:CI CMR:CM COD:CD COG:CG COK:CK COL:CO COM:KM CPV:CV CRI:CR CUB:CU CUW:CW CXR:CX "
    "CYM:KY CYP:CY CZE:CZ DEU:DE DJI:DJ DMA:DM DNK:DK DOM:DO DZA:DZ ECU:EC EGY:EG ERI:ER ESH:EH ESP:ES "
    "EST:EE ETH:ET FIN:FI FJI:FJ FLK:FK FRA:FR FRO:FO FSM:FM GAB:GA GBR:GB GEO:GE GGY:GG GHA:GH GIB:GI "
    "GIN:GN GLP:GP GMB:GM GNB:GW GNQ:GQ GRC:GR GRD:GD GRL:GL GTM:GT GUF:GF GUM:GU GUY:GY HKG:HK HMD:HM "
    "HND:HN HRV:HR HTI:HT HUN:HU IDN:ID IMN:IM IND:IN IOT:IO IRL:IE IRN:IR IRQ:IQ ISL:IS ISR:IL ITA:IT "
    "JAM:JM JEY:JE JOR:JO JPN:JP KAZ:KZ KEN:KE KGZ:KG KHM:KH KIR:KI KNA:KN KOR:KR KWT:KW LAO:LA LBN:LB "
    "LBR:LR LBY:LY LCA:LC LIE:LI LKA:LK LSO:LS LTU:LT LUX:LU LVA:LV MAC:MO MAF:MF MAR:MA MCO:MC MDA:MD "
    "MDG:MG MDV:MV MEX:MX MHL:MH MKD:MK MLI:ML MLT:MT MMR:MM MNE:ME MNG:MN MNP:MP MOZ:MZ MRT:MR MSR:MS "
    "MTQ:MQ MUS:MU MWI:MW MYS:MY MYT:YT NAM:NA NCL:NC NER:NE NFK:NF NGA:NG NIC:NI NIU:NU NLD:NL NOR:NO "
    "NPL:NP NRU:NR NZL:NZ OMN:OM PAK:PK PAN:PA PCN:PN PER:PE PHL:PH PLW:PW PNG:PG POL:PL PRI:PR PRK:KP "
    "PRT:PT PRY:PY PSE:PS PYF:PF QAT:QA REU:RE ROU:RO RUS:RU RWA:RW SAU:SA SDN:SD SEN:SN SGP:SG SGS:GS "
    "SHN:SH SJM:SJ SLB:SB SLE:SL SLV:SV SMR:SM SOM:SO SPM:PM SRB:RS SSD:SS STP:ST SUR:SR SVK:SK SVN:SI "
    "SWE:SE SWZ:SZ SXM:SX SYC:SC SYR:SY TCA:TC TCD:TD TGO:TG THA:TH TJK:TJ TKL:TK TKM:TM TLS:TL TON:TO "
    "TTO:TT TUN:TN TUR:TR TUV:TV TWN:TW TZA:TZ UGA:UG UKR:UA UMI:UM URY:UY USA:US UZB:UZ VAT:VA VCT:VC "
    "VEN:VE VGB:VG VIR:VI VNM:VN VUT:VU WLF:WF WSM:WS YEM:YE ZAF:ZA ZMB:ZM ZWE:ZW"
).split())


def _declared_country(locations) -> Optional[str]:
    """列表行里 Apple 自报的国家（ISO-2），交给 RawJob.country_code；normalize 只在地点文本判不出国家时采信。

    地点的 name 多半只是门店 / 园区 / 城市名（Cambridge / Maiden / Bellevue Square / Melbourne），
    同名地点在别国也有，按名字认国家会错；国家在同一个对象的 countryID 里，对方已经报了。

    ⚠️ 宁可漏判（与 workday._declared_country 同一条纪律）：一行挂多个地点时，任何一个在大中华就报大中华；
    有地点没报国家、或报的不是 ISO 码，就什么都不报——回到 normalize 原来的判法，不替对方猜。
    """
    codes = []
    for loc in locations or []:
        if not isinstance(loc, dict):
            continue
        m = _COUNTRY_ID_RE.fullmatch(str(loc.get("countryID") or ""))
        codes.append(_ISO3_TO_ISO2.get(m.group(1)) if m else None)
    for code in codes:
        if code in _GREATER_CHINA:
            return code
    return codes[0] if codes and all(codes) else None


class AppleAdapter(BaseAdapter):
    """Apple Jobs — public search page hydration data."""

    name = "apple"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )
    SEARCH_URL = "https://jobs.apple.com/en-us/search"
    SEARCH_LOCATION = "united-states-USA"  # 子类置空 = 不限地点（全球混合，再按需过滤）
    CHINA_ONLY = False                      # 子类置 True = parse 后只保留在华/remote 岗

    PAGE_SIZE = 20        # Apple 搜索页每页固定 20 条（实测）
    MAX_PAGES = 400       # 安全上限：全量 ~6000 岗 ÷ 20 ≈ 303 页，留余量
    PAGE_RETRY_BACKOFF = (3, 8, 20)  # 中途页失败/空页的退避秒数（测试置 0）

    def fetch(self, source_url: str) -> str:
        """翻全 Apple 公开搜索页，返回 JSON 岗位数组。

        旧实现只发 3 个写死的关键词（software / machine learning / data）各取首页，
        每轮固定只拿到 60 条，而库里已有 1041 条 active —— 岗位绝大多数永远刷不到
        （2026-07-28 实测 apple 源 3 天刷新率仅 11%，是全库最差之一）。
        现改为**空关键词枚举 + 逐页翻到底**：`?search=` 不带词即返回全部岗位，
        hydration 里 `totalRecords` 给出分母（实测限美国 4636 / 全球 6047），
        `?page=N` 逐页 20 条且页间零重叠 —— 三点都已 live 验证。
        关键词枚举天然带偏且互相重叠，改成全量枚举后覆盖面和可核对性都更好。
        """
        params = {"search": ""}
        if self.SEARCH_LOCATION:
            params["location"] = self.SEARCH_LOCATION

        def fetch_once(page: int) -> PageResult:
            url = f"{self.SEARCH_URL}?{urlencode({**params, 'page': page})}"
            resp = httpx.get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            search = self._extract_search_node(resp.text)
            rows = search.get("searchResults")
            total = search.get("totalRecords")
            return PageResult(
                items=rows if isinstance(rows, list) else [],
                total=total if isinstance(total, int) else None,
            )

        def fetch_page(page: int) -> PageResult:
            # 中途页「抛错 / 空页」都会让 paginate_all 就地收尾：2026-10-03 起 CI 上每轮只抓到
            # 20~280 / ~4,500 个岗（本机同时连翻 40 页全 200、每页 20 条），是瞬时失败把整轮截断。
            # 首页不重试（交上层记 failed）；之后的页退避重试，仍失败再按原语义截断 + 标没抓全。
            last_exc = None
            for wait in (0, *self.PAGE_RETRY_BACKOFF):
                if wait:
                    time.sleep(wait)
                try:
                    result = fetch_once(page)
                except Exception as e:  # noqa: BLE001 — 记下来，重试用尽再上抛
                    if page == 1:
                        raise
                    last_exc = e
                    print(f"    apple page {page} failed ({exc_brief(e)}); retry", flush=True)
                    continue
                if result.items or page == 1:
                    return result
                last_exc = None
                print(f"    apple page {page} came back empty; retry", flush=True)
            if last_exc is not None:
                raise last_exc
            return PageResult(items=[], total=None)

        rows, total, complete = paginate_all(
            fetch_page,
            page_size=self.PAGE_SIZE,
            first_page=1,
            max_pages=self.MAX_PAGES,
            delay_seconds=0.15,   # 礼貌爬取：几百页别把对方打毛
            label=f"apple:{self.name}",
        )
        if not rows:
            # 整站空结果不是「Apple 没岗」：它常年 4000+ 岗。2026-09-28 14:18 / 09-29 07:02
            # 两轮各 2 秒收尾、totalRecords=0、记 success + coverage_complete，重档当晚等于没抓
            # （次日只有 403/4883 个 active 岗 30h 内被刷新）。抛错让它记 failed、别标抓全。
            raise RuntimeError(
                f"apple search returned no rows (totalRecords={total!r}); "
                "treating as fetch failure, not an empty board"
            )
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps(rows)

    def parse(self, html: str) -> List[RawJob]:
        """Parse either fetch()'s JSON array or a raw public search page."""
        try:
            rows = json.loads(html)
        except json.JSONDecodeError:
            rows = self._extract_hydration_rows(html)

        jobs = []
        for row in rows:
            title = row.get("postingTitle", "")
            slug = row.get("transformedPostingTitle") or self._slugify(title)
            team_code = (
                f"?team={row['team']['teamCode']}"
                if row.get("team", {}).get("teamCode")
                else ""
            )
            job_id = row.get("id") or row.get("reqId")
            if not job_id or not title:
                continue
            jd_url = (
                f"https://jobs.apple.com/en-us/details/{job_id}/{slug}{team_code}"
            )

            location = None
            if row.get("locations"):
                location = ", ".join(
                    loc.get("name", "") for loc in row["locations"] if loc.get("name")
                )

            summary = row.get("jobSummary", "")

            jobs.append(
                RawJob(
                    company="Apple",
                    title=title,
                    location=location,
                    job_type="社招" if row.get("type") == "REQ" else None,
                    summary=summary[:250] if summary else None,
                    jd_url=jd_url,
                    apply_url=jd_url,
                    salary_text=None,
                    posted_at=row.get("postDateInGMT") or row.get("postingDate"),
                    country_code=_declared_country(row.get("locations")),  # 只在地点说不清时生效
                )
            )
        if self.CHINA_ONLY:
            jobs = [
                j for j in jobs
                if normalizer.location_in_source_regions(j.location, getattr(self, "regions", None))
            ]
        return jobs

    @staticmethod
    def _extract_search_node(html: str) -> dict:
        """抽 hydration 里的 search 节点（含 searchResults 与 totalRecords）。抽不到返回 {}。"""
        match = re.search(
            r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("([\s\S]*?)"\);</script>',
            html or "",
        )
        if not match:
            return {}

        try:
            hydration_text = json.loads(f'"{match.group(1)}"')
            hydration = json.loads(hydration_text)
        except json.JSONDecodeError:
            return {}

        node = (hydration.get("loaderData") or {}).get("search")
        return node if isinstance(node, dict) else {}

    @classmethod
    def _extract_hydration_rows(cls, html: str) -> List[dict]:
        """parse() 直接吃原始搜索页 HTML 时的兜底取行（fetch 走 _extract_search_node）。"""
        rows = cls._extract_search_node(html).get("searchResults")
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        return slug or "job"


class AppleChinaAdapter(AppleAdapter):
    """Apple 在华岗位：不固定 location（全球混合搜索）→ parse 后只保留在华/remote 岗。

    Apple 的 location code 不公开稳定，因此不猜 code；改为按通用关键词全局搜索，再用
    keep_for_china_radar 裁到在华/不绑定海外的 remote 岗。jd_url 仍是 Apple 官方 details 页。
    """

    name = "apple_cn"
    SEARCH_LOCATION = ""     # 不限地点
    CHINA_ONLY = True        # 只保留在华/remote
