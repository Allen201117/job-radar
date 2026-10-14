"""
中国本土 ATS / 企业官网招聘站通用浏览器适配器（Tier-2，SPA 拦截）。

覆盖三大类「各行各业公司」来源，一套代码 + 一行 sources 记录即可扩源：
  - moka     : Moka（{tenant}.mokahr.com / app.mokahr.com）—— 大量消费/互联网/制造公司在用
  - beisen   : 北森（*.zhiye.com / *.italent.cn / careers.*）—— 大型国企/集团在用
  - company_spa : 通用企业官网 SPA —— 仅放行站点自有接口里**带真实 per-job URL** 的岗位

合规与质量（遵守 CLAUDE.md 数据质量优先级）：
  - 只加载官方公开招聘页，拦截站点**自己**发起的岗位列表接口响应；不破签名、不调私有接口、低频。
  - jd_url 优先用接口返回的**真实 per-job 链接**；仅 moka/beisen 这类已知 URL 形态才用模板兜底拼。
  - company_spa 不猜 URL：post 里没有可用 per-job 链接的行直接丢，由 normalizer 质量门再兜一层。

host / tenant 从每个 source 的 source_url 动态解析，因此**同一 adapter 覆盖任意租户公司**。
playwright 仅在 fetch() 内惰性导入。
"""
import html as _html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

import normalizer
from geo import TITLE_CITY_PROVINCE_NAMES, is_place_name
from .base import (DEFAULT_LIST_CAP, PageResult, RawJob, RepetitionBrake, exc_brief,
                   paginate_all, redact_urls, resolve_detail_cap, resolve_list_cap, resolve_page_cap)
from .playwright_base import PlaywrightAdapter

_log = logging.getLogger(__name__)

# 翻页时单页失败的重试次数与退避基数（见 _post_page_with_retry）。3 次 × 0.6s 退避足够穿过
# 北森的秒级限流窗口，又不会让一个真坏掉的源把整轮抓取拖住。
_PAGE_RETRIES = 3
_PAGE_BACKOFF_SECONDS = 0.6


def _first_str(post: dict, keys) -> str:
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


def _city_of(post: dict) -> str:
    for k in ("cityName", "city", "workCity", "location", "workPlace", "address",
              "city_name", "work_city", "locationName", "LocNames", "LocName", "Location"):
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("cityName") or v.get("text")
            if isinstance(name, str) and name.strip():
                return name.strip()
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                name = first.get("name") or first.get("cityName")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


class ChinaSpaAdapter(PlaywrightAdapter):
    """中国本土 SPA 招聘站通用基类：从 source_url 动态解析 host，启发式抽取岗位字段。"""

    # 子类可设详情链接模板（含 {host} {id}）；为空表示「只接受接口里的真实 URL，不拼模板」。
    detail_template: str = ""
    company_name = ""  # 由 sources.company 兜底填充

    def fetch(self, source_url: str) -> str:
        # 记录本次源的 origin / host / 门户前缀，供 _map 拼接相对链接与详情路由。
        parsed = urlparse(source_url)
        self._source_url = source_url
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        # 门户前缀 = 列表页路径去掉最后一段（section）。北森详情路由 = {origin}{prefix}/zwxq?jobAdId=
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        # 必须每次绑定到当前 source_url：本类实例在 run.py/probe.py 是**共享单例**，
        # 用 `if not self.list_urls` 会让首个源的 URL 粘住，后续源全去抓首个源 → 张冠李戴（B 公司入了 A 的岗位）。
        self.list_urls = [source_url]
        return super().fetch(source_url)

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口里直接给的 per-job 链接（最可靠）
        raw = _first_str(post, ("detailUrl", "jobUrl", "positionUrl", "url",
                                "link", "href", "applyUrl", "detail_url", "job_url"))
        if raw:
            if raw.startswith("http"):
                return raw
            return urljoin(
                getattr(self, "_source_url", None)
                or (getattr(self, "_origin", "") + "/"),
                raw,
            )
        # 2) 已知 ATS 形态才用模板兜底（company_spa 不设模板 → 返回空 → 丢弃）
        if self.detail_template and job_id:
            return self.detail_template.format(host=getattr(self, "_host", ""), id=job_id)
        return ""

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        job_id = _first_str(post, ("id", "jobId", "positionId", "code", "postId",
                                   "job_id", "position_id", "uuid", "Id", "JobAdId"))
        title = _first_str(post, ("title", "name", "jobTitle", "positionName",
                                  "job_title", "position_name", "jobName", "JobAdName"))
        if not title:
            return None
        jd_url = self._resolve_url(post, job_id)
        if not jd_url:
            return None

        summary = _first_str(post, ("description", "jobDescription", "responsibility",
                                    "requirement", "duty", "jobDesc", "content",
                                    "job_description")) or None
        if not summary:
            # 北森 GetJobAdPageList 用大写 Duty(职责)/Require(要求)（live 实测 2026-06-10），
            # 此前因大小写不匹配整体丢弃 → beisen 万级岗位 summary 全空。两段拼接（同 feishu/hotjob 口径）。
            duty = _first_str(post, ("Duty",))
            require = _first_str(post, ("Require", "Requirement"))
            summary = (duty + ("\n【任职要求】\n" + require if require else "")).strip() or None
        job_type = _first_str(post, ("jobType", "recruitType", "categoryName",
                                     "positionType", "type")) or None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=_city_of(post) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            salary_text=_first_str(post, ("Salary", "salary", "salaryText", "salaryName")) or None,
            posted_at=normalizer.pick_publish_date(post),
        )


# 角标（「急」这类小标签）。新版卡片里它单独成行，文字各租户自己定：2026-10-11 的 DOM 抽样里出现过
# 急 / 热 / HOT / Hot / 热招。认不全也不要紧——有发布日期行的卡另有不靠词表的判据，见 _split_moka_title。
_MOKA_FLAGS = ("火热招聘", "热招", "急", "热", "新", "HOT", "NEW", "Hot", "New", "hot", "new")
# 老版卡片的角标粘在标题前面（'急客户端c++研发'）。实测只有「急」（96 张老版卡的 DOM 抽样全是它），「火热招聘」是早年的写法。
# 🚫 不许把「热」「新」放进来：标题自己就以它们开头的岗多得多（热管理工程师 / 新媒体运营 / 新能源…）。
#    改前四个字都剥、且不分新老版，同日 38,789 张卡里有 424 张标题因此不对（多数是被剥掉了第一个字）。
_MOKA_GLUED_FLAGS = ("火热招聘", "急")
# 卡片上的发布日期行：新版「发布于 2026-10-09」、英文门户「Posted on 2026-10-10」、老版「发布时间：2026-05-20」。
_MOKA_NEW_PUBLISHED_PREFIXES = ("发布于", "Posted on")
_MOKA_PUBLISHED_LABEL = r"(?:发布于|发布时间[:：]?|Posted on)"
_MOKA_PUBLISHED_RE = re.compile(_MOKA_PUBLISHED_LABEL + r"\s*\d")
_MOKA_FIELD_SEP = "|"
_CJK_RE = re.compile(r"[一-鿿]")
# 老版卡片标题后面最多几行（标签行 + 地点行；发布时间行不算）。实测带「发布时间」行的 824 张老版卡全部 ≤2 行。
_MOKA_OLD_LAYOUT_MAX_LINES = 2
# 地点多于 3 个时 Moka 只列前 3 个，后面跟「等5个地点」（老版写成「 等13个地点」）。
_MOKA_MORE_PLACES_RE = re.compile(r"\s*等\s*\d+\s*个地点$")
# 「省·市·区」里词表外的下级（区县 / 县级市）：前面有认得的上级才放行，见 _is_moka_place。
_MOKA_SUB_PLACE_RE = re.compile(r"[一-鿿]{1,9}(?:自治州|自治县|自治旗|地区|新区|市|区|县|州|盟|旗)")
# 第一级不会是区 / 县 / 旗（自治区、特别行政区除外）：「广东区」「浙江区」是销售大区，is_place_name 却会认（名字 + 行政后缀）。
_MOKA_DISTRICT_HEAD_RE = re.compile(r"(?<!自治)(?<!行政)[区县旗]$")
# 说不到城市的地点，整行只有它们时当作没写：
#   · 只写到国家一级的本国地点（「中国」，同日 1,212 张卡）、只写了省名的（「湖北」）——读侧「地点非空且对不上目标城市」
#     是硬拒（lib/opportunities/eligibility.ts locationState），写进去会把这个岗从填了城市的用户那里藏掉，
#     还会盖掉标题里更准的城市（正泰校招标题写「…-黄冈」，卡片地点只写「湖北」）。
#     带「省」字的写法（「河南省」）改前就在写，这次不动；与标题兜底「只写到省不填」同一个理由（geo.title_city_location ③）。
#   · 「海外其他」：Moka 自己的「其它境外」选项，说不出是哪国。
_MOKA_OTHER_OVERSEAS = "海外其他"
# ⚠️「台湾省」不在此列：它必须照常写出去，才会被出口的台湾红线拒收（normalizer.validate_job_quality）。
_MOKA_VAGUE_PLACES = frozenset({"中国", "全国", "china", "prc", "cn", "greater china", _MOKA_OTHER_OVERSEAS,
                                *(name for name in TITLE_CITY_PROVINCE_NAMES if not name.startswith("台湾"))})


def _first_line(exc: BaseException, limit: int = 240) -> str:
    """异常的类型 + 首行信息（Playwright 报错动辄几十行 call log，只留能定位问题的那一行）。
    首行走 base.exc_brief（URL 脱敏、绝不抛）；点击超时再把 call log 里点名挡住按钮的那一行接上。"""
    head = exc_brief(exc, limit)
    try:
        rest = str(exc).strip().splitlines()[1:]
    except Exception:  # noqa: BLE001 —— 跑在 except 分支里，摘要失败不能再抛
        rest = []
    for line in rest:
        if "intercepts pointer events" in line:   # 点名挡住按钮的元素，比首行更有用
            head = f"{head} | {redact_urls(line.strip(), limit + 1000)}"
            break
    return head[:limit]


def _split_moka_title(lines: List[str]):
    """卡片各行 → (标题, 标题之后的行, 角标是不是单独成行)。

    新版卡片的角标单独一行、下一行才是标题。除了认已知的角标文字，还有一条不靠词表的判据：
    标题后面紧跟的就是发布日期行，所以「第三行才是发布日期」说明第一行是角标（富途校招的角标写的是「Hot」）。
    """
    badge_line = len(lines) > 1 and (
        lines[0] in _MOKA_FLAGS
        or (len(lines) > 2 and lines[2].startswith(_MOKA_NEW_PUBLISHED_PREFIXES)
            and not lines[1].startswith(_MOKA_NEW_PUBLISHED_PREFIXES)))
    if badge_line:
        return lines[1], lines[2:], True
    return lines[0], lines[1:], False


def _has_new_date_line(rest: List[str]) -> bool:
    """标题后面第一行是不是新版的发布日期行（「发布于 …」/「Posted on …」）——有它就一定是新版卡片。"""
    return bool(rest) and rest[0].startswith(_MOKA_NEW_PUBLISHED_PREFIXES)


def _moka_card_fields(rest: List[str]):
    """标题之后的行里，哪些是卡片字段（薪资 / 部门 / 职位性质 / 职能类别 / 地点），正文一行都不要。
    返回 (字段行, 卡片上有没有字段标记, 紧跟在字段区下面的那一行)。

    新版卡片：字段之间是单独一行「|」，带省略提示的字段渲染两遍（连着两行相同），最后一个字段后面
    紧跟正文。所以一行算字段，当且仅当它「重复了两行」「后面是 |」「前面是 |」三者占一；字段后面不再是
    「|」= 字段区到此为止。字段区下面那一行多数门户是正文，但有的门户在那里单独放一行地点
    （福瑞泰克「上海市 浙江·杭州市」、阳光电源校招「合肥」），所以把它一并交回去，由调用方看它是不是地名。
    老版卡片没有这些标记：标题后面只有「标签行 + 地点行」（发布时间在最后、卡片上没有正文），两行都算。
    两种都不是（新版但没配置任何字段，标题后面直接是正文 / 投递说明）→ 没有字段。正文里的短行不许当字段：
    「招聘城市 / 北京 / 上海 / 广州」逐行列城市的正文，会被读成只在最后那个城市。
    """
    new_layout = _has_new_date_line(rest)
    rest = [ln for ln in rest if not _MOKA_PUBLISHED_RE.match(ln)]
    fields: List[str] = []
    i, after_sep = 0, False
    while i < len(rest):
        if rest[i] == _MOKA_FIELD_SEP:
            i, after_sep = i + 1, True
            continue
        doubled = i + 1 < len(rest) and rest[i + 1] == rest[i]
        nxt = i + (2 if doubled else 1)
        sep_follows = nxt < len(rest) and rest[nxt] == _MOKA_FIELD_SEP
        if not (doubled or sep_follows or after_sep):
            break
        fields.append(rest[i])
        if not sep_follows:
            return fields, True, (rest[nxt] if nxt < len(rest) else None)
        i, after_sep = nxt, False
    if fields:
        return fields, True, None
    if new_layout or len(rest) > _MOKA_OLD_LAYOUT_MAX_LINES:
        return [], False, None
    return rest, False, None


def _is_moka_place(place: str) -> bool:
    """一个地点：「四川·成都市」「上海市」「上海市·黄浦区」「香港」「中国香港」「新加坡」。

    第一级必须整段是认得的地名（is_place_name），后面的下级可以是词表外的区县。
    不认第一级 = 不认整个地点：「华北区域」「广东大区」「河南省公司」「上海战区」都卡在这里。
    """
    if place == _MOKA_OTHER_OVERSEAS:
        return True
    head, *subs = place.split("·")
    if head.startswith("中国") and len(head) > 2:
        head = head[2:]                   # 老版把港澳写成「中国香港」
    if not is_place_name(head) or _MOKA_DISTRICT_HEAD_RE.search(head):
        return False
    return all(is_place_name(s) or _MOKA_SUB_PLACE_RE.fullmatch(s) for s in subs)


def _latin_places(text: str) -> Optional[List[str]]:
    """英文门户的地点行 → 逐个地点；不是地点行返回 None。

    「Shenzhen, Guangdong」是一个地点（城市, 省），「Hong Kong Shenzhen, Guangdong」是两个：
    逗号连着的算同一个地点，只隔空格的算下一个。每个词都得落在英文地名里（「hong kong」这种多词地名按最长的认）。
    """
    low = text.lower()
    if re.sub(r"[a-z.'\s,-]", "", low):
        return None                       # 有数字 / & / 其它符号：「R&D」不是地点
    words = list(re.finditer(r"[a-z][a-z.'-]*", low))
    places: List[str] = []
    i, prev_end = 0, 0
    while i < len(words):
        for size in (3, 2, 1):            # 「salt lake city」「hong kong」「shenzhen」
            if i + size > len(words):
                continue
            name = low[words[i].start():words[i + size - 1].end()]
            if is_place_name(re.sub(r"\s+", " ", name)):
                break
        else:
            return None
        if places and "," in low[prev_end:words[i].start()]:
            places[-1] += ", " + name
        else:
            places.append(name)
        prev_end = words[i + size - 1].end()
        i += size
    return places or None


def _moka_places(line: str) -> Optional[List[str]]:
    """整行是地点字段 → 逐个地点；不是 → None。多个地点用空格并列（「吉林·长春市 辽宁·沈阳市」）。

    按内容认、不按字眼认：带「区 / 市」字样的部门名、职能类别比比皆是（「华北区域」「发行市场类」「全职市场类」）。
    整行说不到城市的（「中国」「湖北」「海外其他」）也返回 None，理由见 _MOKA_VAGUE_PLACES。
    """
    if not _CJK_RE.search(line):
        places = _latin_places(line)
    else:
        places = _MOKA_MORE_PLACES_RE.sub("", line).split()
        if not all(_is_moka_place(p) for p in places):
            return None
    if not places or all(p.lower() in _MOKA_VAGUE_PLACES for p in places):
        return None
    return places


def _survives_location_cleaning(line: str, places: List[str]) -> bool:
    """这一行地点写进库之后，页面上列的每个国内城市是不是都还匹配得上。

    多地并列的地点行（「北京市 广东·深圳市 上海市」）只在入库清洗不丢城市时才写：读侧地点对不上是硬拒，
    丢掉的那个城市的用户在今日推荐里就看不到这个岗；不写地点它至少还是「城市未知」，标题里带城市的还能由标题兜底。
    清洗（normalizer.clean_location）2026-10-11 起逐个城市折成「北京/深圳/上海」，所以国内城市并列的行都能写了；
    仍然不写的是「等N个地点」的截断行，和清洗会弄丢其中某个国内城市的行。这里直接问清洗的结果，不自己另猜一遍。
    """
    if _MOKA_MORE_PLACES_RE.search(line):
        # 「…等8个地点」只列了前 3 个，没列出来的城市不知道是哪几个：写进去，那几个城市的用户就被硬拒了。
        return False
    if len(places) == 1 and _CJK_RE.search(line):
        return True                       # 单个地点：折成城市名正是清洗该做的（「四川·成都市」→「成都」）
    # 以下是多地并列（或英文行，逗号写法分不清是「城市, 省」还是两个城市）。
    cleaned = normalizer.clean_location(line)
    if cleaned == re.sub(r"\s+", " ", line).strip():
        return True                       # 行里没有别名表里的城市：整行原样入库
    # 整行一起认、再和清洗结果比：省和它自己的城市并列（「广东 广东·深圳市」）时，省是被城市盖住的上级，
    # 逐个地点单独认会把它当成一个丢了的地点。
    if not normalizer.location_place_keys(cleaned).issuperset(normalizer.location_place_keys(line)):
        return False                      # 清洗把行里的某个城市弄丢了（折错城市的那类，见 clean_location）
    any_named = False
    for place in places:
        if normalizer.location_place_keys(place):
            any_named = True
        elif not _beyond_location_column(place):
            return False
    return any_named


def _beyond_location_column(place: str) -> bool:
    """location 列本来就表示不了的地点：只说到国家 / 省的（_MOKA_VAGUE_PLACES），或者在境外。

    location 给国内城市用、国家码只有一个（一岗多地中国优先，见 geo.derive_country_code），
    所以「广东·深圳市 中国」「马来西亚 福建·福州市」里行内的国内城市一个不少就算没丢。
    """
    if place.lower() in _MOKA_VAGUE_PLACES:
        return True
    # 拼音写的省（「Jiangsu」「Henan Sheng」）同样只说到省：「Changzhou, Jiangsu, China」里的城市由拼音表认
    # （geo.latin_cn_places），省这一段不算丢了的地点。
    if normalizer.latin_cn_bare_province(place, assume_cn=True):
        return True
    code = normalizer.derive_country_code(place)
    return code is not None and code not in ("CN", "HK", "MO")


def _parse_moka_card(text: str):
    """从 Moka 岗位卡 innerText（含换行）解析 (location, title)。

    标题在首行；首行是角标（「急」「热招」「Hot」）时取次行，老版卡片角标粘在标题前面时剥掉。
    地点 = 字段行里整行是地名的那一个（见 _moka_card_fields / _moka_places）；卡片上没有地点字段就是 None，
    不去正文里找——正文里带「市 / 区」的短句（「进行市场调查和分析；」）曾被当成地点写进库。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None, ""
    title, rest, badge_on_own_line = _split_moka_title(lines)
    fields, marked, below_fields = _moka_card_fields(rest)
    # 粘连的角标只在老版卡片上剥：新版（有字段标记 / 有「发布于」行）的角标一定单独成行，标题开头的字是标题自己的。
    if not (badge_on_own_line or marked or _has_new_date_line(rest)):
        for f in _MOKA_GLUED_FLAGS:
            if title.startswith(f) and len(title) > len(f):
                title = title[len(f):].strip()
                break
    # 新版卡片的地点是字段区最后一段，只看它：前面的段即使整段是地名也是部门（微医的部门就叫「三明」「山东」）。
    # 最后一段不是地点时，再看字段区下面那一行（有的门户把地点单独放在那儿；别的门户那里是正文，正文不会整行是地名）。
    # 老版卡片没有字段标记，两行都看、取最后一个整行是地名的。
    candidates = fields[-1:] if marked else fields
    if marked and below_fields and not _moka_places(candidates[0]):
        candidates = [below_fields]
    location = None
    for field in candidates:
        places = _moka_places(field)
        if places:
            location = field if _survives_location_cleaning(field, places) else None
    return location, title


# 卡片上的发布日期：年限口径（MokaAdapter._MAX_AGE_DAYS）和写库的 posted_at 都读 _moka_card_published 这一个函数。
# 只认「该在的位置上、整行就是发布日期」的那一行，别处出现的日期一律不认：
#   新版 / 英文门户：标题后面第一行（「发布于 2026-10-09」/「Posted on 2026-10-10」）；
#   老版：卡片最后一行（「发布时间：2026-05-20」），且标题后面连它在内最多 3 行（标签行 + 地点行 + 发布时间）。
# 2026-10-12 全量 417 条在用源、49,641 张卡片原文逐张量过：42,971 张有发布行（三种写法 36,222 / 201 / 6,548），
# 全部落在这两个位置、整行匹配、都是合法日期（2018~2026 年，没有晚于抓取日的），没有一张卡上有两条发布行。
# 其余 6,670 张卡片上没写发布日期（76 个门户整站不展示：特斯拉社招 889 张、康龙化成校招 566 张…）→ None。
# 🚫 不去正文里找：新版卡片带正文摘要，正文里的日期是截止日 / 报名时间 / 年龄要求（「截止日期：2024年08月29日」），
#    哪怕正文里有一整行「发布时间：2023-01-05」也不是这个岗的发布日——认了就会把在招岗按超龄下架、把错日期写进库。
# ⚠️ 这个日期是 Moka 的 publishedAt（门户主文档内嵌的第一页岗位明文里有原始时间戳：416 个门户 3,881 个岗逐个对过，
#    3,866 个同一天、15 个是抓完之后被对方刷新的）= **最近一次发布**，对方刷新后会变新，不是岗位第一次开放的时间；
#    它按浏览器时区渲染（CI 是 UTC，北京时间 0~8 点发布的岗会早一天，实测 0.38%）。租户把日期格式配成 dd/MM/yyyy、
#    或门户渲染成别的语言时认不出 → None（416 个门户全是默认格式）。怎么量的：docs/crawler-adapter-notes.md。
_MOKA_NEW_POSTED_RE = re.compile(
    "(?:" + "|".join(re.escape(p) for p in _MOKA_NEW_PUBLISHED_PREFIXES) + r")\s*(\d{4})-(\d{2})-(\d{2})")
_MOKA_OLD_POSTED_RE = re.compile(r"发布时间[:：]\s*(\d{4})-(\d{2})-(\d{2})")


def _moka_card_published(text: str, today: Optional[date] = None) -> Optional[date]:
    """Moka 岗位卡 innerText → 卡片上写的发布日期。卡片上没写 / 写法认不出 / 不是合法日期 → None，
    不猜、不拿卡片上别的数字顶替。"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    title, rest, _ = _split_moka_title(lines)
    # 标题位置上就是发布行 = 这张卡没渲染出标题（全量里没见过）。日期照认：年限口径要能点名它。
    m = _MOKA_NEW_POSTED_RE.fullmatch(title) or _MOKA_OLD_POSTED_RE.fullmatch(title)
    if not m and rest:
        m = _MOKA_NEW_POSTED_RE.fullmatch(rest[0])
        if not m and len(rest) <= _MOKA_OLD_LAYOUT_MAX_LINES + 1:
            m = _MOKA_OLD_POSTED_RE.fullmatch(rest[-1])
    if not m:
        return None
    try:
        published = date(*(int(g) for g in m.groups()))
    except ValueError:      # 「2026-02-30」这种不是日期
        return None
    # 发布日不可能晚于今天（留一天余量：卡片按浏览器所在时区渲染，可能比抓取机的日期早翻一天）。全量里没有这样的卡；
    # 真出现了宁可留空：读侧「按发布时间排」会把它一直顶在最前、「最近 N 天发布」永远命中。
    if published > (today or date.today()) + timedelta(days=1):
        return None
    return published


_MOKA_INIT_DATA_RES = (
    re.compile(r'<input\b[^>]*?\bid="init-data"[^>]*?\bvalue="([^"]*)"'),
    re.compile(r'<input\b[^>]*?\bvalue="([^"]*)"[^>]*?\bid="init-data"'),
)


