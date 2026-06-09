"""
通用 Workday 适配器（公开 CXS API，无需鉴权）。

source_url = https://{host}/wday/cxs/{tenant}/{site}/jobs   （host 形如 {tenant}.wd{N}.myworkdayjobs.com）
大量在华跨国企业（外企100强主力：NVIDIA / 制造 / 金融 / 消费…）用 Workday，greenhouse/lever 抓不到。
一套适配覆盖任意 Workday 租户 —— 新增公司只需加一行 sources（source_url 填 CXS jobs 端点）。

服务「在华外企」：用 Workday 的 location facet **服务端**过滤到大中华区（China/Hong Kong/Macau），
只抓在华岗位，避免全球岗位灌入（list 接口 locationsText 常是「N Locations」不可靠，故用 facet）。
jd_url = {host}/{site}{externalPath}（Workday 托管的稳定 per-job 页，已 live 验证渲染对应岗位）。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import BaseAdapter, RawJob

# 大中华区 facet 关键词（China / Mainland China / Greater China / Hong Kong / Macau…）
_GREATER_CHINA = ("china", "中国", "hong kong", "香港", "macau", "macao", "澳门")
# 台湾不属本雷达「在华」口径，排除
_TAIWAN = ("taiwan", "台湾", "台灣", "chinese taipei")


def _is_china_facet(desc: str) -> bool:
    """是否大中华区 facet 项：含 China/HK/Macau 关键词、排除台湾。
    允许城市级（'China, Beijing'）—— 不同租户把可选叶子放在国家级或城市级 param，按 param 分组后逐组试探。"""
    d = str(desc or "").strip().lower()
    if not d or any(t in d for t in _TAIWAN):
        return False
    return any(k in d for k in _GREATER_CHINA)


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    max_pages = 25  # 每页 20 → 单源最多约 500 在华岗（容纳 AstraZeneca 等大租户，避免静默截断；分页 <20 即停）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def _parse_endpoint(self, source_url: str):
        p = urlparse(source_url)
        self._host = f"{p.scheme}://{p.netloc}"
        # CXS detail 端点 = {host}/wday/cxs/{tenant}/{site}{externalPath}（= source_url 去掉尾部 /jobs）。
        self._cxs_base = re.sub(r"/jobs/?$", "", source_url)
        parts = [x for x in (p.path or "").split("/") if x]
        # 期望 ['wday','cxs',{tenant},{site},'jobs'] → site 是 cxs 后第 2 段
        try:
            i = parts.index("cxs")
            self._site = parts[i + 2]
        except (ValueError, IndexError):
            self._site = parts[-2] if len(parts) >= 2 else ""

    def fetch(self, source_url: str) -> str:
        self._parse_endpoint(source_url)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        # 1) 取 facets，按 param 分组收集大中华区候选 id
        r = httpx.post(source_url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                       headers=headers, timeout=self.timeout)
        r.raise_for_status()
        candidates = self._china_facet_candidates(r.json().get("facets", []))

        # 2) facet 路径：把**每个**大中华区 facet 组各自分页、并集去重。
        # 不靠 Workday 的 `total` 字段选「最佳单组」—— 实测该字段极不可靠（NVIDIA 报 total=180 实际可翻 600+），
        # 靠它选组/比较会误判。改为「所有 china facet 组并集」：每组都是合法在华过滤，OR 起来即全部在华岗，
        # 这些是**可信在华**岗（parse 不再过滤）。同 param 多 id 一次 OR 提交；不同 param 分别提交后并集。
        trusted: List[dict] = []
        seen = set()
        for param, ids in candidates.items():
            if not ids:
                continue
            for page in range(self.max_pages):
                body = {"appliedFacets": {param: ids}, "limit": 20, "offset": page * 20, "searchText": ""}
                rr = httpx.post(source_url, json=body, headers=headers, timeout=self.timeout)
                rr.raise_for_status()
                posts = rr.json().get("jobPostings", []) or []
                if not posts:
                    break
                for p in posts:
                    key = p.get("externalPath") or p.get("title")
                    if key and key not in seen:
                        seen.add(key)
                        trusted.append(p)
                if len(posts) < 20:
                    break

        # 3) searchText 文本补充：部分租户的在华地点埋在**嵌套/截断**的 location facet 里，facet 只露出
        # 部分叶子（如 GE HealthCare 的 locationMainGroup 只有 Hong Kong、漏掉上海 22 岗）。facet 取到的太少
        # （<25，或压根没 facet）就用 Workday searchText 按 'China'/'Hong Kong'/'Macau' 文本召回把漏的捞回；
        # 这些是**待过滤**岗（searchText 会带入母国/描述含 China 的非华岗），由 parse 按 is_china_location 严格过滤。
        # facet 已足够多（NVIDIA/BMS 数百岗）则跳过补充：补充只增不减、out ⊇ trusted，绝不回退召回。
        text_posts: List[dict] = []
        if len(trusted) < 25:
            for q in ("China", "Hong Kong", "Macau"):
                for page in range(self.max_pages):
                    body = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": q}
                    rr = httpx.post(source_url, json=body, headers=headers, timeout=self.timeout)
                    rr.raise_for_status()
                    posts = rr.json().get("jobPostings", []) or []
                    if not posts:
                        break
                    for p in posts:
                        key = p.get("externalPath") or p.get("title")
                        if key and key not in seen:
                            seen.add(key)
                            text_posts.append(p)
                    if len(posts) < 20:
                        break

        # 4) 逐岗 detail 抓 jobDescription —— list 接口不含描述，外企卡片 JD 因此全空。
        #    GET {host}{externalPath} → jobPostingInfo.jobDescription（HTML；run.py 的 clean_summary 去标签解实体，
        #    且 summary 有正文后 extract_job_type/experience/education 能从中推断）。只抓将保留的在华岗
        #    （trusted 全保留；text_posts 取在华的），单源封顶防夜间全量被拖垮；失败该岗无摘要、不影响入库。
        self._enrich_descriptions(trusted, headers, china_only=False)
        self._enrich_descriptions(text_posts, headers, china_only=True)

        return json.dumps({
            "_host": self._host, "_site": self._site,
            "trusted_posts": trusted, "text_posts": text_posts,
        }, ensure_ascii=False)

    _DETAIL_CAP = 300  # 单源逐岗 detail 抓取上限：覆盖绝大多数源；超大租户部分覆盖，避免拖垮夜间全量

    def _enrich_descriptions(self, posts: List[dict], headers: dict, china_only: bool):
        """对将保留的岗位逐个 GET detail 端点，把 jobDescription 挂到 post['_jd']（供 parse 取作 summary）。"""
        n = 0
        for p in posts:
            if n >= self._DETAIL_CAP:
                break
            if not isinstance(p, dict):
                continue
            ep = (p.get("externalPath") or "").strip()
            if not ep:
                continue
            if china_only:
                loc = self._loc_from_path(ep) or p.get("locationsText")
                if not normalizer.is_china_location(loc):
                    continue
            try:
                d = httpx.get(f"{self._cxs_base}{ep}", headers=headers, timeout=self.timeout)
                if d.status_code < 300:
                    desc = (d.json().get("jobPostingInfo", {}) or {}).get("jobDescription")
                    if desc:
                        p["_jd"] = desc
                    n += 1
            except Exception:
                continue

    @staticmethod
    def _china_facet_candidates(facets) -> dict:
        """深搜 facets，按 facetParameter 分组收集大中华区相关叶子 id（含 'China, City' 城市级）。
        返回 {param: [id...]}。**不跨 param 合并** —— 不同租户的可选叶子放在 locationHierarchy1 /
        locationCountry / locations 等不同 param，且 locationCountry 的国家聚合项常不可直接选（应用返回 0）。
        因此分组后由 _pick_best_facet 逐组试探、取命中最多的单组，自适应各租户 facet 结构。"""
        groups: dict = {}

        def walk(node):
            if isinstance(node, dict):
                param = node.get("facetParameter")
                for v in node.get("values", []) or []:
                    if param and v.get("id") and _is_china_facet(v.get("descriptor", "")):
                        ids = groups.setdefault(param, [])
                        if v["id"] not in ids:
                            ids.append(v["id"])
                for v in node.get("values", []) or []:
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        for f in facets:
            walk(f)
        return groups

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        host = data.get("_host", "")
        site = data.get("_site", "")

        out: List[RawJob] = []
        seen_urls = set()

        def emit(p, trusted):
            if not isinstance(p, dict):
                return
            title = (p.get("title") or "").strip()
            ep = (p.get("externalPath") or "").strip()
            if not title or not ep:
                return
            location = self._loc_from_path(ep) or (p.get("locationsText") or None)
            # trusted（facet 已服务端过滤）全部在华直接收；text_posts（searchText 文本召回）按 location 严格
            # 判定在华（大陆/港/澳）—— 外企 Workday 的 "Remote" 多指母国远程而非中国，故用 is_china_location，
            # 避免泄漏非华岗（如 "Remote - Delhi" / Haifa）。
            if not trusted and not normalizer.is_china_location(location):
                return
            jd_url = f"{host}/{site}{ep}"
            if jd_url in seen_urls:
                return
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,  # run.py 会用 extract_job_type(title, summary) 从正文推断
                summary=p.get("_jd"),  # detail 端点抓到的 jobDescription（HTML）；run.py clean_summary 去标签
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,  # postedOn 是相对文案（"Posted Yesterday"），不伪造日期
            ))

        # 向后兼容：旧形态 {"posts", "_china_filtered"}；新形态 {"trusted_posts","text_posts"}
        if "posts" in data:
            cf = data.get("_china_filtered")
            for p in data.get("posts", []):
                emit(p, trusted=bool(cf))
        else:
            for p in data.get("trusted_posts", []):
                emit(p, trusted=True)
            for p in data.get("text_posts", []):
                emit(p, trusted=False)
        return out

    @staticmethod
    def _loc_from_path(ep: str) -> Optional[str]:
        # externalPath: /job/China-Beijing/Title_JRxxxx → 第 2 段 "China-Beijing" → "China, Beijing"
        parts = [x for x in ep.split("/") if x]
        if len(parts) >= 2 and parts[0].lower() == "job":
            seg = parts[1].replace("-", ", ").strip()
            return _normalize_cn_country(seg) or None
        return None


def _normalize_cn_country(seg: str) -> str:
    """把 Workday externalPath 地点段里的 CHN/CN 国家缩写归一为 China。
    Workday 不同租户写法不一：'Xiamen, CHN' / 'XiamenCHN'（粘连）/ 'Sanshui, CN'。归一后地点展示更干净，
    且 facet=False 回退时 is_china_location 能正确识别为在华。仅匹配独立词或粘连城市尾的国家码，
    避免误伤含 'chn' 的词（如 München→munchen 实为 'chen' 不含 'chn'，且此处只动 CHN/CN 词边界）。"""
    if not seg:
        return seg
    # 粘连：XiamenCHN → Xiamen, China（城市小写尾 + 大写国家码 + 串尾）
    seg = re.sub(r"(?<=[a-z])(CHN|CN)$", r", China", seg)
    # 独立词：'Sanshui, CHN' / 'CN, Shanghai' → China
    seg = re.sub(r"(?i)\b(?:CHN|CN)\b", "China", seg)
    return seg.strip()
