"""老版 WinTalent（wt）招聘站通用适配器（直连公开 position/list JSON 接口，零浏览器）。

矿脉：一批知名大企业仍用 hotjob.cn 的**老版 wt**（区别于已攻克的新版 wecruit）：
伊利(yili) / 中信证券(SEC) / 中广核(CGN) / 中国电信(CT) / 中化(Sinochem) / 现代汽车(HMGC) 等。
入口形如 `{host}.hotjob.cn/wt/{BRAND}/web/index`（302→`CompXXXPageindex` 落地页）。

可行性已 live 验证（两道闸门均过）：
  闸门①（列表 XHR）：wt 列表页 JS 公开 GET `{origin}/wt/{BRAND}/web/json/position/list`
    （query: brandCode=1 + recruitType + page），**无需 operational 签名**即返回明文 JSON：
    {"postList":[{postId, postName, workPlace, postType, workingTreatment, endDate,
     publishDate(Time), workYears, education, serviceCondition, workContent, recruitNum, orgName}],
     "rowCount":N, "pageCount":M, "rowSize":10}。服务端 rowSize 硬封顶 10/页，靠 page 翻页收齐。
  闸门②（★决定性 — 逐岗 jd_url 稳定）：详情走移动版稳定页
    `{origin}/wt/{BRAND}/mobweb/position/detail?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={postId}`，
    **去掉 operational 签名、仅 postId + recruitType** 即渲染出**该岗位本身**（live 实测：
    yili 514713→"总部人力资源部HR数据分析专业经理"、522468→"酸奶苏皖…人力资源专员"，互不串页；
    HMGC 172801→"中英翻译"；无效 postId 仅回 ~1.8KB 关闭页不入坏链）。→ 过质量门，可入库。

recruitType 为 wt 平台常量（非每公司配置）：校招/campus=1 / 社招/social=2 / 实习/intern=12 /
**13=「海外」板块（页面模板 `v_recruitType=="13"` 跳 /web/index/overseas，但租户各自挪用）**，
与详情页 recruitType 一致；逐 recruitType 抓取并合并，三桶归类交后置过滤 + 前端 recruitmentCategory。
rt=13 于 2026-09-18 live 扫全部 41 个 wt 租户补上：11 家共约 200 岗此前一条都没进库
（五矿 81「安全管培生（海外）-2027应届生」是校招、TCL 40「EMC工程师-27届」是校招、中伟 CNGR 38
「汽修工」是社招、华友 11 社招、用友 9 社招、中联重科 8、润阳 8、宇通 3 实习、海澜 2「艺术团招聘」、
兴业证券 1「博士后招聘」、越秀 1）。闸门②对 rt=13 同样成立：8 家 16 岗
`…/mobweb/position/detail?…&recruitType=13&postIdsAry={pid}` 全部渲染出岗位本身，假 postId 只回 ~1.8KB
提示页；且五矿 / 用友 / 宇通 / 海澜的这批岗用 recruitType=2 打详情页只回「提示」页 —— jd_url 必须带 13。
company 由 sources.company 兜底（BRAND 仅用于路由，不当公司名，杜绝张冠李戴）。

直连 httpx（无头浏览器非必需），返回 PlaywrightAdapter.parse 可消费的 _intercepted 信封。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import (DEFAULT_LIST_CAP, PageResult, RawJob, paginate_all, resolve_list_cap,
                   resolve_page_cap)
from .playwright_base import PlaywrightAdapter


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


class WtAdapter(PlaywrightAdapter):
    """老版 WinTalent（wt）招聘站。source_url 填某公司 wt 入口（如
    https://yili.hotjob.cn/wt/yili/web/index 或其 …/CompyiliPageindex_social）。"""

    name = "wt"
    company_name = ""  # 由 sources.company 兜底，绝不用 BRAND 当公司名

    _LIST_PATH = "/wt/{brand}/web/json/position/list"
    # 稳定详情页（移动版，postId-only，无 operational 签名）——闸门②已 live 验证可逐岗直达。
    _DETAIL_TPL = ("{origin}/wt/{brand}/mobweb/position/detail"
                   "?brandCode=1&safe=Y&recruitType={rt}&postIdsAry={pid}")
    # recruitType 平台常量：校招=1 / 社招=2 / 实习=12 / 13=「海外」板块（与详情页 recruitType 同口径）。
    # ⚠️ 逐渠道判 reported_total / fetch_complete 的两处都用 len(self._RECRUIT_TYPES)，加渠道只改这里。
    _RECRUIT_TYPES = (2, 1, 12, 13)
    # 每 recruitType 的页数上限，只作防死循环兜底（靠 rowCount/短页自然收尾）。
    # 旧的硬编码 200 页 × 10 条 = 2000 岗/类：长城汽车社招一超过 2000 就被悄悄截断，
    # 2026-09-04 实测自报 3,421 只抓到 2,617、status 仍是 success。改按 CRAWL_MAX_JOBS 换算。
    _PAGE_CAP = None
    # 单租户总安全预算（10/页 → 最坏约 800 次请求；env CRAWL_MAX_JOBS 可整体调档）。
    # 长城汽车自报 3420 岗，卡在旧的 3000 就差最后 803 个（2026-09-04 crawl_runs 实测），
    # 这种「差一点点」的截断最不值得留。
    _MAX_JOBS = DEFAULT_LIST_CAP

    def _bind_source(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        # 路径形如 /wt/{BRAND}/web/index[/CompXXXPageindex_social]；BRAND = 第 2 段。
        if len(parts) < 2 or parts[0].lower() != "wt":
            raise RuntimeError(f"wt: bad source_url (expect /wt/{{BRAND}}/...): {source_url}")
        self._brand = parts[1]
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        self.official_hosts = (parsed.netloc,)
        # 列表页（用于 Referer，提高接口可达性）
        self._referer = f"{self._origin}/wt/{self._brand}/web/index"
        return self._brand

    def fetch(self, source_url: str) -> str:
        """直连 position/list 接口，逐 recruitType × 翻页拉全量，返回 _intercepted 信封。"""
        self.reported_total = None
        self.fetch_complete = False
        self._bind_source(source_url)
        api = f"{self._origin}{self._LIST_PATH.format(brand=self._brand)}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": self._referer,
            "Origin": self._origin,
        }
        collected: List[dict] = []
        totals: List[int] = []
        type_complete: List[bool] = []
        # postId → 该岗出现过的全部 recruitType（首见渠道在前）。同一 postId 在多个渠道里各出现
        # 一次是常态（2026-09-18 live：TCL 40 个「-27届」岗四个渠道全挂、中伟 38 个 rt=13 岗里
        # 34 个同时在社招）；jd_url 带 recruitType，按 (渠道, postId) 去重会让同一岗存出多行
        # （库里 GWM 3,440 行只有 3,188 个 postId）。所以按 postId 跨渠道去重：**首见渠道**决定
        # jd_url（rt=13 独有的岗只有 recruitType=13 能渲染详情页，首见即它），其余渠道只记进
        # `_wtRecruitTypes` 供 _map 取招聘类型标签（挂在校招板块的岗，不论首见于哪个渠道都标校招）。
        seen_rts: dict = {}
        budget_exhausted = False
        cap = resolve_list_cap(self._MAX_JOBS)
        page_cap = self._PAGE_CAP or resolve_page_cap(10)   # 10 条/页，见 fetch_page
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for rt in self._RECRUIT_TYPES:
                remaining_jobs = cap - len(seen_rts)
                if remaining_jobs <= 0:
                    budget_exhausted = True
                    break
                max_pages = min(page_cap, max(1, (remaining_jobs + 9) // 10))

                def fetch_page(page: int) -> PageResult:
                    resp = client.get(api, params={
                        "brandCode": 1, "recruitType": rt, "page": page})
                    resp.raise_for_status()
                    payload = resp.json()
                    if not isinstance(payload, dict):
                        raise ValueError("wt: position/list returned non-object payload")
                    rows = payload.get("postList") or []
                    kept = []
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        pid = _first(r, ("postId", "id"))
                        if pid and pid in seen_rts:
                            if rt not in seen_rts[pid]:
                                seen_rts[pid].append(rt)
                            continue
                        # 标记本批的 recruitType，供 _map 拼稳定详情链（详情页要 recruitType）。
                        r["_wtRecruitType"] = rt
                        if pid:
                            seen_rts[pid] = r["_wtRecruitTypes"] = [rt]
                        kept.append(r)
                    if kept:
                        collected.append(dict(payload, postList=kept))
                    # ⚠️ 末页判据要看整页（含跨渠道重复行），否则 rt=13 首页全是别的渠道已见过的岗时
                    # 会被当成空页提前收尾，后面几页真正独有的岗就漏了。
                    return PageResult(items=rows, total=_int_or_none(payload.get("rowCount")))

                _, total, complete = paginate_all(
                    fetch_page,
                    page_size=10,
                    first_page=1,
                    max_pages=max_pages,
                    logger=None,
                    label=f"wt:{self._brand}:{rt}",
                )
                if total is not None:
                    totals.append(total)
                type_complete.append(complete)
                if len(seen_rts) >= cap:
                    budget_exhausted = True
                    break
                if not complete and max_pages < page_cap:
                    budget_exhausted = True
                    break
        if not collected:
            # 一条都没拿到 → 多半非 wt 老版 / 接口改版 / 该域被拦；交给 run.py 记 partial（不伪装成功）。
            raise RuntimeError(
                f"wt: empty position/list (brand={self._brand} host={self._host})")
        # 分母去掉跨渠道重复：各渠道 rowCount 之和把同一 postId 数了多次（五矿 4 渠道之和 1,017、
        # 去重后 925），不减就是「渠道总数之和当分母」那块碑说的假缺口——抓全了却永远显示 91%。
        # 减的是本次**真看到**的重复（每个 postId 多出现一次减一），不是估算。
        overlap = sum(len(rts) - 1 for rts in seen_rts.values())
        self.reported_total = (
            sum(totals) - overlap if len(totals) == len(self._RECRUIT_TYPES) else len(seen_rts)
        )
        self.fetch_complete = (
            len(type_complete) == len(self._RECRUIT_TYPES)
            and all(type_complete)
            and not budget_exhausted
        )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    # PlaywrightAdapter._extract_posts 的 posts_keys 含 'postList'？没有——这里覆盖 parse 用的提取，
    # 直接在 _map 前由 _extract_posts 命中。posts_keys 未含 postList，故显式加上。
    posts_keys = ("postList",) + PlaywrightAdapter.posts_keys

    # recruitType → sourceDeclaredCategory 能识别的显式招聘类型词（lib/china-keyword-expansion.js
    # 的 sourceDeclaredCategory 只认这几类关键词，不认「市场营销类」这种职能类别）。
    # ⚠️ wt 列表接口只按功能类别给 postType（如「市场营销类」「职能管理类」），完全不含招聘类型词汇——
    # 而我们请求时用的 recruitType（1=校招/2=社招/12=实习）才是权威的招聘类型信号。不把它带下去，
    # 分类器只能看 job_type 里的职能类别（永远判不出校招/实习），于是 wt 源的校招/实习岗全部被
    # 兜底成社招（2026-09-17 实锤：华发股份 9 个校招岗、李宁 1 个校招岗全部入库成「社招」）。
    #
    # 🚫 **刻意只标 1/12，不标 2（社招）**，与 china-keyword-expansion 层4 那条
    # 「不对 postType=society 对称判社招」同一个理由：社招本来就是层7 的默认态，标了不增加信息，
    # 却会让层3（declared）抢在层4（url 门户）/层5（标题强校招标记）**之前**拍板。
    # 2026-09-17 香港库全量对拍（只拉 group by 计数）：wt 源 jd_url 带 recruitType=2 的在招岗里，
    # 现在有 **170 个判成校招、91 个判成实习**（公司把校招岗挂在社招板块，靠标题「XX 届 / 应届」
    # 被层5 捞回来）——标上「社会招聘」= 这 170 个当场被压回社招。
    # 正向收益（rt=1/12 标上后能救回的）：rt=1 现有 3,827 个判成社招 + 77 个判成实习，
    # rt=12 现有 285 个判成社招 + 46 个判成校招。只标 1/12 是**单向纯增量**。
    #
    # 🚫 **rt=13 也不贴任何标签**（2026-09-18）：名义是「海外」板块，实际租户各自挪用——五矿 / TCL
    # 放的是「-2027应届生」「-27届」校招，宇通放实习，中伟 / 华友 / 用友 / 中联重科放社招，海澜放
    # 艺术团、兴业证券放博士后。渠道本身不携带招聘类型信息，硬标任何一种都会错一半；交给
    # recruitmentCategory 按标题「27届 / 应届 / 实习生」自己判（层5 / 层2b）。
    _RT_CATEGORY_LABEL = {1: "校园招聘", 12: "实习"}

    # ⛔ 「按院校设的投递入口」不是岗位，一律不入库（2026-09-18 立）。
    # 中广核把校园招聘做成「每所目标院校一条 post」：postName 就是院校名（「北京建筑大学」
    # 「海外院校」「其他院校」），workContent / serviceCondition 都只有一个句号。它们照样有
    # 独立 postId 和可打开的详情页，所以质量门放行 —— 进库后 recruitType=1 又让它们全判成校招，
    # 用户在校招专区看到 957 张标题是大学名、点开没有任何 JD 的卡片。
    # 判据是**两条同时成立**，不是公司名（别写成 if company == 中广核，下一家照样中招）：
    #   ① 标题整体就是一个院校 / 研究机构名（不是「XX-研究院」这种带职位的写法）；
    #   ② 正文去掉句号与「【任职要求】」后为空。
    # 2026-09-18 香港库全 wt 语料（20,600 个在招岗）逐行对拍这两条的**交集**：
    #   命中 957 行 = 中广核全部 957 行，无第四家公司；
    #   只中①不中②：4 行（特变电工「FPGA软件工程师-研究院」等真岗，正文完整）→ 保住；
    #   只中②不中①：3 行（三棵树「行政接待类实习生」/ 特变电工「实习生（客房部）」等薄卡）→ 保住
    #   （薄卡按 CLAUDE.md §4 该留在库里、只是不计入有效在招，不该被这道门顺手删掉）。
    _INSTITUTION_TITLE = re.compile(
        r"^[^,，/、|]{2,20}(?:大学|学院|院校|研究生院|研究院|研究所|学校)(?:（[^）]*）|\([^)]*\))?$")
    _EMPTY_BODY = re.compile(r"[。\s【】任职要求]")

    # 类属性起步、`+=` 时自动变成实例属性：不覆写 __init__，免得跟基类的构造签名纠缠。
    _skipped_school_entries = 0

    def _is_school_entry(self, title: str, summary: Optional[str]) -> bool:
        if not self._INSTITUTION_TITLE.match(title.strip()):
            return False
        return not self._EMPTY_BODY.sub("", summary or "")

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        post_id = _first(post, ("postId", "id"))
        title = _first(post, ("postName", "title", "name"))
        if not (post_id and title):
            return None
        rt = post.get("_wtRecruitType") or 2
        rts = post.get("_wtRecruitTypes") or [rt]
        jd_url = self._DETAIL_TPL.format(
            origin=self._origin, brand=self._brand, rt=rt, pid=post_id)

        desc = _first(post, ("workContent", "description"))
        req = _first(post, ("serviceCondition", "requirement"))
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        if self._is_school_entry(title, summary):
            # 不吞声：累计并打一行，让「这源少了 957 条」在 CI 日志里有据可查。
            self._skipped_school_entries += 1
            if self._skipped_school_entries == 1:
                print(f"    [wt:{self._brand}] 跳过「按院校设的投递入口」（标题=院校名且无正文），"
                      f"首条：{title}", flush=True)
            return None
        func_type = _first(post, ("postType", "postTypeName"))
        # 招聘类型标签看该岗出现过的**全部**渠道：首见于社招、同时也挂在校招板块的岗照样标校招
        # （去重前它本来就以 rt=1 那一行的身份带着「校园招聘」入库过）。
        rt_label = next((self._RT_CATEGORY_LABEL[x] for x in (1, 12) if x in rts), None)
        # 职能类别 + 招聘类型词并存：sourceDeclaredCategory 只是子串匹配，两段拼一起互不干扰；
        # 职能类别继续喂给 classifyJobFunction，招聘类型词喂给 recruitmentCategory（「校园招聘」走层3；
        # 「实习」走层2b —— 它是租户级的频道声明，排在层2 经验门**之后**：2026-09-18 live 实锤中伟新材料 /
        # 浙江华友钴业把 rt=12（门户上就叫「实习生招聘」）当蓝领社招频道用，电工 3 年 / 钳工 3-5 年 /
        # 仓管员「仓储经验 3 年以上」全被标成实习。标签照贴，让分类器拿岗位自己写的年限压过它）。
        job_type = " ".join(p for p in (func_type, rt_label) if p) or None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=_first(post, ("workPlace", "workCity", "location")) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=(normalizer.pick_publish_date(post)
                       or normalizer.coerce_iso_date(post.get("publishDateTime"))
                       or normalizer.coerce_iso_date(post.get("publishDate"))),
            education=_first(post, ("education", "educationName")) or None,
            experience=_first(post, ("workYears", "workYearName", "workExperience")) or None,
            deadline=normalizer.coerce_iso_date(post.get("endDate")),
        )