def _moka_portal_total(document_html: str) -> Optional[int]:
    """Moka 门户页自报的岗位总数（内嵌数据的 jobStats.total）。读不到 / 不是非负整数一律返回 None。"""
    for pattern in _MOKA_INIT_DATA_RES:
        m = pattern.search(document_html or "")
        if not m:
            continue
        try:
            total = (json.loads(_html.unescape(m.group(1))).get("jobStats") or {}).get("total")
        except (ValueError, TypeError, AttributeError):
            return None
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            return total
        return None
    return None


def _moka_list_filter(source_url: str) -> str:
    """source_url 的 hash 里带的列表筛选 → 要打开的路由「#/jobs?<筛选>」；没带筛选返回空串。

    写法就是门户自己选完筛选项后地址栏里的那一段，原样用、不重新编码（2026-10-12 在麦当劳老版门户上逐项点出来的：
    `zhineng=<职能 id>`、`department=[id,id]`、`keyword=<词>`）。`page=N` 是翻页位置不是筛选，去掉后从第 1 页开始。
    """
    path, _, query = (source_url or "").partition("#")[2].partition("?")
    if path != "/jobs":
        return ""
    kept = [part for part in query.split("&")
            if "=" in part and part.split("=", 1)[0] != "page" and part.split("=", 1)[1]]
    return "#/jobs?" + "&".join(kept) if kept else ""


# ── 一个 Moka 门户发多家公司的岗（2026-10-12）────────────────────────────────────────────
# 北森国寿 / 广发那块碑（_BEISEN_SHARED_TENANTS）在 Moka 上的同一种情况。
# 租户 crland 是华润置地的，校招门户 168540（门户名「华润置地2027届秋招」）自报 441 个岗，其中 372 个的部门挂在
# 「华润万象生活」节点下（必投清单里是另一家公司）。旧代码每条都贴 sources.company →
# 缺口台账记华润置地校招 441、华润万象生活校招 5，按「华润万象生活」筛校招几乎看不到岗。
#
# 判据 = 标题末尾括号里「-」之前的那一段（「万象生-推广岗（商业-厦门)」→ 商业）。为什么是它：
#   · 岗位卡只渲染标题和地点（门户配置 jobsListSettings.jobEnableFields = ["title", "location"]），部门不在卡片上；
#   · 2026-10-12 全集对拍：用页面自己的部门筛选（hash 参数 department[0]=<部门 id>）把 46 个部门逐个取回来，
#     每个部门的条数都等于门户内嵌数据 jobsGroupedByDepartment 的 jobCount（父节点的结果含整棵子树：
#     商业航道 245 = 直属 17 + 11 个子部门，物业航道 123 = 直属 12 + 14 个子部门）。441 个岗逐个比「直属部门」与「标题这一段」：
#       商业 242 / 物业 123 / 万象生活总部 4 / 写字楼 3 → 部门全在华润万象生活节点下（372）；
#       开发 34 / 文体 23 / 有巢 7 / 酒管 5 → 部门全是华润置地其它航道（69）；对不上 0、认不出 0。
#     逐条真值在 fixtures/moka_crland_campus_titles.json，test_moka_shared_portal 全量回放。
#   · 不用页面上的「业务赛道」筛选（自定义字段 332245）：同日 10 个岗（全在商业华北大区）没填这个字段。
#   · 不在抓取里用部门筛选逐个取：每晚要多翻一遍列表，而且筛选参数名一旦对不上页面会直接忽略它、
#     返回整个列表（实测 departmentIds[0] / deptId[0] 都是这样）——那会把全部岗都判给别家。
#   · 标题开头的校招品牌（百匠新人 / 万象生 / 万悦生 / 销冠生）不是判据：百匠新人同时出现在开发 32、商业 37、物业 12，
#     万悦生在物业 111、酒管 5，万象生在商业 205、文体 18。
# 认不出的业务段（含没有末尾括号的标题）一律留在门户本家，不猜；每轮在日志里点名。
#
# 「租户/门户号」→ {"owners": {业务段: 归属公司}, "home_segments": 核实过属于门户本家的业务段, "home_company": 门户本家}。
# 按整段相等认，不按子串（同 _BEISEN_SHARED_TENANTS 用前缀不用子串的理由）。
# 本家的行抓取时不写公司名、照旧由 sources.company 兜底（与别的 adapter 同一个约定）；home_company 是给存量脚本
# 核对用的：那条源在 sources 里的名字和它对不上时，reattribute_moka_shared_portal 拒绝动库。
# ⚠️ 只登记核实过的这一个门户：校招换期会换门户号，新门户要重新对拍后再登记（那条源的 notes 里也写了）。
_MOKA_SHARED_PORTALS = {
    "crland/168540": {
        "owners": {"商业": "华润万象生活", "物业": "华润万象生活",
                   "写字楼": "华润万象生活", "万象生活总部": "华润万象生活"},
        "home_segments": frozenset({"开发", "文体", "有巢", "酒管"}),
        "home_company": "华润置地",
    },
}
# 门户页地址 / 岗位链接里的「租户/门户号」：…mokahr.com/{campus-recruitment|social-recruitment|apply|…}/{租户}/{门户号}
_MOKA_PORTAL_KEY_RE = re.compile(r"^https?://[^/]*mokahr\.com/[^/#?]+/([^/#?]+)/(\d+)(?![\w-])", re.I)
_MOKA_TITLE_TAIL_RE = re.compile(r"[（(]([^（()）]*)[)）]\s*$")
_MOKA_SEGMENT_SEP_RE = re.compile(r"[-－—–]")


def moka_portal_key(url: str) -> str:
    """Moka 门户页地址或岗位链接 → 「租户/门户号」（小写，同 ops_watchdog.portal_identity）；认不出返回空串。"""
    m = _MOKA_PORTAL_KEY_RE.match(url or "")
    return f"{m.group(1)}/{m.group(2)}".lower() if m else ""


def moka_title_segment(title: str) -> str:
    """标题末尾括号里「-」之前的那一段；标题不以括号结尾返回空串。"""
    m = _MOKA_TITLE_TAIL_RE.search(title or "")
    return _MOKA_SEGMENT_SEP_RE.split(m.group(1))[0].strip() if m else ""


def moka_shared_portal(url: str) -> Optional[dict]:
    """门户页地址或岗位链接所在的门户若登记为「发多家公司的岗」，返回它的登记项；否则 None。"""
    return _MOKA_SHARED_PORTALS.get(moka_portal_key(url))


def moka_shared_portal_verdict(portal_url: str, title: str):
    """共享门户里这个岗归谁 → (归属公司 | None, 判得了没有)。

    (公司, True) = 归别家；(None, True) = 不是共享门户，或业务段核实过属于门户本家；
    (None, False) = 共享门户里认不出的业务段，留在本家（沿用 sources.company），调用方要点名。"""
    portal = moka_shared_portal(portal_url)
    if not portal:
        return None, True
    segment = moka_title_segment(title)
    owner = portal["owners"].get(segment)
    if owner:
        return owner, True
    return None, segment in portal["home_segments"]


