"""华润集团招聘平台（runjob.crc.com.cn）适配器 —— 零登录、零浏览器、零签名。

接它的缘由：华润三九官网 999.com.cn 的「招聘」早已改指华润集团自建的这个平台，而我们盯着的
是它在第三方 ATS 上的旧租户（只剩 1 个岗）。结构性审计连续 7 天报「success + 0 岗」，
两道预检全放行——**没有任何信号会提示「我们盯的入口已经被公司边缘化了」**（2026-09-20 立项）。

## 接口形态（2026-09-20 live 逐条核实）
网关 `POST https://ssdp.crc.com.cn/ssdp/sys/rf/?ssdp=<base64>`：
  · `ssdp` 解码后是 `Api_Version=1.0&Api_ID=…&App_Sub_ID=…&App_Token=…&Sys_ID=…&Partner_ID=…
    &Sign=NO_SIGN&Time_Stamp=<北京时间>&User_Token=`。
    `Sign=NO_SIGN` + `User_Token` 为空 = **匿名可调**，不需要登录也不需要签名。
    App_Token 是写死在公开 JS 包 `js/app.*.js` 里的客户端标识（不是谁的凭证）。
  · body `{"base64String": base64(json({"biz":{"method":…,"param":…}}))}`
  · 响应 `{"RESPONSE":{"RETURN_CODE":"MS000A000","RETURN_DATA": base64(json)}}`

## 🚩 三个会让整源静默变 0 的坑（每个都实测过，别"简化"掉）
1. **`Time_Stamp` 必须是北京时间、且误差在几分钟内**，否则网关返 **HTTP 200 + 完全空的 body**
   （不是错误码、不是空 data，是零字节）。实测：北京时间当下 ✅26001 字节；同一时刻的
   **UTC** ❌0 字节；北京时间 -5 分钟 ✅；-30 分钟 ❌；-2 小时 ❌。
   ⚠️ GitHub runner 跑在 UTC，`datetime.now()` 直接就是错的 —— 这正是「绿灯零产出」的完美配方，
   所以本文件显式用 `ZoneInfo("Asia/Shanghai")`，**改它之前先想清楚 runner 的时区**。
2. **四个自定义请求头缺一不可**：`homepageconfigid`（= 该品牌招聘站 id）/ `languageindex: 0`
   / `rmapplyid: ""` / `authorization: ""`。少带同样是 200 + 空 body（同华为新网关那一类）。
3. **逐岗详情用 `blockRowId`，不是 `id`** —— 两者只差 1（如 …849 与 …850），
   用 `id` 打开的页面渲染成「**职位已下架**」。用错字段 = 全源死链，而且会被巡检判成撤岗后删库。

## 三个渠道会重叠，别把「各渠道自报总数之和」当分母
`recruitTypeCode`：A01 社会招聘 / A02 校园招聘 / A04 实习生招聘。
2026-09-20 华润三九实测：127 + 56 + 25 = 208 条，按 `blockRowId` 去重后只有 **186 条**
（与该品牌卡自报的「186 个热招职位」对得上）。所以抓全率**逐渠道判**：每个渠道都要
「抓到它自己自报的 total」才算 `fetch_complete`（同 huawei / xiaohongshu 的既有写法）。

## 列表即全文
列表行直接带 `rmJobDuty`（岗位职责）+ `rmJobRqmt`（职位要求），无需逐岗富化：
实测 208 条里 197 条正文 ≥60 字，直接过「有效在招」的正文门。

## 归属
每条岗位用平台**自报的法人名** `companyDescr`（华润三九医药股份有限公司 / 深圳华润三九医药贸易
有限公司 / 昆药集团股份有限公司 …），不统一贴成 sources.company。理由同「hotjob 只认租户自报
的 companyName」：平台自己声明的归属才是事实，把昆药的岗贴成「华润三九」是张冠李戴。

## 加别的华润品牌 = 只加一行 source，不用改代码
品牌清单（23 个，各带自己的招聘站 id）来自 `searchEmployerBrandList`；
source_url 写成 `https://runjob.crc.com.cn/#/homepage?id=<该品牌站 id>` 即可。
"""
import base64
import json
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

from .base import BaseAdapter, RawJob

SHANGHAI = ZoneInfo("Asia/Shanghai")