class MokaAdapter(PlaywrightAdapter):
    """Moka 招聘（{tenant}.mokahr.com / app.mokahr.com）—— 大量消费/互联网/游戏私企在用。

    Moka 列表接口的数据是**加密的**（响应体 data 为密文 + necromancer，反爬），拦截 JSON 拿不到岗位明文；
    故改为**渲染后解析 DOM**：页面 JS 解密后岗位卡渲染为 `a[href*='#/job/{uuid}']`，
    per-job 详情链接 = `{base}#/job/{uuid}`（hash 路由，可直达岗位）。
    source_url 填某公司 Moka 公开招聘页（如 https://app.mokahr.com/apply/shein/2933）。
    只要门户里的一部分岗时，把门户自己的筛选写在 source_url 的 hash 里
    （…/social-recruitment/mcdchina/4610#/jobs?keyword=…，见 _moka_list_filter 与 _LEGACY_LIST_CARD_SEL）。
    """

    name = "moka"
    company_name = ""  # 由 sources.company 兜底
    wait_ms = 5500
    # 不同 Moka 页岗位列表挂在不同 hash 子路由，逐个试取岗位最多的
    _routes = ("#/jobs", "", "#/campus/jobs", "#/positions")
    # 「列表渲染完」的判据 = 岗位卡出现，或出现 Moka 自己的空态文案。**不等 networkidle**：
    # 2026-09-10 起 Moka 新版前端（recruitmentWeb-20260910-*）每页都 POST sentry-fe.mokahr.com，
    # 该主机从 GitHub runner 连不上且不断开（runner 上 curl 20s 超时），请求永远挂着 →
    # networkidle 永远等不到 → 4 个路由 ×35s 全超时被吞 → 0 岗记 success（410 个源日产 3.6 万 → 535）。
    # 而同一页面岗位卡在 commit 后 4~8s 就渲染出来了。
    # 空态文案取自真实空租户：新版「暂无匹配职位」（科沃斯）、老版「尚无任何相关职位」（知乎）。
    _EMPTY_MARKERS = ("暂无匹配职位", "尚无任何相关职位")
    # 租户门户被 Moka 关停时整页只有这一句（人福医药 / 观远数据 / 真格基金等，标题同文）。
    # 它既不是「0 岗」也不是「没渲染出来」，单独报出来，好让人去停用这条源。
    # 英文那句是同一张页面的英文版：门户默认语言是英文的租户（Meshy 的 apply/taichi/148086）关停后给的是它，
    # 带中文 Accept-Language 也一样。2026-10-11 之前只认中文 → 四个路由各等满 20 秒，记成
    # 「job list not found on any route」，原因写错、每轮白等 80 秒。
    # 关停文案同时看 <title>：它是服务端直接写进 HTML 的（httpx 读过中英两种关停页，标题都与那句话同文），
    # 不依赖前端把那句话渲染出来；比对不分大小写（innerText 会跟着 CSS 的 text-transform 变）。
    _CLOSED_MARKERS = ("当前网页已关停", "This website has been shut down")
    # 岗位卡的选择器。下面几段页面脚本里写的也是这一串（_scoped 按它替换），改这里要一起改。
    _CARD_SEL = "a[href*='#/job/']"
    # 带筛选的源（source_url 的 hash 里写了筛选，见 _moka_list_filter）只读列表区：
    # 老版门户的页面是两栏，列表和翻页器在 .col-xs-9 里，右栏「最新职位」（.col-xs-3，5 张）不受筛选影响。
    # 2026-10-12 麦当劳门户实测：筛出 0 条时列表区只有一句「尚无任何相关职位」，右栏照样挂着 5 个门店岗——
    # 不限定列表区，每晚会把这 5 个筛选之外的岗收进来。
    # ⚠️ 筛选只在老版门户（websiteVersion=1）上验过。新版门户没有这个两栏结构，带筛选的源会等不到列表区的岗位卡、
    #    记成失败——这是有意的：没验过的门户上宁可报错，也不把整站的岗当成筛选结果收进来。
    _LEGACY_LIST_CARD_SEL = ".col-xs-9 a[href*='#/job/']"
    _card_sel = _CARD_SEL     # 这条源读哪里的岗位卡（fetch 开头按有没有筛选定）
    _list_filter = ""         # 这条源要打开的筛选路由（没有筛选为空串）
    _READY_TIMEOUT_MS = 20000
    _READY_JS = ("([markers, closed]) => {"
                 " if (document.querySelectorAll(\"a[href*='#/job/']\").length > 0) return 'cards';"
                 " const t = (document.body && document.body.innerText) || '';"
                 " const low = (t + '\\n' + (document.title || '')).toLowerCase();"
                 " if (closed.some(c => low.includes(c.toLowerCase()))) return 'closed';"
                 " return markers.some(m => t.includes(m)) ? 'empty' : false; }")
    # Moka 列表每页仅渲染 ~30 个岗位卡，其余在「sd-Pagination」分页组件后面（非 ant，非滚动加载）。
    # 不翻页只能拿首页，岗位多的租户被截断（如李宁 32/176、SHEIN 34/747）。逐页点「下一页」累加全量。
    # 单租户抓取条数上限 → 换算成页数上限（env CRAWL_MAX_JOBS 整体调档，见 base.resolve_page_cap）。
    # ⚠️ 旧实现写死 `_page_cap = 60`（"封顶约 1800 岗，足够覆盖最大租户 SHEIN ~25 页"）——
    # 那个 60 背后其实是「当时最大的租户多少页」，租户一扩招就悄悄截断且 status 还是 success：
    # 2026-09-04 live 实测吉利控股自报 86 页/2,580 岗，卡在 60 页只拿到 1,800，漏 780。
    # 收归同一个旋钮后，页数上限只剩「防失控」的兜底作用，真正的收尾交给分页器自报的总页数。
    _MAX_JOBS = DEFAULT_LIST_CAP
    # 显式覆写（只翻前 N 页）的口子，供单测与 verify_sources 的廉价探活用；None = 走共享旋钮。
    # 同 wt._PAGE_CAP / sf_express.MAX_PAGES 的既有写法。
    _page_cap = None
    # 翻页器有两套，选择器都是 2026-10-11 在真浏览器里读的（祖龙 zulong/25157 六页逐页翻到底、特斯拉 tesla/46129）：
    #   新版门户（页面内嵌数据 websiteVersion=2）：sd-Pagination 组件，「下一页」是 button，class 前缀稳定
    #     （带 build hash 后缀），末页加 disabled 属性；30 行/页。
    #   老版门户（websiteVersion=1）：容器 .theme-pagination，按钮全是 span.pagination-item；「下一页」的 class 带
    #     next-page-<hash>，末页多一个 disabled-<hash> 的 class（没有 disabled 属性）；15 行/页。
    # 2026-10-11 之前只认新版那一套，老版门户一律被当成「单页租户不渲染分页器」：只拿第 1 页，还记成抓全。
    # 417 条在用的源里 43 条如此（祖龙自报 86 只入库 15，万科 1,312 / 15，移远 730 / 15）。
    _next_sel = ("button[class*='sd-Pagination-forward'], "
                 ".theme-pagination .pagination-item[class*='next-page-']")
    # 分页器里的页码按钮：末页页码 = 总页数（老版的上一页 / 下一页按钮没有文字，不影响取最大值）。
    _page_no_sel = ("[class*='sd-Pagination'] [class*='sd-Pagination-item'], "
                    ".theme-pagination .pagination-item")
    _active_page_sel = ("[class*='sd-Pagination-is-active'], "
                        ".theme-pagination .pagination-item[class*='active-']")
    _legacy_pager_sel = ".theme-pagination"
    _cards_js = ("els => els.map(e => ({href: e.getAttribute('href'),"
                 " text: (e.innerText || '').trim()}))")
    _PAGE_ROWS = 30          # 新版门户「30 行/页」，分页器上写着
    _PAGE_ROWS_LEGACY = 15   # 老版门户每页 15 行（祖龙 6 页 = 15×5 + 11）
    _rows_per_page = _PAGE_ROWS   # 当前这条源按哪套翻页器算（_collect_all_pages 开头判定）
    _pager_seen = False           # 翻页过程中见没见过下一页按钮 / 页码
    # 点了「下一页」之后，列表和翻页器会先从页面上整个消失，等数据回来再一起渲染（两套门户都是）。
    # 2026-10-11 本机实测消失的时长：万科 0.8~0.95s、特斯拉 1.1~1.6s、麦当劳 2.6s（runner 在境外，只会更久）。
    # 旧写法固定等 1.8s 就读：没等到的那一拍读到「没有新卡 + 没有下一页按钮」，被当成单页租户收工、不留停因
    # （吉利 / 百济神州 / 58同城 / 太古地产的抓不全记录都是「停在半路、停因为空」）。
    # 所以改成等「翻页器回来了，且卡片换了一批、当前页码也变了」。
    _TURN_TIMEOUT_MS = 20000
    _TURN_SETTLE_MS = 400
    _TURN_FALLBACK_MS = 1800   # 判据本身没跑成（不是超时）时退回旧的固定等待，至少不比改前差
    _TURNED_JS = ("([nextSel, activeSel, prevCards, prevActive]) => {"
                  " if (!document.querySelector(nextSel)) return false;"
                  " const cards = [...document.querySelectorAll(\"a[href*='#/job/']\")]"
                  ".map(e => e.getAttribute('href')).join('|');"
                  " if (!cards || cards === prevCards) return false;"
                  " const a = document.querySelector(activeSel);"
                  " return !prevActive || !a || (a.innerText || '').trim() !== prevActive; }")
    # 首屏同理：「出现了岗位卡」不等于「列表渲染完了」——页面上另有一小块推荐岗（老版右栏「最新职位」5 张、
    # 新版 8 张），它先于列表出现。2026-10-12 对拍实测滴滴（门户自报 637）：开始读的那一刻页面上只有那 8 张、
    # 翻页器还没出来，读完这 8 张列表才到，接着点了下一页 → 第 1 页列表里另外 22 个岗没读到，还记成抓全。
    # 所以开读之前先等「下一页按钮出现了，或者页面上的岗已经够门户自报的数」；等不到就按现状读，
    # 少了的由 _finalize_coverage 拿门户总数照出来。门户总数读不到时不等（没有判据）。
    _FIRST_PAGE_TIMEOUT_MS = 15000
    _FIRST_PAGE_JS = ("([nextSel, enough]) => !!document.querySelector(nextSel) ||"
                      " new Set([...document.querySelectorAll(\"a[href*='#/job/']\")]"
                      ".map(e => e.getAttribute('href'))).size >= enough")
    # 门户自报的岗位总数：页面 HTML 里 <input id="init-data" value="…HTML 转义的 JSON…"> 的 jobStats.total。
    # 页面脚本一执行就把这个 input 删了（渲染后的 DOM 里没有），所以只能从主文档的响应体里读。
    # 它是「抓全了没有」唯一不依赖翻页器的分母。2026-10-12 拿全部在用的源真跑对过（同一次抓取里先读总数、再翻完）：
    # 404 条翻到末页的源里 398 条与翻到的条数逐个相等，其余 6 条差 -3 / -1 / +1 / +1 / +5（万科 1,312 对 1,307，
    # 逐页核过是 87 整页 + 末页 2 张，门户总数本身多 5）和 1 条偶发的整页没渲染。
    _portal_total = None
    _own_base = None
    # 抓到的条数比门户自报少多少才算「没抓全」：差 2 个以内或 1% 以内算时间差 / 门户总数自己的出入（依据见上）。
    # 老版门户漏掉整个第 2 页最少也少 1 个岗——门户自报 16~17 个、只拿到首屏 15 个的那种，这个容差照不出来；
    # 翻页器认得出来时本来也不靠它。
    _PORTAL_SHORT_MIN = 2
    _PORTAL_SHORT_RATIO = 0.01
    # 发布年限口径（2026-10-12）：卡片上的发布日期早于 _MAX_AGE_DAYS 天前的岗不收，
    # 库里已有的由 run.py 按链接下架成 removed（可逆；岗被重新发布、日期变新后又会被收回来）。
    # 起因：老版门户翻页修好当晚新入库 5,324 个岗，其中 1,698 个是 2024 年及以前发布的（最早 2019 年），
    # 门户仍列着，分不清是常年在招还是没人撤；它们在库里的首见时间却是当晚。
    # 谁定的：设年限口径是创始人同意的（提的建议是「设年限口径、超龄的标成可恢复的下架」，原话回复「按你的建议来」）；
    # 730 这个数是做的人按下面的全集数据取的，创始人没有逐字确认过，可否决——改成 0 即关掉，下一轮抓取会把下架的行收回来。
    # 为什么是 730 天而不是百胜那条的 365 天（_SSR_TENANT_POLICY）：全量 43,400 张带日期的卡片里，超过 365 天的
    # 7,402 张、超过 730 天的 3,737 张。安踏（1,602 张）、岚图（1,352 张）这类有人维护的门户各有四百多个 1~2 年的岗、
    # 却没有一个超过 2 年；超过 2 年的集中在猿辅导（740 张里 606）、万科（1,307 张里 864）、科兴、云从、知道创宇
    # 这类整个门户多年没动的。365 天会把前一类一起下掉。
    # 卡片上没有发布日期的照收（76 条源整个门户都不显示日期，没有证据说它旧）。
    # 筛在列表翻完之后做：fetch_complete / reported_total 不受影响（与百胜那条同理，规则 G 只看 coverage_complete）。
    # ⚠️ 以后要给 moka 开「列表缺席即撤岗」，得先把这批岗排除掉：它们在列表里、只是我们不收，
    #    按缺席判会变成 expired、次日被永久删除。
    # ⚠️ 已知边界：首屏列表没渲染出来、只读到右栏那几张没有日期的小卡时，超龄岗会被当成有效岗收一次（把已下架的行
    #    写回 active），下一轮读到带日期的完整卡片再下架。只在门户总数也读不到的单页门户上可能发生，没见过实例。
    _MAX_AGE_DAYS = 730
    # 这一轮在门户上见到、但超出年限口径没收的岗的链接；run.py 据此下架库里已有的行。每次 parse 重置。
    retire_jd_urls: tuple = ()
    # 部分租户首屏渲染出岗位卡的同时会弹一个「cookies」同意抽屉（sd-Modal-drawer，
    # 按钮文案「好的」），浮在页面最上层拦截点击事件。不清掉它，第一次点「下一页」
    # 就会被它挡住、`nxt.click()` 超时进 except、`_collect_all_pages` 静默停在第 1 页
    # （2026-09-19 live 实测实锤：作业帮/百济神州的 social-recruitment 源常年卡在
    # 30~31/240~510，Playwright trace 显示 click 报
    # 「secret-drawer-content intercepts pointer events」）。campus-recruitment /
    # apply 这类路由多半页数少、根本不需要点「下一页」，所以碰不到这个坑。
    _COOKIE_ACCEPT_SEL = "button:has-text('好的')"
    # 抓全率可观测契约（190 个 moka 校招源此前 reported_total 恒为 None＝不可判定）
    reported_total = None
    fetch_complete = False

    # 校招门户「换期换 id」：同一租户每一期校招新建一个门户 id，公司换期后我们存的那个 id 页面还在、
    # 列表恒空（迁移 286：知乎/菲尼克斯/芯粤能/明源云）。它和「这一批招完、下一批没开」长得一模一样，
    # 都是 success + 0 岗，而假绿体检从 2026-09-23 起不再数休眠的校招入口 —— 不在这里认出来就彻底看不见了。
    # 平台自己的无 id 别名 `campus_apply/{tenant}` 会 302 到该租户**当前生效**的那一期，
    # 所以「本门户 0 岗 且 别名指向另一个 id 且那个门户真有岗」= 我们指着一个旧门户，记 failed 并把新地址带进报错。
    # ⚠️ 只报不自动换：别名不保证指向有岗的门户（华虹的别名指向的恰恰是没配置过的空模板 74008），
    #    换不换由人渲染新门户确认有岗后改 source_url（迁移 286 的做法）。
    # ⚠️ 本门户有岗时绝不查：一个租户常同时开着好几个校招门户（2026-09-23 全量扫 203 条 Moka 校招源，
    #    22 条别名 ≠ 存的 id，其中 20 条照常出岗），「别名不同」本身不说明任何问题。
    _CAMPUS_PORTAL_RE = re.compile(
        r"^https?://([^/]*mokahr\.com)/(?:campus-recruitment|campus_apply)/([^/#?]+)/(\d+)")
    _CAMPUS_ALIAS_ID_RE = r"/(?:campus_apply|campus-recruitment)/{tenant}/(\d+)"

    def _current_campus_portal_id(self, host: str, tenant: str) -> Optional[str]:
        """问平台这个租户当前生效的校招门户 id（`campus_apply/{tenant}` 的 302 目标）。

        问不到返回 None —— 查不到不等于换了期，宁可漏报也不能把一个正常休眠的门户记成失败。"""
        try:
            resp = httpx.get(f"https://{host}/campus_apply/{tenant}",
                             headers={"User-Agent": self.user_agent},
                             timeout=15, follow_redirects=False)
        except httpx.HTTPError as e:
            _log.warning("moka campus alias lookup failed for %s: %s: %s", tenant, type(e).__name__, e)
            return None
        m = re.search(self._CAMPUS_ALIAS_ID_RE.format(tenant=re.escape(tenant)),
                      resp.headers.get("location") or "")
        return m.group(1) if m else None

    def _raise_if_campus_portal_superseded(self, page, source_url: str) -> None:
        """本门户渲染为空时调用：别名指向另一个 id **且那个门户真有岗** → 记 failed 并带上新地址。

        「别名不同」本身不够：租户常同时开着几个门户，别名也可能指向没配置过的空模板（华虹 74008）。
        所以要在同一个浏览器里把别名门户打开看一眼——那边也是空的，就当本门户只是休眠，照常记 0 岗。
        打不开 / 看不清一律不报（宁可漏报，不把休眠记成失败）。"""
        if self._list_filter:
            return  # 带筛选的源：筛出 0 条只说明这一类岗现在没有，不说明门户换了期
        m = self._CAMPUS_PORTAL_RE.match(source_url or "")
        if not m:
            return  # 不是带 id 的校招门户（社招 / 无 id 别名本身就跟着当前期走）
        host, tenant, stored_id = m.groups()
        current_id = self._current_campus_portal_id(host, tenant)
        if not current_id or current_id == stored_id:
            return
        current_url = f"https://{host}/campus_apply/{tenant}/{current_id}"
        cards = []
        for route in self._routes:  # 与本门户同样逐个路由试，岗位卡不一定挂在 #/jobs
            try:
                state, cards = self._open_route(page, current_url + route)
            except Exception as e:  # noqa: BLE001 —— 看不清就不下结论
                _log.warning("moka campus alias portal %s%s not readable: %s",
                             current_url, route, exc_brief(e))   # Playwright 报错后面是几十行 call log
                continue
            if cards or state == "closed":
                break
        if cards:
            raise RuntimeError(
                f"moka campus portal superseded: 本门户 {stored_id} 为空，该租户当前生效的校招门户 "
                f"{current_url} 首屏有 {len(cards)} 个岗；渲染确认后把这条来源改到新门户")

    def _dismiss_cookie_banner(self, page) -> None:
        """点掉可能挡住「下一页」按钮的 cookies 同意抽屉；没有就什么都不做，失败也不影响主流程。"""
        try:
            btn = page.query_selector(self._COOKIE_ACCEPT_SEL)
            if btn and btn.is_visible():
                btn.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            pass

    def _scoped(self, js: str) -> str:
        """页面脚本里数岗位卡的那个选择器，换成这条源该读的范围（带筛选的源只数列表区，其余原样）。"""
        return js if self._card_sel == self._CARD_SEL else js.replace(self._CARD_SEL, self._card_sel)

    def _active_page_text(self, page) -> str:
        """翻页器上当前页的页码文字；读不到返回空串（_TURNED_JS 此时只看卡片换没换）。"""
        try:
            el = page.query_selector(self._active_page_sel)
            return (el.inner_text() or "").strip() if el is not None else ""
        except Exception:  # noqa: BLE001 —— 只是「翻过去没有」的辅助判据，读不到不影响翻页
            return ""

    def _wait_page_turn(self, page, prev_cards: str, prev_active: str) -> bool:
        """点完「下一页」后等列表渲染回来。返回等到没有；没等到不抛，由调用方按「这一页没翻过去」处理。"""
        try:
            page.wait_for_function(
                self._scoped(self._TURNED_JS),
                arg=[self._next_sel, self._active_page_sel, prev_cards, prev_active],
                timeout=self._TURN_TIMEOUT_MS, polling=200)
        except Exception as e:  # noqa: BLE001 —— 超时是这里的正常分支之一
            if "Timeout" not in type(e).__name__:
                # 不是没等到，是判据没跑成（页面被导航走 / 浏览器报错）。按超时处理会立刻回去读，等于没等。
                _log.warning("moka: 等翻页的判据没跑成，退回固定等待：%s", exc_brief(e))
                page.wait_for_timeout(self._TURN_FALLBACK_MS)
            return False
        page.wait_for_timeout(self._TURN_SETTLE_MS)   # 翻页器与卡片同一拍渲染，再留一点余量等卡片文字齐
        return True

    def _wait_first_page(self, page) -> None:
        """开读之前等首屏列表渲染完（判据见 _FIRST_PAGE_JS 上面的注释）。等不到 / 没有判据都不抛。"""
        total = self._portal_total
        if not total:
            return
        try:
            page.wait_for_function(self._scoped(self._FIRST_PAGE_JS),
                                   arg=[self._next_sel, total - self._PORTAL_SHORT_MIN],
                                   timeout=self._FIRST_PAGE_TIMEOUT_MS, polling=250)
        except Exception as e:  # noqa: BLE001
            if "Timeout" not in type(e).__name__:
                _log.warning("moka: 等首屏列表的判据没跑成：%s", exc_brief(e))

    def _collect_all_pages(self, page) -> List[dict]:
        """从当前已渲染的列表路由翻页累加全量岗位卡，按 href 去重（同一个 href 留文字更全的那张）。

        逐次点「下一页」直到：页面上没有该按钮 / 按钮 disabled（末页）/ 连续无新卡 / 点击失败 /
        下一页迟迟渲染不出来 / 重复度刹车 / 触达页数封顶。「页面上没有下一页按钮」不等于抓全，
        由 _finalize_coverage 拿门户自报总数再核一次。
        """
        union: dict = {}
        no_growth = 0
        self._wait_first_page(page)
        self._last_page = self._read_last_page(page)   # 分页器自报的总页数（拿不到=None）
        try:
            legacy = page.query_selector(self._legacy_pager_sel) is not None
        except Exception:  # noqa: BLE001
            legacy = False
        self._rows_per_page = self._PAGE_ROWS_LEGACY if legacy else self._PAGE_ROWS
        self._pager_seen = bool(self._last_page)
        pages_done = 0
        # 翻页为什么停（只在没翻到末页时有意义，见 _finalize_coverage）。2026-09-28 之前这里的
        # 三种停法既不打日志也不写 crawl_runs：09-24~28 的抓不全告警里，百济神州（分页器 17 页）每次都是
        # 30 岗 = 停在第 1 页，58同城（16 页）出现时都是 150 岗 = 停在第 5 页，却分不出是点击被挡还是翻页没生效。
        stop_cause, stop_detail = "list_cap", ""
        brake = RepetitionBrake()
        turn_timed_out = False   # 上一次点完「下一页」没等到渲染，且当时页面上连翻页器都没有
        self._dismiss_cookie_banner(page)   # 翻页前先清场，否则首次点击就会被它挡住
        page_cap = self._page_cap or resolve_page_cap(self._rows_per_page, self._MAX_JOBS)
        for attempt in range(page_cap):
            cards = page.eval_on_selector_all(self._card_sel, self._cards_js)
            before = len(union)
            upgraded = False
            fresh_titles = []   # 这一页新见到的岗的标题，喂给重复度刹车
            for c in cards:
                href = c.get("href") or ""
                if not href:
                    continue
                seen = union.get(href)
                if seen is None:
                    union[href] = c
                    fresh_titles.append(_parse_moka_card(c.get("text", ""))[1])
                elif len(c.get("text") or "") > len(seen.get("text") or ""):
                    # 同一个岗在页面上有两种链接：列表里的完整卡片，和右栏「最新职位」里只有标题的一行（每页都在）。
                    # 右栏的岗不在第 1 页列表里时，先收到的是只有标题的那个；等翻到它所在的页，完整卡片要顶替它，
                    # 否则这个岗的地点字段就丢了（2026-10-11 实测：改前 65 个多页门户里 35 个、共 206 张卡只剩标题）。
                    union[href] = c
                    upgraded = True
            # 只数「真翻到了新一页」：点了没翻过去的那几轮不算。旧写法每轮都 +1，
            # 卡在第 5 页的 6 页租户会数成 7 页 ≥ 总页数 → 判成抓全，缺口从告警里消失。
            # 「顶替了右栏那张」也是翻到新一页的证据：末页的岗若全在右栏里出现过，只看新增会少数一页。
            progressed = len(union) > before or upgraded
            if attempt == 0 or progressed:
                pages_done += 1
            no_growth = 0 if progressed else no_growth + 1
            if no_growth >= 2:  # 连续两页零新增 → 停（防呆）
                stop_cause, stop_detail = "page_no_new_rows", f"点了「下一页」连续 {no_growth} 次，岗位卡没变"
                break
            nxt = page.query_selector(self._next_sel)
            if nxt is None:
                if turn_timed_out and not progressed:
                    # 点了「下一页」，等满了时限，列表和翻页器都没渲染回来（上面已经再读过一次，仍然没有新卡）。
                    stop_cause = "page_render_timeout"
                    stop_detail = (f"第 {pages_done} 页点了「下一页」，{self._TURN_TIMEOUT_MS // 1000}s 内"
                                   "列表和翻页器都没渲染回来")
                else:
                    stop_cause, stop_detail = "", ""
                break  # 页面上没有下一页按钮：单页租户不渲染分页器，也可能是我们不认识的翻页器
            self._pager_seen = True
            cls = (nxt.get_attribute("class") or "").lower()
            if "disabled" in cls or nxt.get_attribute("disabled") is not None:
                stop_cause, stop_detail = "", ""
                break  # 末页：下一页按钮 disabled（新版是属性，老版是 class）
            if brake.observe(fresh_titles):
                # 后面还有页，但连续几百条都没带来新的岗位角色（同一个岗 × N 家门店）→ 按设计停，见 RepetitionBrake。
                stop_cause = "repetition_brake"
                stop_detail = f"翻到第 {pages_done} 页，已收 {len(union)} 条"
                break
            if attempt == page_cap - 1:
                break  # 页数预算用完（停因保持 list_cap）：别再点一次没人读的下一页
            prev_cards = "|".join(c.get("href") or "" for c in cards)
            prev_active = self._active_page_text(page)
            try:
                nxt.scroll_into_view_if_needed(timeout=2000)
                nxt.click(timeout=2500)
            except Exception as first_exc:  # noqa: BLE001 —— 下面重试，再失败就把原因留下
                # 常见诱因：cookies 抽屉在这一拍才弹出来（首屏渲染晚于 _dismiss 那一次调用）。
                # 补清一次、重试点击一次；再失败才真放弃（保留已收的行，不让整源卡死在这一页）。
                self._dismiss_cookie_banner(page)
                try:
                    # 重新取一次按钮：页面在这期间重绘过的话，手里那个句柄已经不在文档里了
                    (page.query_selector(self._next_sel) or nxt).click(timeout=2500)
                except Exception as retry_exc:  # noqa: BLE001
                    # Playwright 的点击超时报错会点名挡住按钮的元素（「<div class=…> intercepts
                    # pointer events」）——这正是判断「是哪个弹层在挡」唯一的现场证据，别丢。
                    stop_cause = "page_click_failed"
                    stop_detail = (f"第 {pages_done} 页点「下一页」两次都失败："
                                   f"{_first_line(first_exc)} / 重试 {_first_line(retry_exc)}")
                    break
            # 没等到渲染时不在这里停：回到循环开头再读一次——页面其实翻过去了就照收；
            # 翻页器在、只是没翻过去，连续两次没有新卡由 page_no_new_rows 收；翻页器也不在，由上面记 page_render_timeout。
            turn_timed_out = (not self._wait_page_turn(page, prev_cards, prev_active)
                              and page.query_selector(self._next_sel) is None)
        self._pages_done = pages_done
        self._stop_cause, self._stop_detail = stop_cause, stop_detail
        return list(union.values())

    def _finalize_coverage(self, best: List[dict], source_url: str = "") -> None:
        """抓全率可观测：写 reported_total / fetch_complete / coverage_stop_reason。
        分母优先用门户自报的岗位总数（_portal_total），读不到才退回分页器的总页数。
        2026-10-11 前只有「没有下一页按钮 = 单页抓全」：43 条老版门户的源每晚只入库首屏 15 个岗、
        记 coverage_complete=true，没有任何告警。没抓全时打一条 warning（带 Playwright 报错原文），下一轮就知道该修哪。
        """
        last_page = getattr(self, "_last_page", None)
        pages_done = getattr(self, "_pages_done", 0)
        portal_total = self._portal_total
        got = len(best)
        if not best and not portal_total:
            self.reported_total = None          # 一条都没拿到、门户也没说有岗，别拿 0 当分母
            return
        # 抓到的数明显少于门户自报（一条都没拿到而门户说有岗，也算）。读不到门户总数时这条不设防。
        short = portal_total is not None and (
            not best
            or portal_total - got > max(self._PORTAL_SHORT_MIN, portal_total * self._PORTAL_SHORT_RATIO))
        # 翻页是自己走到头的（没有下一页按钮 / 下一页按钮 disabled），还是被打断的（点击失败、刹车、撞上限…）。
        # 被打断的一律不算抓全、停因照实写——不能因为页码没读到就当它翻完了。
        stop_cause = getattr(self, "_stop_cause", "") or ""
        by_pages = not last_page or pages_done >= last_page
        # 页数对不上、但门户自报的岗已经一个不少：门户总数是比页码更硬的证据（页码会因整页都是见过的岗而少数一页）。
        got_everything = portal_total is not None and got >= portal_total
        if not stop_cause and not short and (by_pages or got_everything):
            self.reported_total = got if portal_total is None else max(got, portal_total)
            self.fetch_complete = True
            return
        self.fetch_complete = False
        if portal_total is not None:
            self.reported_total = max(got, portal_total)
        elif last_page:
            self.reported_total = max(got, last_page * self._rows_per_page)   # 上界估计，好让告警看得见缺口
        else:
            self.reported_total = got           # 总数和总页数都读不到：只知道没翻完，分母没法估
        if stop_cause:
            cause = stop_cause
        elif short:
            # 页面上能翻的都翻完了，数却对不上。有卡片、却从头到尾没见过下一页按钮 = 多半是我们不认识的翻页器；
            # 其余（翻到了末页仍少 / 一张卡都没渲染出来）= 列表与门户总数对不上，原因要到页面上看。
            unseen_pager = bool(best) and not self._pager_seen
            cause = "paginator_not_found" if unseen_pager else "short_of_portal_total"
        else:
            cause = None                        # 翻页器中途不见了、总数又读不到：原因判不出
        self.coverage_stop_reason = cause
        _log.warning("moka: 没抓全，停在第 %d/%s 页（%d 岗，门户自报 %s），停因=%s %s url=%s",
                     pages_done, last_page or "?", got, "未知" if portal_total is None else portal_total,
                     cause or "未知", getattr(self, "_stop_detail", ""), source_url)

    def _read_last_page(self, page):
        """从 Moka 分页组件读总页数。拿不到返回 None（单页租户不渲染分页器，也走这条）。"""
        try:
            texts = [(e.inner_text() or "").strip() for e in page.query_selector_all(self._page_no_sel)]
        except Exception:
            return None
        numbers = []
        for text in texts:
            for token in re.findall(r"\d+", text):
                try:
                    numbers.append(int(token))
                except ValueError:
                    continue
        return max(numbers) if numbers else None

    def _note_portal_total(self, response, url: str) -> None:
        """从本源主文档的响应体里记下门户自报的岗位总数。读不到就保持原值，绝不抛。

        只认本源自己的地址：校招换期检查会在同一个浏览器里打开别的门户，那边的总数不是这条源的分母。
        只换 hash 的跳转是同文档导航，goto 返回 None，沿用第一次读到的值。
        带筛选的源不记：门户自报的是整站总数（麦当劳 58,187），不是筛选后那个列表的；分母退回翻页器的总页数。"""
        if self._list_filter:
            return
        if response is None or not self._own_base or url.split("#")[0] != self._own_base:
            return
        try:
            total = _moka_portal_total(response.text())
        except Exception as e:  # noqa: BLE001 —— 分母读不到只是退回旧口径，不能影响抓取
            _log.warning("moka: 读门户自报总数失败 %s url=%s", exc_brief(e), url)
            return
        if total is not None:
            self._portal_total = total

    def _open_route(self, page, url: str):
        """打开一个列表路由并等它渲染完，返回 (状态, 岗位卡列表)，状态 ∈ {"cards", "empty", "closed"}。

        既没出岗位卡、也没出空态 / 关停页 → 抛异常（由调用方记成「该路由上没有列表」）。
        渲染出来后仍等 wait_ms 再数卡：一是等整页卡片渲染齐，二是防「数据回来前先闪一下空态」。
        """
        self._note_portal_total(page.goto(url, wait_until="domcontentloaded", timeout=35000), url)
        handle = page.wait_for_function(self._scoped(self._READY_JS),
                                        arg=[list(self._EMPTY_MARKERS), list(self._CLOSED_MARKERS)],
                                        timeout=self._READY_TIMEOUT_MS, polling=250)
        if handle.json_value() == "closed":
            return "closed", []
        page.wait_for_timeout(self.wait_ms)
        cards = page.eval_on_selector_all(self._card_sel, self._cards_js)
        return ("cards" if cards else "empty"), cards

    def _plan_routes(self, source_url: str) -> tuple:
        """这条源要试哪些列表路由，并定下读哪里的岗位卡。

        带筛选的源只开筛选那一个路由、只读列表区：别的路由是不带筛选的整站列表，在那上面抓到的不是这条源要的岗。"""
        self._list_filter = _moka_list_filter(source_url)
        self._card_sel = self._LEGACY_LIST_CARD_SEL if self._list_filter else self._CARD_SEL
        return (self._list_filter,) if self._list_filter else self._routes

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        self.reported_total = None
        self.fetch_complete = False
        self.coverage_stop_reason = None
        self._last_page = None
        self._pages_done = 0
        self._stop_cause, self._stop_detail = "", ""
        self._pager_seen = False
        self._portal_total = None
        base = source_url.split("#")[0]
        self._own_base = base
        routes = self._plan_routes(source_url)
        best: List[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=self.user_agent, locale="zh-CN").new_page()
            try:
                # 先按首页岗位数挑出正确的列表路由（不同 Moka 页挂不同 hash 子路由），
                # 再在该路由上翻页累加全量（多数租户岗位都在 #/jobs，空路由很快返回单页）。
                best_route = None
                best_first = 0
                rendered_empty = False
                route_errors = []
                last_route = None   # 页面当前停在哪个路由（且已渲染完）
                for route in routes:
                    last_route = None
                    try:
                        state, first = self._open_route(page, base + route)
                    except Exception as e:  # noqa: BLE001 —— 记下来，全军覆没时要带着它报错
                        route_errors.append(f"{route or '(root)'}={type(e).__name__}")
                        continue
                    last_route = route
                    if state == "closed":
                        # 整个门户关停，换 hash 路由也是同一页，不必再试
                        raise RuntimeError(
                            "moka portal closed: page says「" + "」/「".join(self._CLOSED_MARKERS) + "」")
                    if state == "empty":
                        rendered_empty = True
                    if len(first) > best_first:
                        best_first, best_route = len(first), route
                    if best_first >= 3:
                        break  # 命中有岗位的路由即可，无需续试空路由
                if best_route is None and not rendered_empty:
                    # 所有路由都既没出岗位卡、也没出空态 = 没找到岗位列表（没渲染出来 / 入口已跳走）。
                    # ⚠️ 不许安静返回 0 岗：那会记成 success，2026-09-10 起 312 个源天天「0 岗成功」没人发现。
                    raise RuntimeError(
                        "moka job list not found on any route (no job cards, no empty state): "
                        + ", ".join(route_errors)
                        + ("；这条源带筛选，只读老版门户的列表区（.col-xs-9）——门户换了版式就读不到，到页面上核一下"
                           if self._list_filter else ""))
                if best_route is None:
                    # 渲染出了空态、一张卡都没有：先排除「我们指着一个已换期的旧门户」再认 0 岗。
                    self._raise_if_campus_portal_superseded(page, source_url)
                if best_route is not None:
                    # 已在这个路由上见过岗位卡；这一步再失败就是真故障，同样不许吞成 0 岗。
                    # 页面还停在该路由首页（循环在它上面 break 了）就不必重开一遍。
                    if last_route != best_route:
                        self._open_route(page, base + best_route)
                    best = self._collect_all_pages(page)
            finally:
                browser.close()
        # 宁可分母偏大被告警盯上，也不要像过去那样 reported_total=None、190 个源集体「不可判定」。
        self._finalize_coverage(best, source_url)
        return json.dumps({"_base": base, "cards": best}, ensure_ascii=False)

    @staticmethod
    def _today() -> date:
        """年限口径按北京时间算天数（与 jobs_db.retire_posted_before 同口径）。"""
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()

    def parse(self, html: str) -> List[RawJob]:
        self.retire_jd_urls = ()
        try:
            data = json.loads(html)
        except (ValueError, TypeError):
            return []
        base = data.get("_base", "")
        out: List[RawJob] = []
        seen = set()
        too_old = []
        today = self._today()
        oldest_kept = today - timedelta(days=self._MAX_AGE_DAYS) if self._MAX_AGE_DAYS else None
        shared = moka_shared_portal(base) is not None   # 一个门户发多家公司的岗：逐行归属
        unknown_titles = []
        for c in data.get("cards", []):
            m = re.search(r"#/job/([\w-]+)", c.get("href") or "")
            if not m:
                continue
            jd_url = f"{base}#/job/{m.group(1)}"
            published = _moka_card_published(c.get("text", ""), today)
            if oldest_kept and published and published < oldest_kept:
                too_old.append(jd_url)   # 正好 _MAX_AGE_DAYS 天前发布的仍收，与 _ssr_policy_allows 同一边界
                continue
            location, title = _parse_moka_card(c.get("text", ""))
            if not title:
                continue
            if jd_url in seen:
                continue
            seen.add(jd_url)
            owner = None
            if shared:
                owner, known = moka_shared_portal_verdict(base, title)
                if not known:
                    unknown_titles.append(title)
            out.append(RawJob(
                company=owner or self.company_name or "",
                title=title,
                location=location,
                job_type=None,
                summary=None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=published.isoformat() if published else None,
            ))
        if len(unknown_titles) * 2 > len(out):
            # 过半的岗认不出业务段 = 标题写法变了，登记的规则已经对不上这个门户。照常入库会把这些岗（包括库里已经
            # 归到别家的）悄悄贴回 sources.company，正是要修的错（同北森共享租户「整批没有招聘机构」那条）：
            # 记失败、这一轮不写，让人来重新对拍。个别认不出的不在此列，走下面的日志。
            raise RuntimeError(
                f"moka: shared portal {moka_portal_key(base)} 的 {len(out)} 个岗里 {len(unknown_titles)} 个认不出业务段"
                f"（例：{unknown_titles[0]}）；拒绝把它们贴给 sources.company，先重新核对标题写法")
        if unknown_titles:
            _log.warning("moka: shared portal %s 有 %d/%d 个岗的业务段认不出，留在门户本家：%s",
                         moka_portal_key(base), len(unknown_titles), len(out),
                         "；".join(dict.fromkeys(unknown_titles[:8])))
        if too_old:
            # 同一个岗万一有两张卡（一张写着旧日期、一张没日期），以写了日期的为准：不能一边点名下架、一边又收进来，
            # 那样库里这一行每晚先下架再被写回。
            old = set(too_old)
            out = [j for j in out if j.jd_url not in old]
            self.retire_jd_urls = tuple(dict.fromkeys(too_old))
            _log.info("moka: 年限口径外 %d 个岗没收（发布日期早于 %s），收 %d 个 base=%s",
                      len(self.retire_jd_urls), oldest_kept, len(out), base)
        return out


# 北森详情路由按租户缓存（host → 详情页 base，如 https://chinalife.zhiye.com/custom/zwxq）。
# 启动时从 crawler/beisen_routes.json 预载（onboarding/probe 探测后落盘提交）→ 每日爬取直接读，不再现场探测。
# 未命中缓存的 host 才现场 render-verify 探测一次（慢，仅新源），结果写回内存缓存。
import json as _json
import os as _os

_BEISEN_ROUTES_FILE = _os.path.join(_os.path.dirname(__file__), "..", "beisen_routes.json")


def _load_beisen_routes() -> dict:
    try:
        with open(_BEISEN_ROUTES_FILE, encoding="utf-8") as f:
            return {k: v for k, v in _json.load(f).items()}
    except (OSError, ValueError):
        return {}


_BEISEN_ROUTE_CACHE: dict = _load_beisen_routes()


def _beisen_route_usable(route) -> bool:
    """这条缓存路由**能不能给新版 GetJobAdPageList 的行拼出 jd_url**。

    能用的只有五种形状：点击捕获的 `{template, idfield}`、旧的 detail base 字符串、
    `{"cms": true}`（老版 theme2 CMS）、`{"cards": true}`（卡片式 CMS，见 _httpx_fetch_cards）、
    `{"ssr": true}`（老版 SSR「jobsTable」路径式详情，见 _httpx_fetch_ssr_paged）。
    后三者不参与 `_resolve_url` 拼链接 —— 它们的 jd_url 来自列表页锚点本身，登记只是为了让
    `beisen_httpx_ready()` 认它「零浏览器可抓」，好让 run.py 把它排进 httpx 并发快车道。
    ⚠️ 2026-09-23 实测：harvest_beisen_routes.py 待探队列 26 家里 23 家（88%）就是这一类——
    `fetch()` 早就能纯 httpx 抓全，只是当时没登记 `{"ssr": true}`，harvest 脚本天天当成
    「还没探出路由」重探、harvested 连续 3 天卡 0（这类租户压根不需要探测）。
    ⚠️ **`{"ssr": true}` 不是** `{ssr_path, ssr_param}`——后者才是被禁的老版残留形状，
    两者字面接近但含义相反，改这里千万别搞混：
    `{ssr_path, ssr_param}` 是**给新版 GetJobAdPageList 的行**配 SSR 锚点里的数字 id 用的模板，
    而新版接口给的是 uuid，两者不通用 —— 2026-09-17 真渲染实测：把新版 uuid 拼进
    `fosunpharma.zhiye.com/campusxq?jobId=<uuid>` / `cnnc.zhiye.com/szxq?…` / `boe.zhiye.com/zwxq?…`，
    三家渲染出来的都是门户首页（body 文本 30~51 字，没有那个岗位），**拼出来就是坏链**。
    而 `_resolve_url` 的 dict 分支只认 template → 这类租户每行 jd_url 都是空串 → 质量门全丢 →
    「success + 0 岗」且不报错。实测这三家躺了很久：复星医药 33 次 success / 0 岗（北森自报 161 个岗、
    其中 71 个校招），中核集团北森自报 854 个校招、库里 0 个，京东方（必投）同病。
    `{"ssr": true}` 则完全不参与拼链接（同 cms/cards），只是「这个 host 走 _httpx_fetch_ssr_paged
    自己从列表锚点里拿 jd_url，不需要任何模板」的标记——两者能用性判据不同，别以为都带 ssr 字样
    就该一视同仁。
    """
    if isinstance(route, str):
        return bool(route)
    if isinstance(route, dict):
        return (bool(route.get("template")) or route.get("cms") is True
                or route.get("cards") is True or route.get("ssr") is True)
    return False


def beisen_httpx_ready(source_url: str) -> bool:
    """该 beisen 源能否走纯 httpx（= 详情路由已缓存**且能用**，能拼 jd_url 不开浏览器）。
    未缓存或缓存形状用不了（含老版 SSR 残留 / 异构租户）→ False → 必须留浏览器档，
    在那里重新探一次路由才有救。
    run.py `_partition_by_tier` 用它做 **per-source** 分档：缓存了的 beisen 进 httpx 快车道，没缓存的留浏览器。"""
    try:
        host = urlparse(source_url or "").netloc
    except Exception:
        return False
    return bool(host) and _beisen_route_usable(_BEISEN_ROUTE_CACHE.get(host))
# 北森详情页常见路由名（zwxq=职位详情拼音；不同租户配置不同：chinalife=zwxq、横店/杰瑞=detail…）
_BEISEN_DETAIL_NAMES = ("zwxq", "detail", "jobdetail", "positiondetail", "jobDetail")

# —— 老版 SSR（C 型）专用：列表页 HTML 直出 per-job 锚点，无 JSON 接口可拦 ——
# 详情页路径因租户而异（中核=szxq、BOE 校招=details2021…），param 多为 jobId(数字)/adId。
# socialxq / overseasxq 是 theme2 老版 CMS 的社招 / 海外板块详情路由（2026-08-27 中芯国际 live 实测）；
# 原来只有 campusxq，导致这类租户的社招 / 海外板块猜不出路由 → jd_url 全空 → 整源判「0 岗」丢弃。
_BEISEN_SSR_DETAIL_PATHS = ("szxq", "szzwxq", "xzxq", "campusxq", "socialxq", "overseasxq",
                            "zwxq", "details2021",
                            "overseadetail", "detail", "jobdetail", "szzp", "xq", "positiondetail")
_BEISEN_SSR_PARAMS = ("jobId", "adId", "jobAdId")
# 从 SSR 列表页抽取 per-job 锚点（jobId/adId/jobAdId=数字或 GUID + 标题文本），去重。
_BEISEN_SSR_ANCHOR_JS = r"""
() => {
  const out=[], seen=new Set();
  const push=(id,name,href)=>{
    if(!name || name.length<3 || name.length>60) return;   // 跳过登录/注册等短文本
    if(seen.has(id)) return; seen.add(id);
    out.push({id, name, href});
  };
  // ① 查询串式：?jobId= / ?jobAdId= / ?adId=（详情 path 因租户而异，需 _discover_ssr_route 探）
  for (const a of document.querySelectorAll(
        "a[href*='jobId='],a[href*='adId='],a[href*='jobAdId=']")) {
    const href=a.getAttribute('href')||'';
    const m=href.match(/(?:jobId|jobAdId|adId)=([^&#]+)/i);
    if(!m) continue;
    push(decodeURIComponent(m[1]), (a.innerText||a.textContent||'').trim(), a.href);
  }
  // ② 路径式：/job_show/230910610、/zpdetail/230300168 …（老版 CMS Portal 租户用这种，
  //    2026-07-27 实测科伦 kelun=/job_show/{id}、启德 eic=/zpdetail/{id}）。
  //    这类 href 本身就是**完整可用的详情链接**，直接带出去用，不需要再猜路由。
  for (const a of document.querySelectorAll("a[href]")) {
    const href=a.getAttribute('href')||'';
    const m=href.match(/\/(?:job[_-]?show|zpdetail|jobdetail|job[_-]?detail|positiondetail)\/(\d{4,})/i);
    if(!m) continue;
    push(m[1], (a.innerText||a.textContent||'').trim(), a.href);
  }
  return out.slice(0,120);
}
"""


_BEISEN_SSR_JD_RE = re.compile(
    r"(工作职责|岗位职责|职位描述|工作内容|岗位描述|职责描述)[：:]\s*(.+)$", re.S)
_BEISEN_SSR_SUMMARY_CAP = 60
# 老版门户详情页的页脚模板（25 个租户同一套，2026-09-24 逐租户取真页核过）：
#   正文 … 现在申请 返回职位列表 收藏 [热招职位 更多 >> 别的岗名…] [长招职位 更多 >> …] ©2026 公司 京ICP备…
# 正文正则取到页尾，不在这里截断就会把页脚与**别的岗位名**一起写进 summary（卡片露出备案号、职能分类读到别的岗）。
# 华夏基金 / 京博的自有详情模板页脚不同：「返回列表 分享： 版权所有：…」「立即申请返回」。
_BEISEN_SSR_FOOTER_RE = re.compile(
    r"\s(?:现在申请\s+返回职位列表|返回职位列表|返回列表|立即申请|热招职位\s*更多|长招职位\s*更多"
    r"|版权所有|©\s*20\d\d)")
# 部分租户的 /zpdetail/{id} 只是跳转壳：隐藏框 #v 写招聘类别，脚本按类别跳到租户自己的详情模板
# （华夏基金 校招/社招/其它 → /yjszwxq /szzwxq /sxszwxq，京博 → /xiangqing2 /xiangqing /xiangqing3）。
_BEISEN_SSR_STUB_CATE_RE = re.compile(r'<input[^>]*\bvalue="([^"]*)"[^>]*\bid="v"', re.I)
_BEISEN_SSR_STUB_BRANCH_RE = re.compile(
    r'cate\s*==\s*"([^"]*)"\s*\)\s*\{\s*window\.location\.href\s*=\s*"(/[^"?]+\?jobId=)"\s*\+\s*(\d+)')
_BEISEN_SSR_STUB_ELSE_RE = re.compile(
    r'\}\s*else\s*\{\s*window\.location\.href\s*=\s*"(/[^"?]+\?jobId=)"\s*\+\s*(\d+)')
_BEISEN_SSR_ZPDETAIL_ID_RE = re.compile(r"/zpdetail/(\d+)")


def _beisen_ssr_fill_summaries(jobs: List[dict]) -> None:
    """老版 CMS Portal 租户：详情页是 SSR 直出正文，纯 httpx 取回来即可（无需浏览器）。

    为何要做：不补正文的话这些岗只是「薄卡」——`count_valid_active_jobs()` 与北极星
    「必投清单健康覆盖」都要求 summary≥60 字，薄卡不计数，等于白抓
    （2026-07-27 实测科伦/启德首抓 17 岗全无正文）。
    只取「工作职责/岗位职责/职位描述」之后的正文，去掉导航与页眉页脚噪声；失败静默跳过（留薄卡）。
    """
    cap = resolve_detail_cap(_BEISEN_SSR_SUMMARY_CAP)
    with httpx.Client(timeout=15, follow_redirects=True,
                      headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
        for job in jobs[:cap]:
            try:
                body = beisen_ssr_fetch_detail_body(
                    lambda u: (lambda r: (r.status_code, r.text))(cli.get(u)), job["jd_url"])
                if body:
                    job["summary"] = body
            except Exception:
                continue


def beisen_ssr_stub_target(html_text: str, page_url: str) -> Optional[str]:
    """/zpdetail/{id} 是跳转壳时，按壳自己的分支（#v 的招聘类别）算出真正的详情页地址；不是壳返回 None。

    跳转目标里的 jobId 必须与原链接的 id 相同才采信——正文宁可取不到，也不能挂到别的岗上。"""
    m = _BEISEN_SSR_STUB_CATE_RE.search(html_text or "")
    own = _BEISEN_SSR_ZPDETAIL_ID_RE.search(page_url or "")
    if not m or not own:
        return None
    cate = m.group(1)
    target = next(((path, jid) for c, path, jid in _BEISEN_SSR_STUB_BRANCH_RE.findall(html_text) if c == cate), None)
    if target is None:
        e = _BEISEN_SSR_STUB_ELSE_RE.search(html_text)
        target = (e.group(1), e.group(2)) if e else None
    if target is None or target[1] != own.group(1):
        return None
    return urljoin(page_url, target[0] + target[1])


def beisen_ssr_fetch_detail_body(get, url: str) -> str:
    """取老版详情页正文；遇到跳转壳按它自己的分支跟一跳。get(url) -> (status_code, text)。取不到返回 ""。"""
    status, text = get(url)
    if status != 200:
        return ""
    body = beisen_ssr_detail_body(text)
    if body:
        return body
    target = beisen_ssr_stub_target(text, url)
    if not target:
        return ""
    status, text = get(target)
    return beisen_ssr_detail_body(text) if status == 200 else ""


def beisen_ssr_detail_body(html_text: str) -> str:
    """老版 SSR / CMS 详情页 HTML → 正文（「工作职责 / 岗位职责 / 职位描述…」之后）；不足 60 字返回 ""。

    抓取时补正文（_beisen_ssr_fill_summaries）与补正文 / 巡检任务（enrich._detail_beisen 的老版分支）
    共用这一份，两边口径不许漂。"""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", _html.unescape(_html.unescape(text))).strip()
    m = _BEISEN_SSR_JD_RE.search(text)
    body = (m.group(2) if m else "").strip()
    cut = _BEISEN_SSR_FOOTER_RE.search(body)
    if cut:
        body = body[:cut.start()].strip()
    return body[:4000] if len(body) >= 60 else ""


# ============================================================================
# 老版 SSR「jobsTable」门户（路径式详情：/zpdetail/{id}、/job_show/{id}）——纯 httpx，零浏览器
# ============================================================================
# 与上面 theme2 CMS 门户的区别（2026-09-04 live 实测 21 个租户）：
#   theme2 CMS：列表是 <ul><li><a href="/{板块}xq?jobId={id}">，详情走 **查询串**。
#   jobsTable  ：列表是 <table class="jobsTable"><tr><td><a href="/zpdetail/{id}">，详情走 **路径**，
#                因此 _CMS_ROW_RE（强制 ?jobId=）一条都匹配不到 → 之前只能掉进浏览器 _fetch_ssr，
#                而 _fetch_ssr **只渲染首屏、从不翻页、也不报总数** → 21 个源集体
#                「reported_total=None＝不可判定」，抓全率对它们答不上来。
#
# 分母就印在页面上，不用猜（MvcPager 组件，raw HTML 里就有，无需浏览器）：
#   <div class="counts">共36条记录</div> ... <div class="tablefooter"> 当前第1/3页
# live 实测 11 个租户有分页条（223 → 1,190 条，漏抓 967），另 10 个只有一页故不渲染分页条。
#
# 已 live 确认的坑：
#   ① **每页行数逐租户不同**（实测 zpdetail 系 15 / job_show 系 10）→ 不写死，按首页行数推断
#      （同 avature.py「页长各租户不同」的既有处置）。
#   ② 表头列序逐租户不同（富瀚微＝职位名称/职位类型/工作地点/发布时间，科伦＝职位名称/职能/公司/
#      招聘人数/工作地点）→ 必须按表头建列映射，**不能按下标硬取**，否则「公司」会被写进 location。
#   ③ 岗位全名在 `<a title="…">` 属性里，`<a>` 内文本同样是全名但更易被样式标签切碎 → 优先取 title 属性。
#   ④ 与 theme2 同源的老坑：模板占位假岗藏在 <!-- --> 注释里，解析前必须先剥注释。
_SSR_TABLE_RE = re.compile(
    r"<table[^>]*class=\"[^\"]*(?:jobsTable|listtable)[^\"]*\"[^>]*>(.*?)</table>", re.S | re.I)
_SSR_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_SSR_TD_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.S | re.I)
# 表头单元格：多数租户用 <td>，百胜中国（yumchina，class=listtable）用 <thead><th>（2026-09-23 live）。
# 只认 <td> 时列映射为空 → 「工作地点 / 发布时间」整列丢失，2392 个岗全无地点。
_SSR_HEAD_CELL_RE = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)
_SSR_TITLE_ATTR_RE = re.compile(r"\btitle=\"([^\"]*)\"", re.I)
# 路径式详情锚点。与 _BEISEN_SSR_ANCHOR_JS 的第②类同一套路径名，保持两端口径一致。
# ⚠️ 分两步匹配（先整个 <a> 标签、再在属性串里找 href）而不是一条正则连着写：
# 实测租户把 `title=` 写在 **href 前面**（`<a title="…" href="/zpdetail/123">`），
# 一条正则只能捕获 href 之后的属性 → title 取不到 → 退回被样式标签切碎的内文本（坑③失效）。
_SSR_ANCHOR_TAG_RE = re.compile(r"<a\s(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.S | re.I)
_SSR_PATH_HREF_RE = re.compile(
    r"href=\"(?P<href>[^\"]*/(?:job[_-]?show|zpdetail|jobdetail|job[_-]?detail|positiondetail)"
    r"/\d{4,}[^\"]*)\"", re.I)
# 分页条（ASP.NET MvcPager）：总条数与「当前第 X/Y 页」分别在两个 div 里，必须分开匹配。
_SSR_COUNT_RE = re.compile(r"共\s*(\d{1,6})\s*条记录")
_SSR_CURPAGE_RE = re.compile(r"当前第\s*(\d{1,4})\s*/\s*(\d{1,4})\s*页")
_SSR_PAGED_MAX_PAGES = 200      # 安全上限（防翻不停）；命中即 fetch_complete=False。实测最长 32 页。
# 表头文案 → 规范字段。只认真正能用的三列，其余（发布时间/公司/招聘人数/操作）一律忽略。
_SSR_COL_ALIASES = (
    ("location", ("工作地点", "工作城市", "地点", "城市", "工作地区", "所在地")),
    ("job_type", ("职位类型", "职位类别", "职位分类", "职能", "岗位类别", "职位职能")),
    ("education", ("学历", "职位学历", "学历要求")),
    ("posted_at", ("发布时间", "发布日期", "更新时间", "刷新时间")),
)
_SSR_DATE_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})")


# 逐租户的入库口径（只对点名的租户生效，其余老版 SSR 租户行为不变）。
# 百胜中国（yumchina，2026-09-23）：列表 2392 个岗全是门店岗，① 地点只在列表的「工作地点」列里，
# 取不到地点的岗会被 /today 当成「城市未知」推给所有城市的用户；② 约 65% 发布于 2017~2023 年，
# 分不清常年在招还是没撤的旧岗。口径（代创始人拍板，可否决）：没有地点的不收；只收近 365 天发布的，
# 发布日期缺失 = 证明不了是近期的，也不收。筛是在「列表完整翻完」之后做的，fetch_complete 仍是 True、
# 分母仍是站点自报总数——规则 G 只看 coverage_complete=False，不会把它当成漏抓。
_SSR_TENANT_POLICY = {
    "yumchina.zhiye.com": {"require_location": True, "max_age_days": 365},
}


def _ssr_policy_allows(job: dict, policy: Optional[dict], today=None) -> bool:
    """按租户口径判这一行收不收。无口径 → 一律收（老租户行为不变）。"""
    if not policy:
        return True
    if policy.get("require_location") and not (job.get("location") or "").strip():
        return False
    max_age = policy.get("max_age_days")
    if max_age:
        dm = _SSR_DATE_RE.search(str(job.get("posted_at") or ""))
        if not dm:
            return False
        try:
            posted = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            return False
        today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if (today - posted).days > int(max_age):
            return False
    return True


def _ssr_policy_retire_before(policy: Optional[dict], today=None) -> Optional[date]:
    """租户口径里有 max_age_days 时，库里「发布日早于这一天」的岗已超出口径（与 _ssr_policy_allows 同一边界：
    正好 max_age_days 天前发布的仍收）。抓取端只能不再收新的，已在库里的由 run.py 收抓后按这一天下架。"""
    max_age = (policy or {}).get("max_age_days")
    if not max_age:
        return None
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return today - timedelta(days=int(max_age))


def _ssr_normalize_job_url(origin: str, href: str) -> str:
    """列表锚点 → 稳定的逐岗 jd_url：**身份只在 path 里**（/zpdetail/{id}），query 一律剥掉。

    ⚠️ 与 theme2 CMS 的坑②同源、但更毒：这类门户把**列表当前页号**回传进详情链接
    （联易融实测 `/zpdetail/390725089?PageIndex=1`），于是
      · 同一个岗从第 1 页和第 3 页抓到 → 算出两个不同的 canonical_jd_url → 库里同岗多行；
      · 与库里已有的干净 URL 也对不上 → 老行在 list-absence 里变「缺席」→ 撤岗 + 次日 purge 永久删。
    canonicalize_jd_url 只去 utm_ 类 tracking 参数，PageIndex 会被原样保留，挡不住这个。
    2026-09-04 live 实测：不剥的话联易融 13 个在招岗会被全量误判撤岗并插 13 行重复。
    """
    if not href:
        return ""
    href = _html.unescape(href).strip()
    path = href.split("?", 1)[0].split("#", 1)[0]
    if not path:
        return ""
    return path if path.startswith(("http://", "https://")) else urljoin((origin or "") + "/", path)


def _ssr_cell_text(attrs: str, body: str) -> str:
    """单元格取值：优先 title 属性（长文本不会被截断），否则取去标签后的文本。"""
    m = _SSR_TITLE_ATTR_RE.search(attrs or "")
    if m and m.group(1).strip():
        return _cms_text(m.group(1))
    return _cms_text(body)


def _ssr_column_map(table_html: str):
    """按表头行建「列下标 → 规范字段」映射（列序逐租户不同，见坑②）。"""
    col_map = {}
    for row in _SSR_TR_RE.findall(table_html):
        cells = [_ssr_cell_text(a, b) for a, b in _SSR_HEAD_CELL_RE.findall(row)]
        if not cells or not any("职位名称" in c or "岗位名称" in c for c in cells):
            continue
        for idx, cell in enumerate(cells):
            for field, names in _SSR_COL_ALIASES:
                if field in col_map.values():
                    continue
                if any(n in cell for n in names):
                    col_map[idx] = field
                    break
        break
    return col_map


def _ssr_parse_list(html_text: str, origin: str):
    """解析 jobsTable 列表页 → (rows, total, last_page)。

    total / last_page 取自页面分页条（站点自报，不是我们估的）；没有分页条＝只有一页，返回 None。
    rows 为 [{title, jd_url, location, job_type, education}]，jd_url 已拼成绝对地址。
    """
    body = _CMS_COMMENT_RE.sub(" ", html_text or "")       # 坑④：先剥注释里的模板占位假岗
    table_m = _SSR_TABLE_RE.search(body)
    table = table_m.group(1) if table_m else body
    col_map = _ssr_column_map(table)
    rows, seen = [], set()
    for tr in _SSR_TR_RE.findall(table):
        a = href_m = None
        for cand in _SSR_ANCHOR_TAG_RE.finditer(tr):
            href_m = _SSR_PATH_HREF_RE.search(cand.group("attrs"))
            if href_m:
                a = cand
                break
        if not a:
            continue
        title = _ssr_cell_text(a.group("attrs"), a.group("body"))   # 坑③：优先 <a title="…">
        jd_url = _ssr_normalize_job_url(origin, href_m.group("href"))
        if not title or jd_url in seen:
            continue
        seen.add(jd_url)
        row = {"title": title, "jd_url": jd_url,
               "location": None, "job_type": None, "education": None, "posted_at": None}
        cells = _SSR_TD_RE.findall(tr)
        for idx, (attrs, cell_body) in enumerate(cells):
            field = col_map.get(idx)
            if not field or row.get(field):
                continue
            value = _ssr_cell_text(attrs, cell_body)
            if value and value != title:
                if field == "education":
                    value = _cms_education(value)
                elif field == "posted_at":
                    dm = _SSR_DATE_RE.search(value)
                    value = "%s-%02d-%02d" % (dm.group(1), int(dm.group(2)), int(dm.group(3))) if dm else None
                if value:
                    row[field] = value
        rows.append(row)
    flat = re.sub(r"\s+", " ", body)
    cm, pm = _SSR_COUNT_RE.search(flat), _SSR_CURPAGE_RE.search(flat)
    total = int(cm.group(1)) if cm else None
    last_page = int(pm.group(2)) if pm else None
    return rows, total, last_page


# ============================================================================
# 老版 CMS Portal 门户（北森 theme2 SSR）——纯 httpx，零浏览器
# ============================================================================
# 与新版 SPA 租户的区别（2026-08-27 live 实测 smics.zhiye.com=中芯国际 563 岗）：
#   新版：列表页是 React，HTML 里抽得到 PortalId，岗位走 POST GetJobAdPageList（→ _httpx_fetch）。
#   老版：列表页 SSR 直出 <li><a href="/{板块}xq?jobId={id}&jc=N">，**没有 PortalId、没有那个接口**
#         → _httpx_fetch 返回 None → 旧代码只能掉进浏览器慢车道（慢，且 _fetch_ssr 不翻页、只取首屏）。
# 识别一律按**响应特征**（抽不到 PortalId + 列表页直出 jobId 锚点），不按域名/租户名写白名单。
#
# 已 live 确认的坑：
#   ① 服务端**无条件 gzip**：httpx 自动解压（curl 要 --compressed），否则拿到乱码会误判空页。
#   ② 列表锚点尾部带**筛选态回传参数** `&c=&p=1^-1,3^-1&ky=`，随用户当前筛选变化 →
#      必须只留 jobId(+jc) 两个身份参数，否则同一岗算出多个 canonical_jd_url = 库里同岗多行。
#   ③ 翻页越界仍返 **HTTP 200 + 完整页面骨架**（约 19KB）→ 只能靠「页内锚点数 == 0」判终止，
#      绝不能靠状态码。末页页数各板块不同（实测社招 30 / 校招 25 / 海外 3）且随在招量变，不写死。
#   ④ 模板占位岗藏在 HTML 注释里（href="" 的假行，如「光罩OPC工程师/大专/北京市海淀区」重复多条）
#      → 解析前必须先剥掉 <!-- --> ，否则整页混进假岗。
#   ⑤ 列表里**长标题被服务端截断**（25 字 + "..."，实测约 10% 的行），详情页 <h2> 才是全名 →
#      截断行必须优先补详情，否则「日更快车道写截断名 / 夜间富化写全名」来回抖。
_CMS_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# 岗位行：<li><a href="…?jobId=…">…</a></li>。**必须锚在 <li> 上**——科伦(kelun) 这类老版 CMS
# 的「热招职位」侧栏也有裸 <a href="/social_show?jobId=…">，而它的主列表是 <table><tr><td>，
# 不加 <li> 约束会只捞到侧栏 10 条却自称抓全（fetch_complete=True → list-absence 误杀在招岗）。
# ⚠️ 详情链接不一定在 href 上：建发(chinacdc) 这类租户写成
#     <li><a href="javascript:void(0)" data-url="/zwxq?jobId=561284174">…</a></li>
#   —— href 是 javascript:void(0)，真链接在 **data-url**。只认 href 会一条都抓不到、
#   整源判「0 岗」丢弃（2026-08-27 live 实测建发 10 条/页全被漏掉）。故两个属性都认。
_CMS_ROW_RE = re.compile(
    r"<li[^>]*>\s*<a\s[^>]*(?:href|data-url)=\"(?P<href>[^\"]*[?&](?:jobId|jobAdId|adId)=[^\"]+)\"[^>]*>(?P<body>.*?)</a>",
    re.S | re.I)