class CrcAdapter(BaseAdapter):
    name = "crc"
    company_name = ""          # 空 = 交给 sources.company 兜底；正常路径用每行自报的 companyDescr
    official_hosts = ("runjob.crc.com.cn", "crc.com.cn")

    GATEWAY = "https://ssdp.crc.com.cn/ssdp/sys/rf/"
    API_ID = "crinfo.hrms.rm.websiteView"
    # 公开 JS 包里的客户端标识（`js/app.*.js` 内硬编码），不是任何人的凭证
    APP_TOKEN = "60fe2d19e5ad491f8a02508da3efe532"
    APP_SUB_ID = "0006000908YA"
    SYS_ID = "00060009"
    PARTNER_ID = "00060000"
    DETAIL_URL = ("https://runjob.crc.com.cn/#/RecruitDetail"
                  "?id={job_id}&websiteId={site_id}&typeId={type_id}&internalRecommendFlag=0")
    # (recruitTypeCode, 渠道名)；渠道之间**会重叠**，去重后才是真实条数
    CHANNELS = (("A01", "社会招聘"), ("A02", "校园招聘"), ("A04", "实习生招聘"))
    PAGE_SIZE = 50
    MAX_PAGES = 40

    reported_total = None
    fetch_complete = False

    @staticmethod
    def _site_id(source_url: str) -> str:
        """从 `…/#/homepage?id=2092202183442501634` 里取该品牌招聘站 id。"""
        fragment = urlparse(source_url or "").fragment
        if "?" not in fragment:
            return ""
        query = parse_qs(fragment.split("?", 1)[1])
        for key in ("id", "websiteId", "positionSearchId"):
            value = (query.get(key) or [""])[0].strip()
            if value:
                return value
        return ""

    def _ssdp(self) -> str:
        """网关鉴权串。Time_Stamp 必须是**北京时间当下**，见文件头坑 1。"""
        now = datetime.now(SHANGHAI)
        stamp = now.strftime("%Y-%m-%d %H:%M:%S:") + f"{now.microsecond // 1000:03d}"
        raw = (f"Api_Version=1.0&Api_ID={self.API_ID}&App_Sub_ID={self.APP_SUB_ID}"
               f"&App_Token={self.APP_TOKEN}&Sys_ID={self.SYS_ID}&Partner_ID={self.PARTNER_ID}"
               f"&Sign=NO_SIGN&Time_Stamp={stamp}&User_Token=")
        return base64.b64encode(raw.encode()).decode()

    def _headers(self, site_id: str) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://runjob.crc.com.cn/",
            # 下面四个缺一不可，见文件头坑 2
            "homepageconfigid": site_id,
            "languageindex": "0",
            "rmapplyid": "",
            "authorization": "",
        }

    def _call(self, client: httpx.Client, site_id: str, method: str, param: dict) -> dict:
        payload = {"biz": {"method": method, "param": param}}
        body = json.dumps(
            {"base64String": base64.b64encode(
                json.dumps(payload, ensure_ascii=False).encode()).decode()},
            ensure_ascii=False)
        response = client.post(self.GATEWAY, params={"ssdp": self._ssdp()},
                               content=body.encode("utf-8"),
                               headers=self._headers(site_id))
        response.raise_for_status()
        if not response.content:
            # 200 + 零字节 = 时间戳时区/漂移，或少带了自定义头。**必须抛**：
            # 安静返 0 条正是「报成功却零产出」的来源，这条源当初就是这么坏掉没人发现的。
            raise RuntimeError(
                "crc: gateway returned HTTP 200 with an empty body "
                "(Time_Stamp must be current Asia/Shanghai time; custom headers are required)")
        envelope = (response.json() or {}).get("RESPONSE") or {}
        encoded = envelope.get("RETURN_DATA")
        if not encoded:
            raise RuntimeError(
                f"crc: gateway returned no RETURN_DATA (code={envelope.get('RETURN_CODE')!r} "
                f"desc={envelope.get('RETURN_DESC')!r})")
        return json.loads(base64.b64decode(encoded).decode("utf-8"))

    def _search_param(self, site_id: str, recruit_type: str, page_no: int) -> dict:
        return {
            "recruitTypeCode": recruit_type, "keyword": "", "positionSearchId": site_id,
            "pubPositionName": "", "deptId": "", "company": "", "positionType": "",
            "location": "", "industrySector": "", "workYearsRqmt": "", "educationalRqmt": "",
            "ageRqmt": "", "crcWorkYears": "", "rmTypeCode": "", "rmBusiness": "",
            "filtrateItemId": "", "classifyItemId": "",
            "pageNum": page_no, "pageSize": self.PAGE_SIZE,
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        site_id = self._site_id(source_url)
        if not site_id:
            raise RuntimeError(f"crc: no brand site id in source_url {source_url!r}")
        rows: List[dict] = []
        seen: set = set()
        channel_totals: List[int] = []
        channels_drained: List[bool] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            for recruit_type, channel_name in self.CHANNELS:
                total: Optional[int] = None
                got = 0
                for page_no in range(1, self.MAX_PAGES + 1):
                    data = self._call(client, site_id, "searchPublishPosition",
                                      self._search_param(site_id, recruit_type, page_no))
                    if total is None:
                        try:
                            total = int(data.get("total"))
                        except (TypeError, ValueError):
                            total = None
                    page_rows = data.get("records") or []
                    if not page_rows:
                        break
                    fresh = 0
                    for row in page_rows:
                        key = str(row.get("blockRowId") or "").strip()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        row["_channel"] = channel_name
                        row["_site_id"] = site_id
                        rows.append(row)
                        fresh += 1
                    got += len(page_rows)
                    if total is not None and got >= total:
                        break
                    # 末页判据看「这一页有没有带来新东西」，不看页长——短页可能只是限流抖动。
                    # ⚠️ 这里 fresh 会因**跨渠道重叠**而为 0（A02 的岗可能已在 A01 出现过），
                    # 所以只有在本渠道一条新行都没有、且已知 total 还没抓够时才停，避免提前收工。
                    if not fresh and (total is None or got >= total):
                        break
                    if not page_rows:
                        break
                if total is not None:
                    channel_totals.append(total)
                    channels_drained.append(got >= total)
                else:
                    channels_drained.append(False)   # 连总数都没拿到 → 本渠道不算抓全
        if not rows:
            raise RuntimeError(f"crc: brand site {site_id} returned no positions in any channel")
        # 分母只在**每个渠道都自报了 total** 时才给；且必须逐渠道都抓干净才算 complete。
        # ⚠️ 这个和是「渠道总数之和」，**大于**去重后的真实条数（渠道会重叠），
        #    它只用来回答「每个渠道都翻完了吗」，不要拿它当「库里应该有多少条」。
        if len(channel_totals) == len(self.CHANNELS):
            self.reported_total = sum(channel_totals)
        self.fetch_complete = bool(channels_drained) and all(channels_drained)
        return json.dumps({"records": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("records") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            job_id = str(row.get("blockRowId") or "").strip()   # 不是 id，见文件头坑 3
            title = str(row.get("pubPositionName") or "").strip()
            if not job_id or not title:
                continue
            site_id = str(row.get("_site_id") or "").strip()
            type_id = str(row.get("typeId") or "").strip() or "A01"
            duty = str(row.get("rmJobDuty") or "").strip()
            requirement = str(row.get("rmJobRqmt") or "").strip()
            summary = "\n".join(part for part in (
                ("岗位职责\n" + duty) if duty else "",
                ("职位要求\n" + requirement) if requirement else "",
            ) if part).strip() or None
            jobs.append(RawJob(
                # 平台自报的法人名；取不到才回落 sources.company（见文件头「归属」）
                company=str(row.get("companyDescr") or "").strip() or self.company_name,
                title=title,
                location=str(row.get("locationDescr") or "").strip() or None,
                # 喂给库里的招聘类型分类器 → 用渠道名（社会招聘/校园招聘/实习生招聘），
                # 它是平台自己声明的招聘类别，比任何猜测都准。
                job_type=str(row.get("typeIdDescr") or row.get("_channel") or "").strip() or None,
                summary=summary,
                jd_url=self.DETAIL_URL.format(job_id=job_id, site_id=site_id, type_id=type_id),
                apply_url=self.DETAIL_URL.format(job_id=job_id, site_id=site_id, type_id=type_id),
                posted_at=str(row.get("publishDate") or "").strip() or None,
                experience=str(row.get("workYearsRqmtDescr") or "").strip() or None,
                education=str(row.get("educationalRqmtDescr") or "").strip() or None,
            ))
        return jobs