_CMS_SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S | re.I)
# 卡片式模板的标志：标题包在 <dd> 里（见下面「卡片式 CMS 门户」一节）。theme2 的行里没有它。
_CMS_CARD_MARK_RE = re.compile(r"<dd[^>]*>", re.I)
_CMS_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.S | re.I)
_CMS_PAGE_LINK_RE = re.compile(r"PageIndex=(\d{1,4})", re.I)
_CMS_ID_RE = re.compile(r"[?&](jobId|jobAdId|adId)=([^&#]+)", re.I)
_CMS_JC_RE = re.compile(r"[?&]jc=([^&#]+)", re.I)
_CMS_PORTAL_ID_RE = re.compile(r'PortalId"\s*:\s*"([0-9a-fA-F-]+)"')
# 详情页（同一套 theme2 模板，中英文两版只有 label 不同）：
#   标题 <div class="xqtitle …"><h2>岗位名</h2>
#   字段 <li><span>职位学历：</span><b>硕士</b></li> / <li><span>Education:</span><b>Bachelor</b></li>
#   正文 <h3>职位描述</h3><div class="xqm">…</div><h3>职位要求</h3><div class="xqm">…</div>
_CMS_DETAIL_TITLE_RE = re.compile(
    r"<div[^>]*class=\"[^\"]*xqtitle[^\"]*\"[^>]*>.*?<h2[^>]*>(.*?)</h2>", re.S | re.I)
_CMS_DETAIL_FIELD_RE = re.compile(
    r"<li[^>]*>\s*<span[^>]*>(.*?)</span>\s*<b[^>]*>(.*?)</b>", re.S | re.I)
_CMS_DETAIL_SECTION_RE = re.compile(
    r"<h3[^>]*>(.*?)</h3>\s*<div[^>]*class=\"xqm\"[^>]*>(.*?)</div>", re.S | re.I)
_CMS_CITY_RE = re.compile(r"[一-龥]{2,}[省市区县]")
_CMS_ACTION_RE = re.compile(r"查看职位|查看详情|立即申请|投递|view detail|apply", re.I)
_CMS_TRUNCATED_RE = re.compile(r"(\.{3}|…)\s*$")

_CMS_PAGE_SIZE = 10       # theme2 列表固定每页 10 条（短页 = 末页的判据）
_CMS_MAX_PAGES = 200      # 安全上限（防接口异常翻不停）；命中即 fetch_complete=False
_CMS_DETAIL_CAP = 800     # 逐岗补正文默认上限（详情 ~0.13s/个，中芯最大板块 293 岗 ≈ 38s）
_CMS_TITLE_REPAIR_CAP = 120   # 即使 CRAWL_DETAIL_CAP=0（日更快车道跳过富化），仍补这么多条截断标题
# 正文入库下限。刻意低于 count_valid_active_jobs() 的 60 字「有效在招」线：这里是从
# <h3>+<div class="xqm"> **结构块**里取的，短 ≠ 噪声（中芯校招 6 个环保安全岗 JD 本来就只有 50 来字），
# 存下来用户至少看得见、匹配器也读得到；「够不够 60 字算有效在招」由计数口径在读时把关，不在这一层砍。
_CMS_SUMMARY_MIN = 20

# 表头文本 → 列语义。**从最具体到最泛**匹配：「职位分类」必须在「职位」之前命中，
# 否则含「职位」二字的表头会被一律当成标题列。
_CMS_COL_KEYWORDS = (
    ("职位名称", "title"), ("岗位名称", "title"), ("job title", "title"), ("job name", "title"),
    ("position name", "title"),
    ("职位分类", "category"), ("职位类别", "category"), ("岗位类别", "category"), ("职能", "category"),
    ("job category", "category"), ("category", "category"),
    ("职位学历", "education"), ("学历", "education"), ("education", "education"), ("degree", "education"),
    ("工作地点", "location"), ("工作城市", "location"), ("work place", "location"),
    ("location", "location"), ("城市", "location"), ("地点", "location"),
    ("操作", "action"), ("view", "action"),
    ("职位", "title"), ("岗位", "title"), ("position", "title"),
)
# 学历档次从低到高。列表常写「硕士、博士」（= 硕士及以上），并列时取**最低**档——
# 招聘方给的是门槛下限，取高档会把本来符合条件的人筛掉。
_CMS_EDU_ORDER = ("不限", "大专", "本科", "硕士", "博士")


def _cms_text(fragment: Optional[str]) -> str:
    """HTML 片段 → 纯文本（去标签 + 反转义 + 折叠空白）。"""
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(_html.unescape(text))
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _cms_education(value: Optional[str]) -> Optional[str]:
    """列表/详情的『职位学历』归一到 normalizer 口径（博士/硕士/本科/大专/不限）。
    并列多档取最低档（见 _CMS_EDU_ORDER）；非学历值（如误填的「社招」）返回 None。"""
    raw = (value or "").strip()
    if not raw:
        return None
    hits = []
    for piece in re.split(r"[、,，/|]+", raw):
        level = normalizer.extract_education(piece)
        if level in _CMS_EDU_ORDER:
            hits.append(level)
    if hits:
        return min(hits, key=_CMS_EDU_ORDER.index)
    return normalizer.extract_education(raw)


def _cms_normalize_job_url(origin: str, href: str) -> str:
    """列表锚点 → 稳定的逐岗 jd_url：只保留 jobId(+jc) 两个身份参数。

    原始锚点形如 `/socialxq?jobId=390609112&jc=1&c=&p=1^-1,3^-1&ky=`——尾部 c/p/ky 是**筛选态回传**，
    随用户当前筛选条件变化；不剥掉的话同一个岗在不同筛选态下会算出不同 canonical_jd_url
    （canonicalize_jd_url 只去 utm_ 类 tracking 参数，c/p/ky 会被原样保留）→ 库里出现重复行。"""
    if not href:
        return ""
    href = _html.unescape(href).strip()
    m = _CMS_ID_RE.search(href)
    if not m:
        return ""
    path = href.split("?", 1)[0].split("#", 1)[0]
    query = f"{m.group(1)}={m.group(2)}"
    jc = _CMS_JC_RE.search(href)
    if jc and jc.group(1).strip():
        query += f"&jc={jc.group(1).strip()}"
    base = path if path.startswith(("http://", "https://")) else urljoin((origin or "") + "/", path)
    return f"{base}?{query}"


def _cms_column_map(html_text: str):
    """表头 <th> → {列下标: 列语义}。老版 CMS 各租户列序/列数不同，按表头对齐比按下标硬编码稳。"""
    headers = [_cms_text(h) for h in _CMS_TH_RE.findall(html_text)]
    col_map = {}
    for idx, head in enumerate(headers):
        low = head.lower()
        for keyword, field in _CMS_COL_KEYWORDS:
            if keyword in low:
                col_map[idx] = field
                break
    return col_map, len(headers)


def _cms_row_fields(cells: List[str], col_map: dict, header_count: int) -> dict:
    """一行的若干 <span> 文本 → {title, location, education, category}。
    表头对得上就按表头映射；对不上（表头缺失/列数不符的租户）退回按**取值特征**认字段。"""
    out = {"title": "", "location": None, "education": None, "category": None}
    if col_map and header_count == len(cells):
        for idx, cell in enumerate(cells):
            field = col_map.get(idx)
            if field and field != "action" and cell:
                out[field] = cell
    if out["title"]:
        return out
    rest = []
    for cell in cells:
        if not cell or _CMS_ACTION_RE.search(cell):
            continue
        if out["education"] is None and _cms_education(cell):
            out["education"] = cell
            continue
        if out["location"] is None and _CMS_CITY_RE.search(cell) and len(cell) <= 20:
            out["location"] = cell
            continue
        rest.append(cell)
    out["title"] = max(rest, key=len) if rest else ""
    return out


def _cms_parse_list(html_text: str, origin: str):
    """老版 CMS 列表页 HTML → (rows, last_page)。

    rows = [{title, jd_url, location, education, category, title_truncated}]，按 jd_url 去重。
    last_page = 分页条里出现过的最大 PageIndex（站点自报的总页数，实测每页都带真末页号）；
    抽不到返回 None（交给 paginate_all 用「空页/短页」兜底判末页）。"""
    body = _CMS_COMMENT_RE.sub(" ", html_text or "")   # 先剥注释：模板占位假岗藏在里面
    col_map, header_count = _cms_column_map(body)
    rows, seen = [], set()
    for m in _CMS_ROW_RE.finditer(body):
        jd_url = _cms_normalize_job_url(origin, m.group("href"))
        if not jd_url or jd_url in seen:
            continue
        cells = [_cms_text(s) for s in _CMS_SPAN_RE.findall(m.group("body"))]
        if not cells and _CMS_CARD_MARK_RE.search(m.group("body")):
            # 没有 <span> 的行有两种，必须分开：真 theme2 的纯文本锚点，和**卡片式模板**
            # （标题在 <dd> 里，<a> 体内还塞着地点/部门/日期和整段 JD）。后者若走下面
            # 「整个 <a> 文本当标题」的兜底，就会把「标题+地点+部门+日期+整段JD」当成标题——
            # JD 短的行还能过 3~120 字门，于是**悄悄**入库一批垃圾标题、还自称 success。
            # 2026-09-18 实测方太 /intern 6 行里正是有 3 行这么进来的（另外 3 行 JD 长、被长度门丢掉，
            # 于是这源看着像「只有 3 个岗」）。判据＝<a> 体里有 <dd> → 本函数弃权，交 _card_parse_list。
            # 全集实测：能被 _CMS_ROW_RE 匹到行的 7 个源里，「<dd> 与 <span> 同时出现」的 0 个，
            # 4 个正统 theme2 源全部只有 <span> —— 这条弃权对既有租户零影响（全集回归复核过）。
            continue
        fields = _cms_row_fields(cells, col_map, header_count) if cells else {
            "title": _cms_text(m.group("body")), "location": None, "education": None, "category": None}
        title = (fields.get("title") or "").strip()
        if not (3 <= len(title) <= 120):   # 太短/太长的不是岗位名（登录、导航等）
            continue
        seen.add(jd_url)
        rows.append({
            "title": title,
            "jd_url": jd_url,
            "location": fields.get("location") or None,
            "education": _cms_education(fields.get("education")),
            # 学历列被租户误填成招聘类型（中芯社招板块实测有「社招」）→ 当 job_type 用，别丢
            "job_type": (fields.get("education")
                         if normalizer.is_recruitment_type(fields.get("education")) else None),
            "title_truncated": bool(_CMS_TRUNCATED_RE.search(title)),
        })
    if not rows:
        rows = _cms_parse_position_items(body, origin)
    pages = [int(p) for p in _CMS_PAGE_LINK_RE.findall(body)]
    return rows, (max(pages) if pages else None)


# 「position-item」模板（2026-09-23，药石科技 pharmablock.zhiye.com）：同属老版 CMS（无 PortalId、?PageIndex= 翻页、
# /zwxq?jobId= 详情），但岗位行不是 <li><a>，而是
#   <div class="position-item"><div class="position-name"><a href="/zwxq?jobId=…">标题</a></div>
#     <div class="position-info"><span class="city">江苏省-南京市</span>…<span>2024-09-14</span></div>
#     <div class="position-desc"><h4>工作内容</h4><p>整段 JD…</p></div>…
# _CMS_ROW_RE 强制锚 <li>（防「热招职位」侧栏裸锚点冒充主列表，见上），于是这类页 0 行、整源静默 0 岗。
# 这里只在 <li> 一行都没匹到时才启用，且锚在 position-item → position-name → jobId 这条三层结构上，
# 侧栏裸 <a> 进不来；既有租户走不到这条分支（全集核过：近 4 天 0 产出的 5 个北森源里没有一个是这种标记）。
_CMS_POSITION_ITEM_SPLIT_RE = re.compile(r"<div[^>]*class=\"position-item\"[^>]*>", re.I)
_CMS_POSITION_NAME_RE = re.compile(
    r"<div[^>]*class=\"position-name[^\"]*\"[^>]*>\s*<a\s[^>]*href=\"(?P<href>[^\"]*[?&](?:jobId|jobAdId|adId)=[^\"]+)\"[^>]*>(?P<title>.*?)</a>",
    re.S | re.I)
_CMS_POSITION_CITY_RE = re.compile(r"<span[^>]*class=\"city[^\"]*\"[^>]*>(.*?)</span>", re.S | re.I)
_CMS_POSITION_DATE_RE = re.compile(r"<span[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</span>")
_CMS_POSITION_DESC_RE = re.compile(r"<div[^>]*class=\"position-desc\"[^>]*>(.*?)</div>", re.S | re.I)


def _cms_parse_position_items(body: str, origin: str) -> list:
    """「position-item」模板的列表行 → 与 _cms_parse_list 同形的 rows（另带列表自带的 summary / posted_at）。"""
    rows, seen = [], set()
    for block in _CMS_POSITION_ITEM_SPLIT_RE.split(body)[1:]:
        m = _CMS_POSITION_NAME_RE.search(block)
        if not m:
            continue
        jd_url = _cms_normalize_job_url(origin, m.group("href"))
        title = _cms_text(m.group("title")).strip()
        if not jd_url or jd_url in seen or not (3 <= len(title) <= 120):
            continue
        city = _CMS_POSITION_CITY_RE.search(block)
        date = _CMS_POSITION_DATE_RE.search(block)
        desc = "\n".join(t for t in (_cms_text(d) for d in _CMS_POSITION_DESC_RE.findall(block)) if t)
        seen.add(jd_url)
        rows.append({
            "title": title,
            "jd_url": jd_url,
            "location": (_cms_text(city.group(1)) or None) if city else None,
            "education": None,
            "job_type": None,
            "summary": desc or None,
            "posted_at": date.group(1) if date else None,
            "title_truncated": bool(_CMS_TRUNCATED_RE.search(title)),
        })
    return rows


def _cms_parse_detail(html_text: str) -> dict:
    """老版 CMS 详情页 HTML → {title, summary, education, job_type, location}。

    正文只取 <h3>小标题</h3> + <div class="xqm">正文</div> 这些块，**不做「某关键词之后全要」的整页切片**——
    该模板正文后面紧跟着几千字《职位申请知情同意书》，整页切片会把隐私条款当岗位正文写进库。
    中英双版同模板（社招/校招是「职位描述/职位要求」，海外板块是「job description/Job requirements」），
    故按结构取而不是按中文关键词找。"""
    out = {"title": "", "summary": None, "education": None, "job_type": None, "location": None}
    if not html_text:
        return out
    cleaned = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_text, flags=re.S | re.I)
    cleaned = _CMS_COMMENT_RE.sub(" ", cleaned)

    m = _CMS_DETAIL_TITLE_RE.search(cleaned)
    if m:
        out["title"] = _cms_text(m.group(1))

    for label_raw, value_raw in _CMS_DETAIL_FIELD_RE.findall(cleaned):
        label = _cms_text(label_raw).rstrip("：:").strip().lower()
        value = _cms_text(value_raw)
        if not value:
            continue
        if any(k in label for k in ("学历", "education", "degree")):
            out["education"] = _cms_education(value)
        elif any(k in label for k in ("工作地点", "工作城市", "location", "work place")):
            out["location"] = value
        elif any(k in label for k in ("工作类型", "job type", "employment")):
            out["job_type"] = value

    parts = []
    for head_raw, body_raw in _CMS_DETAIL_SECTION_RE.findall(cleaned):
        head, body = _cms_text(head_raw), _cms_text(body_raw)
        if not body:
            continue
        parts.append(f"【{head}】\n{body}" if head else body)
    summary = "\n".join(parts).strip()
    if len(summary) >= _CMS_SUMMARY_MIN:
        out["summary"] = summary[:4000]
    return out


# ============================================================================
# 卡片式 CMS 门户（列表卡把整段 JD 塞进 <a> 里）——纯 httpx，零浏览器
# ============================================================================
# **不是新网关，是同一套 CMS 换了列表卡模板**（2026-09-18 逐项 live 对拍，方太 fotile.zhiye.com）：
#   · 静态资源同一个 `cmsportal/<租户数字 id>/` 体系（方太 10204200，老版 CMS 华安 10111900）；
#   · 翻页同为 `?PageIndex=N`，详情身份同为 `?jobId=<数字>`；
#   · 限流同为北森按 IP 的 `X-RateLimit-Limit-<host><ip>-second: 50`。
#   ⚠️ 响应头 `X-PAAS-DEBUG-GENERAL-SITE` 看着像代际标记，**不能当判据**：方太是
#      web-custom-new-zhiye-com，而同为该值的京东方却是新版 SPA（抽得到 PortalId）；
#      华安/中国人寿/联易融是 web-new-zhiye-com、中芯是 web-vip-new-zhiye-com ——
#      它区分的是托管档位，不是门户形态。识别只能按**响应结构**，和本文件其它分支同一条纪律。
# 唯一的差别在列表卡：
#   theme2 CMS：<li><a href="…?jobId=…"><span>字段</span>…</a>            ← 字段在 <span>，标题短
#   本类      ：<li><a href="…?jobId=…"><dd>标题</dd><ol>地点｜部门｜日期</ol>
#                                        <dl><p>整段 JD</p></dl></a>       ← 标题在 <dd>，<a> 里塞着几千字
# 后果是**两个既有解析器都判它「没有岗位」，而且都不报错**：
#   · _cms_parse_list 找不到 <span> → 退回「整个 <a> 文本当标题」→ 长度几千字 → 被 3~120 字门丢光 → 0 行；
#   · 浏览器 _BEISEN_SSR_ANCHOR_JS 的 `name.length<=60` 门同理 → 0 个锚点 → raise
#     「beisen: SSR 列表页无 jobId/adId 锚点」——同事看到的就是这条。
# 因此本分支**只在前面两条老版通道都返回 None 之后**才试，且判据是「<a> 里有 <dd>」这一条结构特征：
# 没有 <dd> 一律返回 None 原样交回旧流程，故对既有租户零影响（全集回归见 docs/crawler-adapter-notes.md）。
_CARD_TITLE_RE = re.compile(r"<dd[^>]*>(.*?)</dd>", re.S | re.I)
_CARD_META_RE = re.compile(r"<ol[^>]*>(.*?)</ol>", re.S | re.I)
_CARD_BODY_RE = re.compile(r"<dl[^>]*>(.*?)</dl>", re.S | re.I)
# 元信息分隔符是**全角竖线** U+FF5C（`地点｜部门｜日期`），半角 | 一并认着兜底。
_CARD_META_SEP_RE = re.compile(r"[｜|]")
_CARD_DATE_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})")
# 地点被服务端按显示宽度截断，实测三种写法：`浙江省-宁波市-...` / `内蒙古自治区,...` / `广西壮族自治区...`
# （231 行里 51 行截断）。必须剥掉尾巴：不剥的话同一个城市会出现两种写法，而夜间富化补的是完整地点
# → location 不在 _PRESERVE_IF_EMPTY 里 → 快车道与富化天天来回刷。剥完 `浙江省-宁波市` 与详情页的
# `浙江省-宁波市-慈溪市` 经 normalizer.clean_location 都归一成「宁波」，两端一致、无抖动。
_CARD_TRUNC_TAIL_RE = re.compile(r"[\s\-,，、]*(?:\.{3,}|…+)\s*$")
# 地点段的识别一律按**取值特征**（同 _cms_row_fields 的兜底哲学），不按下标——下标只对当前这一家成立。
# 「全国」不带省市区县后缀，是实测出现过的唯一例外（231 行里 3 行），显式收进来；
# 其余认不出的段一律留 None：**漏判一个地点无害**（normalizer 照常入库），
# 而按下标硬取会把「万州办事处」这种部门名写成地点（clean_location 不拦非地名，实测原样返回）。
_CARD_NATIONWIDE = ("全国",)
_CARD_MAX_PAGES = 200      # 安全上限（防翻不停）；命中即 fetch_complete=False
_CARD_DETAIL_CAP = 800     # 逐岗补正文默认上限（同 theme2 CMS 口径）
_CARD_REPAIR_CAP = 120     # 即使 CRAWL_DETAIL_CAP=0，仍补这么多条「列表值残缺」的行（见 _card_needs_repair）
# 详情页段标题里出现这些词 = 任职要求段。**要求段必须排在职责段前面**（同 sf_express_campus 的
# 既有处置）：normalizer 存库的 full_summary 走 clean_summary 默认 max_chars=400，grad_class 读的
# 就是这 400 字，而站点自己的段序恒为「工作职责, 任职要求」（2026-09-18 抽 74 个详情页 74/74）——
# 职责段动辄几百字，不换序要求段会被整段截掉。
# 诚实边界：方太当前 231 个岗里只有 1 个能抽出届别硬信号（社招板块的「2024届阳光生」），
# 且它正文短、换不换序都抽得到 —— 也就是说**这条换序在方太身上目前没有可量到的收益**，
# 留着是因为 400 字截断对「职责长、要求里才写届别」的岗必然生效（sf_express_campus 实测 120/120）。
# 换序确实改变了用户读到的那 400 字（实测 231 个岗的 summary 普遍顶到 400 上限）：先要求后职责。
_CARD_REQUIREMENT_HEADS = ("要求", "资格", "条件", "requirement", "qualification")
# 板块路径 → 租户自报的招聘类别。这是「精准路由」的一部分：本类的 jd_url 是
# `/job_show?jobId=…`，**不带任何板块标记**，而 recruitmentCategory 的层4 只认 url 路径 →
# 不带这个声明，/campus /intern 的岗会被兜底成社招（同 BeisenAdapter._map 搬 Category 的道理）。
# ⚠️ 实习必须排在校招**前面**：`/campus/internship` 这种路径两边都命中，实习是更具体的那个
#    （sourceDeclaredCategory 内部也是实习优先，两边口径保持一致）。
_CARD_BOARD_JOB_TYPES = (
    (("intern", "shixi", "实习"), "实习"),
    (("campus", "school", "xiaozhao", "校园", "校招"), "校园招聘"),
    (("social", "shehui", "experienced", "社会", "社招"), "社会招聘"),
)


def _card_board_job_type(path: str) -> Optional[str]:
    """列表页路径 → 租户自报的招聘类别（认不出返回 None，绝不猜）。"""
    low = (path or "").lower()
    for tokens, declared in _CARD_BOARD_JOB_TYPES:
        if any(tok in low for tok in tokens):
            return declared
    return None


def _card_meta_fields(meta_text: str):
    """`地点｜部门｜日期` → (location, posted_at)。按取值特征认，认不出的留 None。"""
    location = posted_at = None
    for seg in _CARD_META_SEP_RE.split(meta_text or ""):
        seg = seg.strip()
        if not seg:
            continue
        date_m = _CARD_DATE_RE.search(seg)
        if date_m and posted_at is None:
            posted_at = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
            continue
        if location is None and (_CMS_CITY_RE.search(seg) or seg in _CARD_NATIONWIDE):
            location = _CARD_TRUNC_TAIL_RE.sub("", seg).strip() or None
    return location, posted_at


def _card_parse_list(html_text: str, origin: str, job_type: Optional[str] = None):
    """卡片式列表页 HTML → (rows, last_page)。

    rows = [{title, jd_url, location, posted_at, job_type, summary}]，按 jd_url 去重。
    last_page = 分页条里出现过的最大 PageIndex（站点自报；抽不到返回 None，交 paginate_all 兜底）。
    没有一行带 <dd> 标题 → 返回 ([], last_page)，调用方据此判「不是这种门户」。
    """
    body = _CMS_COMMENT_RE.sub(" ", html_text or "")   # 同 theme2：模板占位假岗藏在注释里
    rows, seen = [], set()
    for m in _CMS_ROW_RE.finditer(body):
        card = m.group("body")
        title_m = _CARD_TITLE_RE.search(card)
        if not title_m:            # 没有 <dd> = 不是卡片式模板 → 一行都不认，原样交回旧分支
            continue
        title = _cms_text(title_m.group(1))
        if not (3 <= len(title) <= 120):
            continue
        jd_url = _cms_normalize_job_url(origin, m.group("href"))
        if not jd_url or jd_url in seen:
            continue
        seen.add(jd_url)
        meta_m = _CARD_META_RE.search(card)
        location, posted_at = _card_meta_fields(_cms_text(meta_m.group(1)) if meta_m else "")
        rows.append({
            "title": title,
            "jd_url": jd_url,
            "location": location,
            "posted_at": posted_at,
            "job_type": job_type,
            # ⚠️ 列表卡里那段 JD **只有职责、没有任职要求**，与详情页补出来的不是同一段内容，
            # 所以这里**刻意不把它当 summary**（与 theme2 CMS 完全同一处置：列表不出 summary，
            # 只由 _card_fill_details 从详情页写）。否则快车道（CRAWL_DETAIL_CAP=0）会用「半截职责」
            # 盖掉夜间富化写好的完整正文 —— summary 在 jobs_db._PRESERVE_IF_EMPTY 里，**空值才保护旧值**，
            # 写个非空的半截正文正好把这层保护绕过去，变成 CLAUDE.md 立碑的「快车道与富化天天来回抖」。
            # 代价是首抓当天是薄卡，等夜间 enrich 补正文（同中芯/科伦/启德，既有且可接受的形态）。
        })
    pages = [int(p) for p in _CMS_PAGE_LINK_RE.findall(body)]
    return rows, (max(pages) if pages else None)


_CARD_DETAIL_ITEM_RE = re.compile(
    r"<li\s[^>]*class=\"(?P<cls>[^\"]*)\"[^>]*>(?P<body>.*?)</li>", re.S | re.I)


def _card_parse_detail(html_text: str) -> dict:
    """卡片式详情页 HTML → {title, summary, location, posted_at}。

    模板：<li class="t">全名</li><li class="n">面议</li><li class="n">全职｜地点｜日期</li>
          <li class="c"><dd>段标题</dd><dl><p>正文</p></dl></li> × N
    只取 <li class="c"> 这些**结构块**当正文，不做「某关键词之后全要」的整页切片（同 theme2 的处置）。
    """
    out = {"title": "", "summary": None, "location": None, "posted_at": None}
    if not html_text:
        return out
    cleaned = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_text, flags=re.S | re.I)
    cleaned = _CMS_COMMENT_RE.sub(" ", cleaned)

    reqs, rest = [], []
    for m in _CARD_DETAIL_ITEM_RE.finditer(cleaned):
        cls = set((m.group("cls") or "").split())
        block = m.group("body")
        if "t" in cls and not out["title"]:
            out["title"] = _cms_text(block)
            continue
        if "n" in cls:
            location, posted_at = _card_meta_fields(_cms_text(block))
            out["location"] = out["location"] or location
            out["posted_at"] = out["posted_at"] or posted_at
            continue
        if "c" not in cls:
            continue
        head_m, body_m = _CARD_TITLE_RE.search(block), _CARD_BODY_RE.search(block)
        head = _cms_text(head_m.group(1)) if head_m else ""
        text = _cms_text(body_m.group(1)) if body_m else ""
        if not text:
            continue
        chunk = f"【{head}】\n{text}" if head else text
        low = head.lower()
        (reqs if any(k in low for k in _CARD_REQUIREMENT_HEADS) else rest).append(chunk)

    summary = "\n".join(reqs + rest).strip()   # 任职要求在前，理由见 _CARD_REQUIREMENT_HEADS
    if len(summary) >= _CMS_SUMMARY_MIN:
        out["summary"] = summary[:4000]
    return out


def _get_page_with_retry(cli, url: str, attempts: int = _PAGE_RETRIES):
    """GET 一页列表，失败退避重试后仍失败则上抛（交给 paginate_all 的首页/后续页语义处置）。

    ⚠️ 与 _post_page_with_retry 同一个理由：北森按 **IP** 限流
    （实测方太响应头 `X-RateLimit-Limit-<host><ip>-second: 50`，与新版接口是同一套闸），
    一次抖动就 break 会把整源截断成半页。3 次 × 0.6s 递增退避足够穿过秒级限流窗口。
    """
    last = None
    for attempt in range(max(1, attempts)):
        try:
            resp = cli.get(url)
            resp.raise_for_status()
            return resp
        except Exception as exc:     # noqa: BLE001 — 原因原样带给上层，见下面 raise
            last = exc
        if attempt + 1 < max(1, attempts):
            time.sleep(_PAGE_BACKOFF_SECONDS * (attempt + 1))
    raise last


def _post_page_with_retry(cli, endpoints, ep_ok, body, attempts=_PAGE_RETRIES):
    """POST 一页 GetJobAdPageList，失败退避重试。返回 (payload|None, 命中的端点)。

    ⚠️ 为什么必须重试：北森按 **IP** 限流（响应头 `X-RateLimit-Limit-<host><ip>-second: 50`）。
    2026-09-04 把单源上限从 600 抬到 8000 之后，我们对 *.zhiye.com 这一个 CDN 的请求量翻了十几倍，
    偶发被掐成了常态；而旧代码一页拿不到就 `break`，一次抖动就把整源截断——当天线上实测
    上海医药 230→50、三一 135→50、新奥 220→118（同一轮里另有 26 个源多抓了 3.1 万个岗，
    方向是对的，但这 461 个岗的回归是自己造的，得补上）。

    端点大小写两试（/api/Jobad/ 与 /api/JobAd/）只在**首次**发生，命中后固定，不重复试错。
    """
    rounds = max(1, attempts)
    # 最后一次失败的原因：抛异常（网络 / 解析）或回了没有 Data 列表的响应（限流体就是这种，不抛）。
    # 调用方拿到 None 就停止翻页——不记下来，停在哪、为什么停都看不见。
    last_problem = None
    for attempt in range(rounds):
        for ep in ((ep_ok,) if ep_ok else endpoints):
            try:
                cand = cli.post(ep, json=body, headers={"Content-Type": "application/json"}).json()
            except Exception as exc:
                last_problem = exc_brief(exc)
                continue
            if isinstance(cand, dict) and isinstance(cand.get("Data"), list):
                return cand, ep
            last_problem = f"响应里没有 Data 列表：{str(cand)[:120]}"
        if attempt + 1 < rounds:
            time.sleep(_PAGE_BACKOFF_SECONDS * (attempt + 1))
    if last_problem is not None:
        _log.warning("beisen GetJobAdPageList: PageIndex=%s 重试 %d 轮仍拿不到列表，最后一次：%s",
                     body.get("PageIndex"), rounds, last_problem)
    return None, ep_ok


def _dedup_new(chunk, seen_ids, id_fields):
    """本页里没见过的行（按岗位 id 去重）。翻页途中接口重复回同一批是常态，
    不去重会让「收满 total 就停」提前满足，尾巴永远抓不到。"""
    fresh = []
    for row in chunk:
        if not isinstance(row, dict):
            continue
        key = next((str(row[f]) for f in id_fields if row.get(f) not in (None, "")), None)
        if key is None:
            fresh.append(row)          # 认不出 id 的行照收，宁可重也不漏
            continue
        if key in seen_ids:
            continue
        seen_ids.add(key)
        fresh.append(row)
    return fresh



_TITLE_FIELDS = ("JobAdName", "title", "name", "jobTitle", "positionName")


def _titles_of(rows):
    """喂给 RepetitionBrake 的标题序列。北森真岗位恒有 JobAdName（见 _collect 的注释），
    其余字段是异构租户兼容兜底。取不到标题的行返回空串——RepetitionBrake 会忽略空串，
    既不算「新角色」也不会误判成重复。"""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            out.append("")
            continue
        out.append(_first_str(row, _TITLE_FIELDS) or "")
    return out


def _mark_list_cap(adapter, rows, total, cap) -> None:
    """翻页循环因「撞单源条数上限」收工、又确实没收齐自报总数时，记下停因 list_cap。

    只补不覆盖：刹车（repetition_brake）先判先得。为什么要记：我爱我家自报 2.9 万、撞 8000 上限，
    与「翻页中途坏了」在 crawl_runs 上长得一样（coverage_complete=false + 缺口），告警天天叫人
    「修分页」——其实是 base.DEFAULT_LIST_CAP 注释里写明的取舍，该看的是要不要为它抬上限。"""
    if getattr(adapter, "coverage_stop_reason", None):
        return
    if cap and len(rows) >= cap and (not total or len(rows) < total):
        adapter.coverage_stop_reason = "list_cap"


def _should_continue(fresh, chunk, total, page_size):
    """还该不该翻下一页。

    ⚠️ 末页判据**不能**用「本页条数 < pageSize」：北森在限流/抖动时会回短页（2026-09-04 本机
    连续请求就被它掐成 ConnectError），一个瞬时短页就会让整源停在半路 —— 中国交建自报 2565、
    深页明明有数据，却只抓到 800 就收工，正是这么来的。项目里 hotjob/海康那两次也栽在同一条。

    改用「这一页有没有带来新岗位」：接口在原地打转或真到末页 → fresh 为空 → 停；否则继续。
    只有在**没有分母可判**（total 未知）时，才退回短页当自然末页。"""
    if not fresh:
        return False
    if total:
        return True
    return len(chunk) >= page_size


# ============================================================================
# 一个北森租户挂着不止一家公司：按岗位自报的「招聘机构」归属（2026-09-23 立）
# ============================================================================
# 北森的租户 ≠ 公司。chinalife.zhiye.com 是中国人寿集团的租户，广发银行（集团成员）的校招 / 实习 / 社招
# 也发在这里：/custom/intern（国寿实习）与 /custom/gfcampus、/custom/gfintern（广发）是**同一个 PortalId**，
# 列表接口不分门户，一次返回整个租户。旧代码每条都贴 sources.company →
# 广发银行的「一级分行副行长级」「支行公司金融方向暑期实习生」全挂成了「中国人寿」。
#
# 事实来源 = 每行的 `Org`（页面上「招聘机构」那一列，要在 DisplayFields 里点名才返回）。
# 2026-09-23 live 全量 2,964 行：
#   · Org 非空 2,963 行；广发系 466 行，93 个机构全以「广发银行」「广银理财」开头；
#   · 广发自己的校招页圈岗用的是同一棵树（请求体 `ClassificationTwo: 468`）→ 该节点全量 466 行
#     与按 Org 分出来的 466 行逐条一致（多 0、少 0）；Org 与 ClassificationTwo 在 2,963 行上归属 100% 一致；
#   · Org 为空退 ClassificationTwo；两者冲突认 Org（已下线的岗里实测 1 例：「香港分行副行长级」
#     Org=广发银行总行、ClassificationTwo=中国人寿保险（集团）公司，正文写「本行任职回避」——是广发的岗）。
# 为什么不改成「每个门户只抓自己那份」：门户页没有自己的 PortalId，只能复刻它请求体里的树节点号，
# 那是页面配置、不是岗位事实，改一次页面就静默漂；两条源各抓一半还会让 upsert 的 source_id 来回抢。
# 逐岗 Org 是岗位自己带的，同一个 host 照旧一次抓全，list-absence 也仍是全集。
#
# host → ((招聘机构前缀, 归属公司), ...)，按序第一个命中者得；都不命中 = sources.company（租户本家）。
# 用前缀不用子串：本家机构名里夹着别家名字（「…驻广发银行…」）时子串会误判。
_BEISEN_SHARED_TENANTS = {
    "chinalife.zhiye.com": (("广发银行", "广发银行"), ("广银理财", "广发银行")),
}
# 只有共享租户才在列表请求里额外点名这两列，其余租户的请求体保持原样。
_BEISEN_ENTITY_FIELDS = ("Org", "ClassificationTwo")

# 反过来的情形：母集团门户与子公司门户是**两个北森租户**，同一个招聘需求各发一份（jobAdId 不同）。
# 子公司门户已单独接源，母集团门户里那份就跳过，否则同一个岗入库两行、挂两个公司名。
# 2026-09-24 普查：上实集团门户 149 个岗里 117 个与上海医药门户标题连同招聘编号一字不差
# （如「上海医药2027技术工培生(J12541)」，其中 113 个招聘机构也一字不差）；另 32 个是上实自己的
# （东滩疗养院 / 上实总部 / 永发印务 / 南洋兄弟烟草 / 上实服务…），照收。
# ⚠️ 认「同一个岗」靠标题一字不差，只对标题带招聘编号的租户成立；子公司门户那条源停用时这条登记要一起删，
#    否则这批岗两边都不入库。
# host → 子公司门户的列表页（PortalId 从这一页抽）。
_BEISEN_TWIN_PORTALS = {
    "siic.zhiye.com": "https://sph.zhiye.com/campus",
}


def beisen_hiring_entity(post) -> str:
    """岗位自报的招聘机构：Org 优先，空了退 ClassificationTwo；都没有返回空串。"""
    if not isinstance(post, dict):
        return ""
    return _first_str(post, _BEISEN_ENTITY_FIELDS)


def beisen_shared_tenant_owner(host: str, entity: str) -> Optional[str]:
    """共享租户里这条岗归哪家公司。None = 不是共享租户，或机构属于租户本家（沿用 sources.company）。"""
    for prefix, company in _BEISEN_SHARED_TENANTS.get(host or "", ()):
        if entity.startswith(prefix):
            return company
    return None


class BeisenAdapter(ChinaSpaAdapter):
    """北森招聘（*.zhiye.com / *.italent.cn / 自有 careers 域名，由北森承载）。

    source_url 填某公司北森招聘页（如 https://chinalife.zhiye.com/custom/intern）。
    北森列表接口 GetJobAdPageList 不含 per-job URL；详情页 query 恒为 `?jobAdId={Id}`，但 **path 因租户而异**
    （chinalife=/custom/zwxq、横店=/campus/detail…）。因此 fetch 时**逐租户自动探测**详情路由：
    用首个岗位 render-verify 候选 path（替换末段 / 追加 × 常见详情页名），命中「渲染该岗且 job-specific」
    者即为真路由，按 host 缓存。探不到则不拼 URL（丢弃，杜绝坏链）。
    """

    name = "beisen"
    intercept_matches = ("GetJobAdPageList", "JobAd", "Position", "position", "Recruit", "recruit", "/api/")
    # 老版 SSR 租户口径有年限（_SSR_TENANT_POLICY.max_age_days）时由 parse() 置成截止日，run.py 收抓后
    # 把库里发布日早于它的在招岗置 removed（可逆、不进 purge）。其余租户恒为 None，行为不变。
    retire_posted_before: Optional[date] = None
    detail_template = ""

    _ID_FIELDS = ("Id", "id", "jobAdId", "JobAdId", "code")
    # GetJobAdPageList 分页：北森列表页只发**一次** count-probe 请求拿总数（多数租户 PageSize=1，
    # 个别 PageSize=10），渲染时不会自己翻页到底。我们捕获该 POST、用站点自己的 PortalId+session
    # **服务端重放**并翻页到收齐 Count 条（接口实测支持 PageSize=50）。
    _PAGE_SIZE = 50      # 单页拉取数（接口实测 50 稳定返回）
    # 单租户抓取条数上限（env CRAWL_MAX_JOBS 可整体调档，见 base.resolve_list_cap 的取数依据）。
    # ⚠️ 别再把这个数字当成「越大越好」往上堆：2026-09-04 实测 26 个北森源因旧的 600 硬顶累计漏
    # 8.7 万岗（该修），但星巴克那 26,720 条归一后只有 30 种标题、3 种占 99%（不该整包拉）——
    # 「抓全」和「抓多」不是一回事。
    _MAX_JOBS = DEFAULT_LIST_CAP

    # list-absence 探活：beisen GetJobAdPageList 返全量在招岗 + 本类翻全 → 抓全时列表缺席=下架（同 feishu）。
    supports_absence_liveness = True
    fetch_complete = False

    def _map(self, post: dict) -> Optional[RawJob]:
        """在通用映射之上补一件事：把北森**自己声明的招聘类别**带进 job_type。

        GetJobAdPageList 每行都有 `Category`，值是中文串（"校园招聘" / "社会招聘" / "实习"），
        而通用 `_map` 找的是小写的 jobType/recruitType/… —— 大小写对不上，于是这个
        **租户自报、最权威**的信号被整包丢掉，招聘类型只能回落到标题/URL 猜。
        后果是校招岗被兜底成社招：2026-09-17 live 逐租户问北森自己（Category=["2"] 的 Count），
        252 个租户自报 22,862 个校招岗，而库里同一批 host 分类成校招的只有一部分 ——
        奇瑞自报 2,261 / 库里 54、中核集团自报 854 / 库里 0、泰格医药 214 / 5。
        这些岗的标题（"生产操作工" "销售代表"）和 URL（/social/detail?jobAdId=…）里一个校招令牌都没有，
        光靠现有七层裁决**永远**判不出来 —— 唯一的事实来源就是这个字段。

        ⚠️ 只取 `Category`，**绝不能顺手把 `Kind` 也带上**：Kind 是"全职/兼职"，
           而 `sourceDeclaredCategory("全职")` 直接返回「社招」—— 那会把校招岗按住判成社招，
           正好把这个 bug 放大一遍。
        ⚠️ 仍然只在 job_type 为空时才填，不覆盖已有值（保持与通用 _map 的优先级一致）。
        ⚠️ 判定规则本身**不在这里**：这里只负责如实把事实搬过来，
           "校园招聘"→校招 的裁决仍归 lib/china-keyword-expansion.js 的 sourceDeclaredCategory
           （层3），规则只有一份。
        """
        job = super()._map(post)
        if job is not None and not job.job_type and isinstance(post, dict):
            declared = _first_str(post, ("Category", "CategoryName"))
            if declared:
                job.job_type = declared
        if job is not None:
            # 共享租户：按岗位自报的招聘机构归属（见 _BEISEN_SHARED_TENANTS）。
            owner = beisen_shared_tenant_owner(getattr(self, "_host", ""), beisen_hiring_entity(post))
            if owner:
                job.company = owner
        return job

    def fetch(self, source_url: str) -> str:
        """httpx-first（2026-06-28 实测 6/6 租户冷 httpx 可达）：HTML 抽 PortalId → GetJobAdPageList 翻页，
        **零浏览器**。但 jd_url 需本租户详情路由（点击捕获，按 host 缓存到 beisen_routes.json）——故仅当
        **route 已缓存**时走 httpx（能拼 jd_url）；route 未缓存的租户回退浏览器（顺带探+缓存 route，由
        harvest_beisen_routes.py 持久化）。daily-crawl 无 Playwright → httpx 路径自给，回退浏览器会抛由上层记 failed。"""
        self.reported_total = None
        self.fetch_complete = False
        self.coverage_stop_reason = None
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        self.list_urls = [source_url]

        route = _BEISEN_ROUTE_CACHE.get(self._host)
        # beisen_routes.json 里登记 {"cms": true} = 已知老版 CMS Portal 租户。作用有二：
        #   ① 让 beisen_httpx_ready() 认它为「零浏览器可抓」→ run.py 把它排进 httpx 并发快车道
        #      （否则未登记的 host 一律落串行浏览器档，白占慢车道名额）；
        #   ② 直接走老版 CMS 分支，省掉一次注定拿不到 PortalId 的新版探测请求。
        # {"cards": true} 同理，登记的是卡片式 CMS 租户（见 _httpx_fetch_cards）；
        # {"ssr": true} 同理，登记的是老版 SSR「jobsTable」路径式详情租户（见 _httpx_fetch_ssr_paged）。
        cards_hint = isinstance(route, dict) and route.get("cards") is True
        cards_tried = False
        if cards_hint:
            cards_tried = True
            try:
                cards = self._httpx_fetch_cards(source_url)
            except Exception:
                cards = None
            if cards:
                return cards
            # 登记过时（租户换模板/升级 SPA）→ 与下面 cms 分支同一条纪律：把假登记清掉，
            # 否则「首见租户」分支会因为 host 还在缓存里被跳过 → 0 岗 + 自称抓全。
            _BEISEN_ROUTE_CACHE.pop(self._host, None)
            route = None

        cms_hint = isinstance(route, dict) and route.get("cms") is True
        cms_tried = False
        if cms_hint:
            cms_tried = True
            try:
                cms = self._httpx_fetch_cms(source_url)
            except Exception:
                cms = None
            if cms:
                return cms
            # 登记信息过时（租户升级到新版 SPA）→ **必须把这条假登记从缓存里清掉**，否则下面
            # 「首见租户」分支会因为 host 还在缓存里被跳过 → 详情路由永远探不出来 → _resolve_url
            # 全返空 → 整源解析成 0 岗，偏偏浏览器路径又把 fetch_complete 置成 True
            # ＝「0 岗 + 自称抓全」，正是 CLAUDE.md §4 立碑警告的误杀在招岗组合。
            _BEISEN_ROUTE_CACHE.pop(self._host, None)
            route = None

        # {"ssr": true} 同理，登记的是老版 SSR「jobsTable」路径式详情租户（见 _httpx_fetch_ssr_paged）。
        # 别与被禁的 {ssr_path, ssr_param} 形状搞混——那是给新版接口 uuid 拼模板用的旧残留，
        # 这里的 {"ssr": true} 跟 cms/cards 一样只是「零浏览器可抓」标记，不参与拼链接。
        ssr_hint = isinstance(route, dict) and route.get("ssr") is True
        ssr_tried = False
        if ssr_hint:
            ssr_tried = True
            try:
                ssr = self._httpx_fetch_ssr_paged(source_url)
            except Exception:
                ssr = None
            if ssr:
                return ssr
            _BEISEN_ROUTE_CACHE.pop(self._host, None)
            route = None

        if route is not None and not _beisen_route_usable(route):
            # 同上一段一模一样的道理，只是过期的是**老版 SSR 路由登记**：租户升级到新版 SPA 后，
            # `{ssr_path, ssr_param}` 配不了新版接口的 uuid（真渲染实测拼出来是首页，见
            # _beisen_route_usable 的注释）。留着它 = 每行 jd_url 空串 = 「success + 0 岗」永久静默。
            # 清掉 → 落到下面「首见租户」分支，httpx 抓完整列表 + 浏览器重探一次路由。
            _BEISEN_ROUTE_CACHE.pop(self._host, None)
            route = None

        if route:  # route 已缓存 → 尝试纯 httpx（拿到列表即能拼 jd_url，不开浏览器）
            try:
                j = self._httpx_fetch(source_url)
            except Exception:
                j = None
            if j:
                self._detail_route = route
                return j
            # 老版 SSR「jobsTable」租户（路径式详情）：没有 PortalId → _httpx_fetch 恒为 None。
            # 必须在下面 raise 之前试一把，否则这类租户被旧路由登记「锁死」在 failed 上
            # （2026-09-04 实测日立能源 / 华安基金即此症状：错误恒为 "httpx fetch failed for cached route"）。
            ssr = self._httpx_fetch_ssr_paged(source_url)
            if ssr:
                return ssr
            # 卡片式 CMS 租户同理（也没有 PortalId）：旧路由登记会把它锁死在 failed 上，
            # 必须在 raise 之前试一把。放在最后＝旧分支全部落空才轮到它，既有源的命运不受影响。
            if not cards_tried:
                cards = self._httpx_fetch_cards(source_url)
                if cards:
                    return cards
            # httpx 失败且路由已缓存 → 不要穿透到浏览器（CI 环境未装 Playwright 会直接崩溃）。
            # 正确处理：记 partial_success，等下次 auto-discover 重跑刷新路由缓存。
            raise RuntimeError(
                f"beisen: httpx fetch failed for cached route "
                f"({self._host} → {route!r}); retry after auto-discover refreshes the route"
            )

        # route 未缓存的**首见租户**：先用 httpx 抓**完整列表**（可靠），浏览器只用来探一次路由。
        # 为何：旧实现直接走下面的 _fetch_paginated 抓列表，但浏览器拦截重放对多数租户只捞到 count-probe
        # 的 1-2 条 → 列表近空 → 路由探测拿不到候选、jd_url 全空 → auto-discover 逐家确认把长江存储 479 /
        # 追觅 2248 岗这类真源全判「0 岗」丢弃。实测：把 httpx 完整列表喂给 _discover_detail_route，
        # 路由探测正常命中、几百上千岗全拼出 jd_url。故此处 httpx 抓列表 + 浏览器仅探路由。
        if self._host not in _BEISEN_ROUTE_CACHE:
            try:
                j = self._httpx_fetch(source_url)
            except Exception:
                j = None
            if j:
                try:
                    route = self._discover_detail_route(source_url, j)  # 浏览器仅探路由，不抓列表
                except Exception:
                    route = None
                _BEISEN_ROUTE_CACHE[self._host] = route   # 命中或 None 都缓存，避免重复探测
                self._detail_route = route
                return j

        # 新版 GetJobAdPageList 没打通 → 先试**老版 CMS Portal 门户**（theme2 SSR，同样零浏览器）。
        # 放在开浏览器之前：老版 CMS 抽不到 PortalId，走浏览器只会白跑几分钟且 _fetch_ssr 不翻页。
        # 与上面两处 httpx 尝试同样的容错口径：这条新分支出任何意外都只退回原有浏览器路径，不改变既有源的命运。
        if not cms_tried:
            try:
                cms = self._httpx_fetch_cms(source_url)
            except Exception:
                cms = None
            if cms:
                # 首次证实「这是老版 CMS 租户」必须登记 {"cms": true}，否则这个事实只活在
                # 这一次 fetch() 调用里：harvest_beisen_routes.py 只看 _BEISEN_ROUTE_CACHE 判
                # 「探到路由没」，CMS 租户压根不需要 template（jd_url 来自列表锚点本身）却因为
                # 没登记而被当成「还没探出来」天天重探、harvested 永远 0（2026-09-23 实测
                # harvest_beisen_routes.py 待探队列 26 家里 2 家属这一类，同批 23 家其实是下面
                # 的 ssr 分支——两个分支都漏登记，症状一模一样）；run.py 的 beisen_httpx_ready()
                # 同样读不到，会把零浏览器可抓的源错分进慢车道。
                _BEISEN_ROUTE_CACHE[self._host] = {"cms": True}
                return cms

        # 老版 SSR「jobsTable」门户（路径式详情，非 ?jobId= 故 CMS 分支匹配不到）→ 纯 httpx 翻到底。
        # 放在开浏览器之前：浏览器 _fetch_ssr 只渲染首屏、不翻页、也不报分母。
        if not ssr_tried:
            ssr = self._httpx_fetch_ssr_paged(source_url)
            if ssr:
                # 同上一条 cms 分支：这类租户是 2026-09-23 那批 26 个 pending 里的大头（23/26），
                # 不登记 {"ssr": true} 就会被 harvest_beisen_routes.py 天天当成「还没探出路由」
                # 重探，而它们其实早就能纯 httpx 抓全，压根不需要探测。
                _BEISEN_ROUTE_CACHE[self._host] = {"ssr": True}
                return ssr

        # 卡片式 CMS 门户（列表卡内嵌整段 JD）→ 纯 httpx 翻到底。**排在所有旧分支之后**：
        # 旧分支任何一条能出岗就轮不到它，所以既有源走的路一步没变；只有「旧的全部落空、
        # 原本注定掉进浏览器 _fetch_ssr 并 raise『无 jobId/adId 锚点』」的租户才会走到这里。
        if not cards_tried:
            try:
                cards = self._httpx_fetch_cards(source_url)
            except Exception:
                cards = None
            if cards:
                # 同上一条 cms 分支的道理：卡片式 CMS 租户也不需要 template，
                # 不登记 {"cards": true} 就会永远卡在「待探路由」的假 pending 里。
                _BEISEN_ROUTE_CACHE[self._host] = {"cards": True}
                return cards

        # 都没打通 → 回退浏览器全流程（探+缓存 route），再不行落 SSR
        try:
            list_json = self._fetch_paginated(source_url)
        except RuntimeError:
            return self._fetch_ssr(source_url)
        self._detail_route = _BEISEN_ROUTE_CACHE.get(self._host)
        if self._detail_route is None and self._host not in _BEISEN_ROUTE_CACHE:
            self._detail_route = self._discover_detail_route(source_url, list_json)
            _BEISEN_ROUTE_CACHE[self._host] = self._detail_route  # 命中或 None 都缓存，避免重复探测
        return list_json

    def _httpx_fetch(self, source_url: str) -> Optional[str]:
        """纯 httpx 抓 beisen 列表（无浏览器）：GET 列表页 HTML 抽 PortalId → POST GetJobAdPageList 翻全。
        Category 由 url 路径判（campus/intern→校招"2"，否则社招"1"）；端点大小写两试（/api/Jobad/ 与 /api/JobAd/）。
        返回 {"_intercepted":[{"Data":[...],"Count":N}]}（与浏览器路径同 shape，parse/_map 不变）或 None（没打通）。"""
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        # Category=[] = 不按招聘类别过滤 = 返该租户**全部**岗（社招+校招+实习+内部）。2026-06-29 实测：单类别
        # （由 url 路径猜社招/校招）会漏抓另一类别 → 那些 live 岗在 list-absence 里被误判「缺席」=误杀活岗
        # （changan 社招[1]=185 但全部[]=204、leapmotor [1]=829 vs []=921）。取全部 → live 是 DB 的超集 →
        # absence 只判真正撤掉的岗，绝不误杀；freshness 也更全。dedup 靠 canonical_jd_url（同岗一行）。
        ua = PlaywrightAdapter.user_agent
        rows: List[dict] = []
        total: Optional[int] = None
        # 接口是否至少答上来一次（拿到过 dict 响应），区分「真的 0 岗」与「没打通」——同 alibaba.py
        # 的 api_answered 口径。建信基金（ccbfund.zhiye.com）实测：PortalId 能抽到、接口稳定 200
        # 返回 {"Code":200,"Data":[],"Total":0}（/social /campus /intern 逐板块 + 逐 Category 值
        # 交叉验证过，不是某一次偶然），此前 rows 为空一律 return None，把「真 0 岗」和「接口没打通」
        # 混成一种 → 触发下面缓存路由分支的 raise，天天记 failed、25 次都等不到 auto-discover 自愈
        # （根本没有「过期路由」可刷新，租户就是眼下没开放岗位）。
        api_answered = False
        endpoints = (f"{origin}/api/Jobad/GetJobAdPageList", f"{origin}/api/JobAd/GetJobAdPageList")
        ep_ok = None
        display_fields = ["Category", "Kind", "LocId", "PostDate", "WorkWeChatQrCode"]
        if parsed.netloc in _BEISEN_SHARED_TENANTS:
            display_fields += list(_BEISEN_ENTITY_FIELDS)   # 不点名就不返回，归属无从判
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": ua}) as cli:
            try:
                html = cli.get(source_url).text
            except Exception:
                return None
            m = re.search(r'PortalId"\s*:\s*"([0-9a-fA-F-]+)"', html or "")
            portal_id = m.group(1) if m else ""
            index = 0
            seen_ids: set = set()
            cap = resolve_list_cap(self._MAX_JOBS)
            brake = RepetitionBrake()
            while len(rows) < cap:
                body = {"PageIndex": index, "PageSize": self._PAGE_SIZE, "Category": [],
                        "KeyWords": "", "SpecialType": 0, "PortalId": portal_id,
                        "DisplayFields": display_fields}
                jj, ep_ok = _post_page_with_retry(cli, endpoints, ep_ok, body)
                if not isinstance(jj, dict):
                    break
                api_answered = True
                if total is None:
                    total = jj.get("Count") or jj.get("Total") or 0
                    reported = _int_or_none(jj.get("Count"))
                    if reported is None:
                        reported = _int_or_none(jj.get("Total"))
                    if reported is not None:
                        self.reported_total = reported
                chunk = jj.get("Data") or []
                if not isinstance(chunk, list) or not chunk:
                    break
                fresh = _dedup_new(chunk, seen_ids, self._ID_FIELDS)
                rows.extend(fresh)
                if total and len(rows) >= total:
                    break
                # 重复度刹车（批量门店发布源）。放在「抓全」判定之后：能抓全的源一律抓全，
                # 只有还要继续翻页时才问「再翻还有没有新角色」。刹停 → fetch_complete 天然为 False。
                if brake.observe(_titles_of(fresh)):
                    self.coverage_stop_reason = "repetition_brake"
                    _log.info("%s: 重复度刹车 —— 连续 %d 条没有新角色，停在 %d/%s 条 host=%s",
                              self.name, brake.stall_rows, len(rows), total, self._host)
                    break
                if not _should_continue(fresh, chunk, total, self._PAGE_SIZE):
                    break
                index += 1
            _mark_list_cap(self, rows, total, cap)
        if not rows:
            # portal_id 抽到了（不是「页面结构变了、我们没找对 PortalId」）且接口至少答过一次
            # 且明确回了 Count/Total=0（reported_total 由上面显式置 0，非默认 None）→ 真 0 岗，
            # 当成功返回；否则维持原样返 None，交回上层去试 ssr/cards 或最终判 failed。
            if api_answered and portal_id and self.reported_total == 0:
                self.fetch_complete = True
                return json.dumps({"_intercepted": [{"Data": [], "Count": 0}]}, ensure_ascii=False)
            return None
        self.fetch_complete = (total is not None and len(rows) >= (total or 0))
        # 「抓全」按剔除孪生之前的整张列表判：剔掉的是别的门户已经入库的岗，不是我们漏抓的。
        rows = self._drop_twin_portal_rows(parsed.netloc, rows)
        if rows is None:
            return None
        return json.dumps({"_intercepted": [{"Data": rows, "Count": total or len(rows)}]}, ensure_ascii=False)

    def _drop_twin_portal_rows(self, host: str, rows: List[dict]) -> Optional[List[dict]]:
        """见 _BEISEN_TWIN_PORTALS：剔掉子公司门户也在招的岗。子公司门户列表拉不到 → None（上层记失败），
        不静默全收——全收就是一岗两行、两个公司名。"""
        twin_url = _BEISEN_TWIN_PORTALS.get(host)
        if not twin_url:
            return rows
        try:
            payload = BeisenAdapter()._httpx_fetch(twin_url)
        except Exception:        # noqa: BLE001 — 原因在下面的日志里，交上层记 failed
            payload = None
        if not payload:
            _log.warning("%s: %s 的孪生门户 %s 列表没拉到，本轮不入库（避免一岗两行）", self.name, host, twin_url)
            return None
        twin_titles = {_first_str(r, _TITLE_FIELDS)
                       for resp in json.loads(payload).get("_intercepted") or []
                       for r in resp.get("Data") or [] if isinstance(r, dict)}
        twin_titles.discard("")
        kept = [r for r in rows if _first_str(r, _TITLE_FIELDS) not in twin_titles]
        _log.info("%s: %s 剔掉 %d 个孪生门户 %s 也在招的岗，留 %d 个",
                  self.name, host, len(rows) - len(kept), twin_url, len(kept))
        return kept

    # ---- 老版 CMS Portal 门户（theme2 SSR）：纯 httpx 抓全 ----

    @staticmethod
    def _cms_page_url(parsed, page: int) -> str:
        """把 PageIndex 换成目标页（保留 source_url 自带的其它 query，替换而非追加）。"""
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if k.lower() != "pageindex"]
        query.append(("PageIndex", str(page)))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _httpx_fetch_cms(self, source_url: str) -> Optional[str]:
        """老版 CMS Portal 门户（北森 theme2 SSR）：纯 httpx 翻全列表 + SSR 详情直出正文。

        返回值与 _fetch_ssr 同 shape（``{"_ssr_jobs":[…]}``），parse() 不必新增分支。
        **不是**老版 CMS（列表页抽得到 PortalId → 新版 SPA；或首页没有 <li> jobId 锚点）→ 返回 None，
        原封不动交回原有流程（浏览器重放 / _fetch_ssr），故对现有 234 个新版租户零影响。
        """
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        pages_seen = [0]        # 闭包记账：真正抓了几页（用于校正 fetch_complete，见下）
        repeated = [False]      # 翻页参数不认账（每页都回同一批岗）时置位，见 fetch_page
        cache = {}              # 首页 HTML 复用，别为了探测多打一次
        all_urls = set()

        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
            try:
                first = cli.get(self._cms_page_url(parsed, 1))
                first.raise_for_status()
            except Exception:
                return None
            # 识别按响应特征，不按域名/租户名：有 PortalId = 新版 SPA，不归本分支管。
            if _CMS_PORTAL_ID_RE.search(first.text or ""):
                return None
            cache[1] = first.text
            first_rows, last_page = _cms_parse_list(first.text, origin)
            if not first_rows:
                return None

            def fetch_page(page: int) -> PageResult:
                text = cache.pop(page, None)
                if text is None:
                    resp = cli.get(self._cms_page_url(parsed, page))
                    resp.raise_for_status()   # 首页失败上抛记 failed；后续页由 paginate_all 尽力而为
                    text = resp.text
                rows, _ = _cms_parse_list(text, origin)
                pages_seen[0] = page
                # 该租户的翻页参数不是 PageIndex（页页回同一批岗）→ 立刻停，别空转 200 页；
                # 且此时**只看见了第一页**，绝不能自称抓全（下面把 complete 置 False）。
                fresh = [r for r in rows if r["jd_url"] not in all_urls]
                if rows and not fresh:
                    repeated[0] = True
                    return PageResult(items=[], total=None, total_pages=None)
                all_urls.update(r["jd_url"] for r in rows)
                # 翻页越界仍是 200 + 完整骨架 → 只能靠「本页锚点数 0」判终止（paginate_all 的空页规则）。
                # total_pages 只认首页分页条自报的末页号（实测每页都带真末页，社招 30 / 校招 25 / 海外 3）。
                return PageResult(items=rows, total=None,
                                  total_pages=last_page if page == 1 else None)

            jobs, _total, complete = paginate_all(
                fetch_page, page_size=_CMS_PAGE_SIZE, first_page=1,
                max_pages=_CMS_MAX_PAGES, logger=None,
                label=f"beisen-cms {parsed.netloc}")

            # 分页条自报 N 页却没翻到 N 页（中途空页/限流），或翻页参数根本不认账 → 不许自称抓全。
            # fetch_complete=True 会开启 list-absence 撤岗，抓漏 + 自称抓全 = 误杀在招岗（CLAUDE.md §4 立碑）。
            if repeated[0] or (last_page and pages_seen[0] < last_page):
                complete = False

            uniq, seen = [], set()
            for row in jobs:
                if row["jd_url"] in seen:
                    continue
                seen.add(row["jd_url"])
                uniq.append(row)
            self._cms_fill_details(uniq, cli)

        if not uniq:
            return None
        # 站点只报页数不报岗位总数 → 抓全时诚实把「看见的全部」记为分母（paginate_all 同口径）。
        self.reported_total = len(uniq) if complete else None
        self.fetch_complete = complete
        return json.dumps({"_ssr_jobs": uniq}, ensure_ascii=False)

    def _cms_fill_details(self, rows: List[dict], cli) -> None:
        """逐岗 GET SSR 详情页补 summary / 全名标题 / 学历（同一个 GET 全拿到，无需单独 enrich 通道）。

        两个 cap：
          - 正文富化走 resolve_detail_cap(_CMS_DETAIL_CAP)，日更快车道 CRAWL_DETAIL_CAP=0 时跳过（框架约定）。
          - **截断标题**（列表 25 字截断，实测约 10% 的行）另有独立小额度：即使富化关掉也要修，
            否则快车道写「…(J133...」、夜间富化写全名，同一岗标题天天来回抖（title 不在 _PRESERVE_IF_EMPTY 里）。
        单条失败静默跳过（保留列表信息，最差是薄卡），绝不因为一个详情页炸掉整源。"""
        cap = resolve_detail_cap(_CMS_DETAIL_CAP)
        truncated = [r for r in rows if r.get("title_truncated")]
        # 列表已自带正文（position-item 模板）的行不用再打详情页；theme2 列表从不带 summary，对既有租户是空操作。
        rest = [r for r in rows if not r.get("title_truncated") and not r.get("summary")]
        queue = truncated + rest
        budget = max(cap, min(len(truncated), _CMS_TITLE_REPAIR_CAP))
        for row in queue[:budget]:
            try:
                resp = cli.get(row["jd_url"])
                if resp.status_code != 200:
                    continue
                detail = _cms_parse_detail(resp.text)
            except Exception:
                continue
            # 详情页 <h2> 才是全名；伪 id 页只有导航骨架（无 h2、无 xqm）→ detail 全空，保留列表值。
            if detail["title"] and not _CMS_TRUNCATED_RE.search(detail["title"]):
                row["title"] = detail["title"]
                row["title_truncated"] = False
            for field in ("summary", "education", "job_type", "location"):
                if detail.get(field) and not row.get(field):
                    row[field] = detail[field]

    def _httpx_fetch_cards(self, source_url: str) -> Optional[str]:
        """卡片式 CMS 门户（列表卡内嵌整段 JD）：纯 httpx 翻全 + 详情页补正文。

        返回值与 _fetch_ssr 同 shape（``{"_ssr_jobs":[…]}``），parse() 不必新增分支。
        判据是「列表行的 <a> 里有 <dd> 标题」这一条结构特征；**不是**这种门户（抽得到 PortalId
        = 新版 SPA，或一行 <dd> 都没有）→ 返回 None，原封不动交回原有流程，故对既有租户零影响。

        ⚠️ fetch_complete 只在**正面证明抓全**时才置 True（BeisenAdapter 开着 list-absence，
        「抓漏 + 自称抓全」＝误杀在招岗，CLAUDE.md §4 立碑）。两道否决：
          ① 翻页参数不认账（页页回同一批岗）；② 分页条自报 N 页却没翻到 N 页。
        """
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        job_type = _card_board_job_type(parsed.path)
        pages_seen = [0]
        repeated = [False]
        cache = {}              # 首页 HTML 复用，别为了探测多打一次
        all_urls = set()

        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
            try:
                first = _get_page_with_retry(cli, self._cms_page_url(parsed, 1))
            except Exception:
                return None
            # 识别按响应特征，不按域名/租户名：有 PortalId = 新版 SPA，不归本分支管（同 _httpx_fetch_cms）。
            if _CMS_PORTAL_ID_RE.search(first.text or ""):
                return None
            cache[1] = first.text
            first_rows, last_page = _card_parse_list(first.text, origin, job_type)
            if not first_rows:
                return None
            # 每页行数不写死（同 jobsTable 分支的坑①：各租户每页条数不同），按首页实际行数推断。
            page_size = len(first_rows)

            def fetch_page(page: int) -> PageResult:
                text = cache.pop(page, None)
                if text is None:
                    # 首页失败上抛记 failed；后续页由 paginate_all 尽力而为（保留已抓 + complete=False）。
                    text = _get_page_with_retry(cli, self._cms_page_url(parsed, page)).text
                rows, _ = _card_parse_list(text, origin, job_type)
                pages_seen[0] = page
                # 该租户的翻页参数不认账（页页回同一批岗）→ 立刻停，别空转 200 页；
                # 且此时**只看见了第一页**，绝不能自称抓全（下面把 complete 置 False）。
                fresh = [r for r in rows if r["jd_url"] not in all_urls]
                if rows and not fresh:
                    repeated[0] = True
                    return PageResult(items=[], total=None, total_pages=None)
                all_urls.update(r["jd_url"] for r in rows)
                # 翻页越界仍是 200 + 完整骨架（实测 /social?PageIndex=21 返 200 但 0 个锚点）
                # → 只能靠「本页 0 行」判终止，绝不能靠状态码。
                # total_pages 只认首页分页条自报的末页号（实测社招 20 / 校招 3 / 实习无分页条）。
                return PageResult(items=fresh, total=None,
                                  total_pages=last_page if page == 1 else None)

            max_pages = min(resolve_page_cap(page_size, self._MAX_JOBS), _CARD_MAX_PAGES)
            jobs, _total, complete = paginate_all(
                fetch_page, page_size=page_size, first_page=1,
                max_pages=max_pages, logger=None,
                label=f"beisen-cards {parsed.netloc}")

            if repeated[0] or (last_page and pages_seen[0] < last_page):
                complete = False

            uniq, seen = [], set()
            for row in jobs:
                if row["jd_url"] in seen:
                    continue
                seen.add(row["jd_url"])
                uniq.append(row)
            self._card_fill_details(uniq, cli)

        if not uniq:
            return None
        # 站点只报页数不报岗位总数 → 抓全时诚实把「看见的全部」记为分母（同 theme2 CMS 口径）。
        self.reported_total = len(uniq) if complete else None
        self.fetch_complete = complete
        # list-absence 保持类默认（开），理由与 _httpx_fetch_ssr_paged 那条**相反**且都有据：
        #   · 那条关掉，是因为库里压着旧浏览器路径留下的跨板块脏行（详情页侧栏「热招职位」被当成本板块的岗）；
        #     本分支是全新接入、只从本板块列表取行，没有那种历史包袱；
        #   · 板块之间**实测互不重叠**（方太 social/campus/intern 三个 jobId 集合两两交集 = 0），
        #     所以「这个板块的列表就是这个板块的全集」成立；
        #   · 且 absence 只在 fetch_complete=True 时才跑，而 complete 有上面两道否决把关。
        # 另外 run.py 的 LIVENESS_ABSENCE_OBSERVE 默认就含 beisen ＝ 全 beisen 源当前都是 dry-run 观察，
        # 真要开 apply 得先拿观察期的缺席占比说话（不可逆操作前先核验，CLAUDE.md §4）。
        return json.dumps({"_ssr_jobs": uniq}, ensure_ascii=False)

    @staticmethod
    def _card_needs_repair(row: dict) -> bool:
        """这一行的**列表值本身就是残的**，必须补详情，否则快车道与夜间富化会写出两个值。

        两种残法（2026-09-18 方太 231 行实测）：
          · 标题被服务端按宽度截断，11 行（`中医研发工程师（系统开发）(J154...`）——title 不在
            jobs_db._PRESERVE_IF_EMPTY 里，快车道写截断名、富化写全名 = 天天来回抖（同 theme2 坑⑤）；
          · 地点截在词中间认不出来，1 行（`新疆维吾尔自治...` 少了末尾的「区」→ 不含省/市/区/县 →
            _card_meta_fields 留 None）——location 同样不在 _PRESERVE_IF_EMPTY 里，同款抖。
        """
        return bool(_CMS_TRUNCATED_RE.search(row.get("title") or "")) or not row.get("location")

    def _card_fill_details(self, rows: List[dict], cli) -> None:
        """逐岗 GET 详情页补 summary（+ 列表值残缺时补全名标题 / 地点）。

        两个 cap，与 theme2 CMS 的 _cms_fill_details 同一套做法：
          - 正文富化走 resolve_detail_cap(_CARD_DETAIL_CAP)，快车道 CRAWL_DETAIL_CAP=0 时跳过；
          - **残缺行**另有独立小额度：即使富化关掉也要补，否则那些行的 title/location 天天抖。
        ⚠️ **列表已经给全的 location 不许被详情覆盖**：列表地点剥掉截断尾巴后与详情地点经
        clean_location 归一到同一个城市（实测 `浙江省-宁波市-...` 与 `浙江省-宁波市-慈溪市`
        都是「宁波」），但多地岗的详情页会把地点列全 —— 让详情覆盖就又变成两个 lane 两个值。
        单条失败静默跳过（最差是薄卡），绝不因为一个详情页炸掉整源。"""
        cap = resolve_detail_cap(_CARD_DETAIL_CAP)
        broken = [r for r in rows if self._card_needs_repair(r)]
        rest = [r for r in rows if not self._card_needs_repair(r)]
        budget = max(cap, min(len(broken), _CARD_REPAIR_CAP))
        for row in (broken + rest)[:budget]:
            try:
                resp = cli.get(row["jd_url"])
                if resp.status_code != 200:
                    continue
                detail = _card_parse_detail(resp.text)
            except Exception:
                continue
            if detail["title"] and not _CMS_TRUNCATED_RE.search(detail["title"]):
                row["title"] = detail["title"]
            for field in ("summary", "location", "posted_at"):
                if detail.get(field) and not row.get(field):
                    row[field] = detail[field]

    def _httpx_fetch_ssr_paged(self, source_url: str) -> Optional[str]:
        """老版 SSR「jobsTable」门户（路径式详情）：纯 httpx **翻到底** + 分母取自页面分页条。

        返回值与 _fetch_ssr 同 shape（``{"_ssr_jobs":[…]}``），parse() 不必新增分支。
        不是这种门户（首页解析不出路径式锚点）→ 返回 None，原样交回原有流程（浏览器 _fetch_ssr），
        故对其它租户零影响。

        ⚠️ fetch_complete 只在**正面证明抓全**时才置 True（BeisenAdapter 开着 list-absence 撤岗，
        「抓漏 + 自称抓全」＝误杀在招岗，CLAUDE.md §4 立碑）。三道否决：
          ① 翻页参数不认账（页页回同一批岗）；② 分页条自报 N 页却没翻到 N 页；③ 收到的条数 < 自报总数。
        """
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        seen_urls: set = set()
        pages_seen = [0]
        repeated = [False]      # 翻页参数不认账（每页都回同一批岗）时置位
        cache = {}              # 首页 HTML 复用，别为了探测多打一次

        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
            try:
                first = cli.get(self._cms_page_url(parsed, 1))
                first.raise_for_status()
            except Exception:
                return None
            cache[1] = first.text
            first_rows, first_total, last_page = _ssr_parse_list(first.text, origin)
            if not first_rows:
                return None
            # 坑①：每页行数逐租户不同（实测 15 / 10），按首页行数推断，别写死。
            page_size = len(first_rows)

            def fetch_page(page: int) -> PageResult:
                text = cache.pop(page, None)
                if text is None:
                    resp = cli.get(self._cms_page_url(parsed, page))
                    resp.raise_for_status()   # 首页失败上抛记 failed；后续页由 paginate_all 尽力而为
                    text = resp.text
                rows, total, lastp = _ssr_parse_list(text, origin)
                pages_seen[0] = page
                # 该租户不认 PageIndex（页页回同一批岗）→ 立刻停，别空转 200 页；
                # 且此时只看见了第一页，绝不能自称抓全（下面置 complete=False）。
                fresh = [r for r in rows if r["jd_url"] not in seen_urls]
                if rows and not fresh:
                    repeated[0] = True
                    return PageResult(items=[], total=None, total_pages=None)
                seen_urls.update(r["jd_url"] for r in rows)
                return PageResult(items=fresh,
                                  total=total if page == 1 else None,
                                  total_pages=lastp if page == 1 else None)

            max_pages = min(resolve_page_cap(page_size, self._MAX_JOBS), _SSR_PAGED_MAX_PAGES)
            jobs, reported, complete = paginate_all(
                fetch_page, page_size=page_size, first_page=1,
                max_pages=max_pages, logger=None,
                label=f"beisen-ssr {parsed.netloc}")

        if repeated[0] or (last_page and pages_seen[0] < last_page):
            complete = False
        if first_total is not None and len(jobs) < first_total:
            complete = False
        if not jobs:
            return None
        # 租户口径先筛、再补正文：补正文每轮有上限（_BEISEN_SSR_SUMMARY_CAP），先补后筛会把
        # 名额全花在要被筛掉的旧岗上（百胜中国实测：列表前 60 行全是 2022 年的岗）。
        # parse() 里还会再套一次同一口径（浏览器兜底路径也要受约束），两次结果一致。
        policy = _SSR_TENANT_POLICY.get(parsed.netloc.lower())
        if policy:
            jobs = [j for j in jobs if _ssr_policy_allows(j, policy)]
        _beisen_ssr_fill_summaries(jobs)
        # 站点报了总条数就用它当分母；没报（单页租户不渲染分页条）→ 抓全时诚实记「看见的全部」。
        self.reported_total = (first_total if first_total is not None
                               else (len(jobs) if complete else None))
        self.fetch_complete = complete
        # 🚫 抓全 ≠ 可以按缺席撤岗 —— 本路径**单独关掉** list-absence（类默认 True，只降本实例）。
        # 「这个板块的列表是全集」是真的（收到的条数 == 站点自报），但库里还压着**旧浏览器路径**
        # 留下的脏行：老的 _fetch_ssr 用 a[href] 全页抓锚点，把详情页侧栏「热招职位/长招职位」里
        # **别的板块**的岗也收了进来，挂在本源名下。
        # 2026-09-04 live 实证（联易融 /social，库里 13 行 vs 列表 13 行）：2 行缺席里
        #   · 390849929 详情页写「对不起，此职位已停用」→ 真撤岗；
        #   · 390854070 详情页是**在招的校园招聘岗**（发布 2026-08-13，武汉）——它只是不属于
        #     /social 板块，而 linklogis 并没有 /campus 源，一旦按缺席撤岗就会被 expired、
        #     次日 purge-expired 永久删除。这正是 CLAUDE.md §4 立碑的「误杀在招岗」。
        # 抽样一个源的 2 条缺席里就有 1 条是活岗，错杀率太高，不满足「不可逆操作前先核验」的门槛。
        # 代价可控：beisen 死岗本来就由 dead-link-audit.yml（浏览器 SPA 审计）逐岗判，
        # 不依赖 list-absence，关掉只是少一条冗余通道，不会让死岗永远挂着。
        self.supports_absence_liveness = False
        return json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False)

    def _fetch_paginated(self, source_url: str) -> str:
        """渲染列表页，捕获其 GetJobAdPageList POST 请求，然后用站点自身 session 服务端翻页重放，
        把全部岗位收齐成单个合成响应 {"_intercepted":[{"Data":[...all...],"Count":N}]}（下游 shape 不变）。

        为何不复用 super().fetch()：列表页**只发一次** count-probe（PageSize 常为 1），被动拦截只能拿到 1 条。
        这里主动重放才是收全岗位的正解；捕获到 POST 即翻页，捕获不到（GET 式/异构租户）则回退被动拦截 (super)。

        命中规则：仅当真捕获到 GetJobAdPageList 的 POST 且至少重放出 1 条岗位才返回合成响应；
        否则回退 super().fetch()（保留原拦截链），再不行由 fetch() 落到 SSR。"""
        # ChinaSpaAdapter.fetch 会绑定 _origin/_host/_portal_prefix/list_urls，这里手动复刻同样绑定。
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        self.list_urls = [source_url]

        from playwright.sync_api import sync_playwright

        captured: dict = {}
        passive: List[dict] = []
        matchers = self.intercept_matches

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=PlaywrightAdapter.user_agent,
                viewport={"width": 1366, "height": 900}, locale="zh-CN")
            page = ctx.new_page()

            def on_request(req):
                # 捕获列表页自己发的 GetJobAdPageList POST（含 PortalId/Category/DisplayFields），供重放。
                if "GetJobAdPageList" in req.url and req.method == "POST" and not captured:
                    try:
                        captured["url"] = req.url
                        captured["body"] = json.loads(req.post_data or "{}")
                        captured["ct"] = (req.headers or {}).get("content-type", "application/json")
                    except Exception:
                        pass

            def on_response(resp):
                # 被动拦截兜底（与 PlaywrightAdapter.fetch 同口径）：捕获不到 POST 时仍有数据可用。
                try:
                    if matchers and not any(m in resp.url for m in matchers):
                        return
                    if "json" in (resp.headers or {}).get("content-type", "").lower():
                        passive.append(resp.json())
                except Exception:
                    pass

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=self.pw_timeout)
                page.wait_for_timeout(self.wait_ms)
            except Exception:
                pass

            rows: List[dict] = []
            total = None
            if captured.get("url") and isinstance(captured.get("body"), dict):
                body = dict(captured["body"])
                hdrs = {"content-type": captured.get("ct") or "application/json"}
                index = 0
                seen_ids = set()
                cap = resolve_list_cap(self._MAX_JOBS)
                brake = RepetitionBrake()
                while len(rows) < cap:
                    body["PageSize"] = self._PAGE_SIZE
                    body["PageIndex"] = index
                    try:
                        r = page.request.post(captured["url"], data=json.dumps(body), headers=hdrs)
                        jj = r.json()
                    except Exception as exc:
                        _log.warning("%s: PageIndex=%d 重放失败，保留已抓 %d 条：%s",
                                     self.name, index, len(rows), exc_brief(exc))
                        break
                    if not isinstance(jj, dict):
                        break
                    if total is None:
                        total = jj.get("Count") or jj.get("Total") or 0
                        reported = _int_or_none(jj.get("Count"))
                        if reported is None:
                            reported = _int_or_none(jj.get("Total"))
                        if reported is not None:
                            self.reported_total = reported
                    chunk = jj.get("Data") or []
                    if not isinstance(chunk, list) or not chunk:
                        break
                    fresh = _dedup_new(chunk, seen_ids, self._ID_FIELDS)
                    rows.extend(fresh)
                    if total and len(rows) >= total:
                        break
                    if brake.observe(_titles_of(fresh)):   # 与 httpx 路径同口径，见那边注释
                        self.coverage_stop_reason = "repetition_brake"
                        _log.info("%s: 重复度刹车 —— 连续 %d 条没有新角色，停在 %d/%s 条 host=%s",
                                  self.name, brake.stall_rows, len(rows), total, self._host)
                        break
                    if not _should_continue(fresh, chunk, total, self._PAGE_SIZE):
                        break
                    index += 1
                _mark_list_cap(self, rows, total, cap)
            browser.close()

        if rows:
            # 与 httpx 路径同口径：抓到 reported_total 全部才算完整（抓全率观测 honesty 契约）
            self.fetch_complete = (total is not None and len(rows) >= (total or 0))
            return json.dumps({"_intercepted": [{"Data": rows, "Count": total or len(rows)}]},
                              ensure_ascii=False)
        if passive:  # 没捕获到 POST/重放为空 → 回退被动拦截链（异构租户兼容）
            return json.dumps({"_intercepted": passive}, ensure_ascii=False)
        # 啥都没有 → 交给 fetch() 落到 SSR 分支
        raise RuntimeError(
            f"{self.name}: anti_bot_blocked — 未捕获 GetJobAdPageList POST 也无被动拦截 host={self._host}")

    def _fetch_ssr(self, source_url: str) -> str:
        """老版 SSR（C 型）：列表页 HTML 直出 per-job 锚点（无 JSON 接口）。
        渲染列表页 → 抽 jobId 锚点 → 探测本租户详情路径（render-verify，按 host 缓存）→ 拼 jd_url。
        探不到详情路径则 raise（记 partial_success，不入坏链）。"""
        from playwright.sync_api import sync_playwright

        origin = getattr(self, "_origin", "")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=PlaywrightAdapter.user_agent, locale="zh-CN").new_page()
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4500)
                anchors = [a for a in (page.evaluate(_BEISEN_SSR_ANCHOR_JS) or [])
                           if a.get("id") and a.get("name")]
                if not anchors:
                    raise RuntimeError(
                        f"beisen: SSR 列表页无 jobId/adId 锚点（非老版 SSR 或被反爬）host={self._host}")
                # 锚点自带完整详情 href（路径式租户，如 /job_show/{id}、/zpdetail/{id}）→ 直接用，
                # 不必再 render-verify 猜路由：页面给的就是真链接，猜反而可能猜错。
                direct = [a for a in anchors
                          if str(a.get("href") or "").startswith(("http://", "https://"))
                          and re.search(r"/(?:job[_-]?show|zpdetail|jobdetail|job[_-]?detail|positiondetail)/\d{4,}",
                                        str(a.get("href")), re.I)]
                if direct:
                    jobs, seen = [], set()
                    for a in direct:
                        jd = str(a["href"])
                        if jd in seen:
                            continue
                        seen.add(jd)
                        jobs.append({"title": a["name"], "jd_url": jd, "location": a.get("location")})
                    _beisen_ssr_fill_summaries(jobs)
                    return json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False)
                route = _BEISEN_ROUTE_CACHE.get(self._host)
                if not (isinstance(route, dict) and route.get("ssr_path")):
                    route = self._discover_ssr_route(page, origin, anchors)
                    if route:
                        _BEISEN_ROUTE_CACHE[self._host] = route
                if not (isinstance(route, dict) and route.get("ssr_path")):
                    raise RuntimeError(f"beisen: SSR 详情路径探测失败 host={self._host}")
                path, param = route["ssr_path"], route["ssr_param"]
                jobs, seen = [], set()
                for a in anchors:
                    jd = f"{origin}/{path}?{param}={a['id']}"
                    if jd in seen:
                        continue
                    seen.add(jd)
                    jobs.append({"title": a["name"], "jd_url": jd, "location": a.get("location")})
                return json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False)
            finally:
                browser.close()

    def _discover_ssr_route(self, page, origin: str, anchors: list):
        """老版 SSR 详情路径探测：用首个锚点 id × 候选 path/param render-verify，命中即 {ssr_path,ssr_param}。"""
        a_id = str(anchors[0]["id"])
        a_name = anchors[0]["name"]
        b_name = next((x["name"] for x in anchors[1:] if x["name"] != a_name), None)
        for path in _BEISEN_SSR_DETAIL_PATHS:
            for param in _BEISEN_SSR_PARAMS:
                url = f"{origin}/{path}?{param}={a_id}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    t = (page.title() or "")
                    if "not found" in t.lower() or t.strip() in ("404", "404 Not Found"):
                        continue  # 路径不存在 → 跳过昂贵的渲染等待
                    page.wait_for_timeout(3000)
                    if self._is_job_detail(page, a_name, b_name):
                        return {"ssr_path": path, "ssr_param": param}
                except Exception:
                    continue
        return None

    def parse(self, html: str):
        try:
            data = json.loads(html)
        except (ValueError, TypeError):
            return []
        shared = getattr(self, "_host", "") in _BEISEN_SHARED_TENANTS
        if isinstance(data, dict) and "_ssr_jobs" in data:  # 老版 SSR 产物
            if shared:
                # 老版 SSR / CMS / 卡片三条路径都不带招聘机构 → 只能整批贴 sources.company，正是要修的错。
                raise RuntimeError(
                    f"beisen: shared tenant {self._host} fell back to an SSR path without hiring entity; "
                    f"refuse to attribute every job to sources.company")
            out, seen = [], set()
            for j in data["_ssr_jobs"]:
                jd, title = j.get("jd_url"), j.get("title")
                if not (jd and title) or jd in seen:
                    continue
                seen.add(jd)
                policy = _SSR_TENANT_POLICY.get(urlparse(jd).netloc.lower())
                if policy:
                    self.retire_posted_before = _ssr_policy_retire_before(policy)
                if not _ssr_policy_allows(j, policy):
                    continue
                # job_type/education 老版 CMS 才有（列表列 + 详情页字段）；posted_at 卡片式 CMS 才有
                # （列表卡 <ol> 的发布日）。老调用方都不传这些 key → .get 返 None，行为逐字节不变。
                out.append(RawJob(company=self.company_name or "", title=title,
                                  location=j.get("location"), job_type=j.get("job_type"),
                                  summary=j.get("summary"), education=j.get("education"),
                                  jd_url=jd, apply_url=jd, posted_at=j.get("posted_at")))
            return out
        out = super().parse(html)  # 新版 JSON 拦截路径
        # 「列表明明有行、却一条都映射不出来」只有一个成因：详情路由用不了 → 每行 jd_url 是空串 →
        # 被质量门丢光。它以前**静默**成 success + 0 岗（复星医药连着 33 次、中核 / 京东方同病），
        # 而「0 岗」在下游会被当成「对方没岗了」。这不是 0 岗，是抓坏了，必须记 failed 让人看见。
        # ⚠️ 只在「有行 → 零产出」这一种组合下抛；真的返回空列表（对方确实没岗）照常返回 []。
        if not out and self._list_posts(html):
            raise RuntimeError(
                f"beisen: list returned rows but no job could be mapped "
                f"({getattr(self, '_host', '?')} → route={getattr(self, '_detail_route', None)!r}); "
                f"detail route unusable, refuse to report 0 jobs as success"
            )
        if shared and out:
            posts = self._list_posts(html)
            missing = sum(1 for p in posts if not beisen_hiring_entity(p))
            if posts and missing == len(posts):
                # 整批都没有招聘机构 = 字段没返回（请求体没点名 / 北森改了字段），不是「全是本家的岗」。
                # 放行就会静默退回「全贴 sources.company」，所以记 failed：库里保留上一轮归属正确的行。
                raise RuntimeError(
                    f"beisen: shared tenant {self._host} returned {len(posts)} rows without Org/"
                    f"ClassificationTwo; refuse to attribute every job to sources.company")
            if missing:
                _log.warning("%s: 共享租户 %s 有 %d/%d 行没有招聘机构，这几行沿用 sources.company",
                             self.name, self._host, missing, len(posts))
        return out

    def _list_posts(self, list_json: str):
        try:
            data = __import__("json").loads(list_json)
        except (ValueError, TypeError):
            return []
        posts = []
        for resp in data.get("_intercepted", []) or []:
            posts.extend(pp for pp in self._extract_posts(resp) if isinstance(pp, dict))
        return posts

    def _discover_detail_route(self, source_url: str, list_json: str):
        """探测本租户的详情路由（**单浏览器会话**，避免多会话连打同一 host 触发反爬）。
        策略①（主，最可靠）：渲染列表页 → 点击首个岗位卡 → 捕获跳转 URL → 把 id 值替换为 {id} 得到模板
          （适配 jobAdId/jobId × Id/JobAdId 各种约定，且对无 href 的 React 卡片也有效）。
        策略②（兜底）：在同一会话内猜常见详情 path × render-verify（返回 base 字符串，按 ?jobAdId={Id} 兜底）。
        返回 dict{template,idfield} / str(base) / None。"""
        posts = self._list_posts(list_json)
        if not posts:
            return None
        # `/api/` 宽匹配会把搜索条件 / 地区树 / 推荐岗等非岗位列表也拦进来，posts[0] 可能不是真岗位
        # （无 JobAdName/Id），甚至地区树节点也带 name+id 会被误判。北森真岗位恒有 JobAdName，
        # 故优先按 JobAdName 取真岗位；仅当无任何 JobAdName 时才退回通用 title/name（兼容异构租户）。
        def _collect(name_keys):
            out = []  # [(name, [(idfield, idval), ...])]
            for p in posts:
                nm = _first_str(p, name_keys)
                if not nm:
                    continue
                ids = [(f, v) for f, v in ((f, _first_str(p, (f,))) for f in self._ID_FIELDS) if v]
                if ids:
                    out.append((nm, ids))
            return out

        real = _collect(("JobAdName",)) or _collect(("title", "name", "jobTitle"))
        if not real:
            return None
        a_name, id_vals = real[0]
        b_name = next((nm for nm, _ in real[1:] if nm != a_name), None)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=PlaywrightAdapter.user_agent, locale="zh-CN")
            page = ctx.new_page()
            try:
                # 北森 SPA 持续轮询（tara-frontend 日志 / AI 机器人），networkidle 永不静默 → 30s 超时
                # → 整个探测被外层 except 吞成 None（NO-DETAIL-ROUTE）。改 domcontentloaded（与主 fetch 一致）。
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                # ① 猜测式（proven，对 chinalife/popmart/横店等直达详情 URL 可渲染的租户最稳，不回退）
                guessed = self._guess_route(page, source_url, id_vals[0][1], a_name, b_name)
                if guessed:
                    return guessed
                # ② 点击捕获兜底（救 React 详情页直达不渲染、需从列表点入的租户，如迈瑞）
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                el = self._first_job_element(page, a_name)
                if el is None:
                    return None
                before = page.url
                captured = None
                try:  # 多数北森详情在新标签打开
                    with ctx.expect_page(timeout=7000) as np:
                        el.click()
                    newp = np.value
                    newp.wait_for_load_state("domcontentloaded", timeout=7000)
                    captured = newp.url
                except Exception:  # 同标签内路由跳转
                    try:
                        page.wait_for_timeout(2500)
                        captured = page.url
                    except Exception:
                        captured = None
                if captured and captured != before:
                    for field, val in id_vals:
                        if val and val in captured:
                            return {"template": captured.replace(val, "{id}"), "idfield": field}
                return None
            except Exception:
                return None
            finally:
                browser.close()

    @staticmethod
    def _first_job_element(page, a_name: str):
        """定位首个岗位卡可点击元素：优先按岗位名文本匹配，兜底按北森常见 class。"""
        try:
            loc = page.get_by_text(a_name[:12], exact=False).first
            if loc and loc.count() > 0:
                return loc
        except Exception:
            pass
        for sel in ("div[class*=JobTitle]", "div[class*=TitleSection]", "div[class*=jobName]",
                    "a[class*=job]", ".job-name", ".position-name", "li[class*=job] a"):
            try:
                el = page.query_selector(sel)
                if el:
                    return el
            except Exception:
                continue
        return None

    def _guess_route(self, page, source_url: str, a_id: str, a_name: str, b_name):
        """同会话内猜常见详情 path × render-verify，返回命中的 detail base（origin+path，无 query）或 None。"""
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        segs = [s for s in (parsed.path or "").split("/") if s]
        bases = []
        if segs:
            bases.append("/" + "/".join(segs[:-1]))
        bases.append("/" + "/".join(segs))
        seen, cand_paths = set(), []
        for base in bases:
            for nm in _BEISEN_DETAIL_NAMES:
                path = (base.rstrip("/") + "/" + nm) if base.strip("/") else "/" + nm
                if path not in seen:
                    seen.add(path)
                    cand_paths.append(path)
        for path in cand_paths:
            url = f"{origin}{path}?jobAdId={a_id}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(3500)
                if self._is_job_detail(page, a_name, b_name):
                    return f"{origin}{path}"
            except Exception:
                continue
        return None

    @staticmethod
    def _is_job_detail(page, a_name: str, b_name) -> bool:
        """判断当前页是否为「岗位 a_name 的详情页」（而非列表页/无关页）。
        强信号：页面主标题（h1/jobName 类）含本岗位名 → 即使侧栏有「推荐职位」露出 b_name 也算命中。
        弱信号兜底：本岗位名在正文 且 列表里另一岗位名 b_name 不在正文（无并列岗位=非列表页）。"""
        content = page.content()
        if not a_name or a_name not in content:
            return False
        heading = page.evaluate(
            "()=>{const sels=['h1','[class*=jobName]','[class*=JobName]','[class*=positionName]',"
            "'[class*=PositionName]','[class*=job-title]','[class*=jobTitle]','[class*=JobTitle]'];"
            "for(const s of sels){const e=document.querySelector(s);"
            "const t=e&&(e.innerText||'').trim();if(t)return t;}return '';}") or ""
        core = a_name.split("（")[0].split("(")[0].strip()[:10]
        if core and core in heading:        # 主标题就是本岗位 → 详情页
            return True
        return not (b_name and b_name in content)  # 无并列岗位 → 非列表页

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口若直接给了 per-job 链接，优先用（最可靠）。
        raw = super()._resolve_url(post, job_id)
        if raw:
            return raw
        # 2) 用本租户探测到的详情路由。探不到则不拼（丢弃，杜绝坏链）。
        route = getattr(self, "_detail_route", None)
        if isinstance(route, dict):  # 点击捕获：{template, idfield}
            idval = _first_str(post, (route.get("idfield", "Id"),))
            return route["template"].format(id=idval) if idval and "{id}" in route.get("template", "") else ""
        if isinstance(route, str):  # 旧缓存：detail base 字符串，按 ?jobAdId={Id} 兜底
            uuid = _first_str(post, ("Id", "id", "jobAdId", "JobAdId"))
            return f"{route}?jobAdId={uuid}" if uuid else ""
        return ""


class CompanySpaAdapter(ChinaSpaAdapter):
    """通用企业官网 SPA 招聘站（各公司自建站）。

    拦截站点自身**所有 JSON** 接口，启发式抽取岗位；仅放行接口里带**真实 per-job 链接**的行，
    绝不拼/猜 URL。覆盖「各公司站」长尾，加源零代码（填公司名 + 招聘页地址 + adapter=company_spa）。
    """

    name = "company_spa"
    intercept_matches = ()  # 拦截所有 JSON
    detail_template = ""    # 不拼链接，只用接口里的真实 URL
    # 通用盲抓 = 「不知道对方是什么平台」，所以每次都从渲染后的页面认一次真实 ATS。
    # 认出来后由 gap_funnel_browser 换成真 adapter 重抓（万泰生物同一 URL：本类 0 个岗，moka 15 个）。
    capture_entry_hint = True
