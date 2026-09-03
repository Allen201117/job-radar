"""
Job Radar Crawler — 主入口。
由 GitHub Actions 每天调用，也可以本地手动运行。

用法：
  python run.py                  # 跑全部 enabled sources
  python run.py --source apple   # 只跑指定 source（按 adapter_name）
"""
import argparse
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import db
import jobs_db
import normalizer
import ops_runs
from robots import check_robots
from adapters.apple import AppleAdapter, AppleChinaAdapter
from adapters.baidu import BaiduAdapter
from adapters.jd import JdAdapter
from adapters.jd_campus import JdCampusAdapter
from adapters.haier import HaierAdapter
from adapters.hikvision import HikvisionAdapter
from adapters.iguopin import IguopinAdapter
from adapters.siemens import SiemensAdapter
from adapters.avature import AvatureAdapter
from adapters.tencent import TencentAdapter
from adapters.tencent_campus import TencentCampusAdapter
from adapters.bytedance import BytedanceAdapter, BytedanceCampusAdapter
from adapters.feishu import NioAdapter, XpengAdapter, HorizonAdapter, XiaomiAdapter, FeishuGenericAdapter
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter
from adapters.ashby import AshbyAdapter
from adapters.smartrecruiters import SmartRecruitersAdapter
from adapters.successfactors import SuccessFactorsAdapter
from adapters.workday import WorkdayAdapter
from adapters.eightfold import EightfoldAdapter
from adapters.oracle import OracleAdapter
from adapters.china_ats import MokaAdapter, BeisenAdapter, CompanySpaAdapter
from adapters.hotjob import HotJobAdapter
from adapters.wt import WtAdapter
from adapters.amazon import AmazonAdapter
from adapters.phenom import PhenomAdapter
from adapters.microsoft import MicrosoftAdapter
from adapters.google import GoogleAdapter
from adapters.netease import NeteaseAdapter
from adapters.oppo import OppoAdapter
from adapters.xiaohongshu import XiaohongshuAdapter
from adapters.alibaba import AlibabaAdapter, AlibabaCampusAdapter
from adapters.huawei import HuaweiAdapter
from adapters.ctrip import CtripAdapter
from adapters.meituan import MeituanAdapter, MeituanCampusAdapter
from adapters.kuaishou import KuaishouAdapter
from adapters.kuaishou_campus import KuaishouCampusAdapter
from adapters.bilibili import BilibiliAdapter
from adapters.pinduoduo import PinduoduoAdapter
from adapters.vivo import VivoAdapter
from adapters.byd import BydAdapter
from adapters.sf_express import SfExpressAdapter
from adapters.tencent_music import TencentMusicAdapter
from adapters.antgroup import AntGroupAdapter
from adapters.mihoyo import MihoyoAdapter
from adapters.gllue import GllueAdapter
from adapters.cnstaff import CnstaffAdapter
from adapters.midea import MideaAdapter
from adapters.cmb import CmbAdapter
from adapters.cmbc import CmbcAdapter
from adapters.gree import GreeAdapter


SUMMARY_STORAGE_LIMIT = int(os.environ.get("JOB_SUMMARY_STORAGE_LIMIT", "500") or "500")


def cap_summary_for_storage(summary):
    """Keep jobs.summary small enough for the hot database table."""
    if summary is None:
        return None
    text = str(summary).strip()
    if not text:
        return None
    if len(text) <= SUMMARY_STORAGE_LIMIT:
        return text
    return text[: max(0, SUMMARY_STORAGE_LIMIT - 3)].rstrip() + "..."


def _source_regions(source):
    raw = source.get("regions") if isinstance(source, dict) else None
    if not raw:
        return {"CN"}
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") and text.endswith("}"):
            raw = text[1:-1].split(",")
        else:
            raw = text.split(",")
    return {str(r).strip() for r in raw if str(r).strip()} or {"CN"}


ADAPTERS = {
    "apple": AppleAdapter(),
    "apple_cn": AppleChinaAdapter(),  # Apple 在华岗位（保留全球 apple 源）
    "baidu": BaiduAdapter(),
    "jd": JdAdapter(),
    # 京东校招独立门户 campus.jd.com（jd.py 只抓社招 zhaopin.jd.com）
    "jd_campus": JdCampusAdapter(),
    "haier": HaierAdapter(),
    # 海康校招独立域名 campushr.hikvision.com（社招 talent.hikvision.com 被 EdgeOne 拦）
    "hikvision": HikvisionAdapter(),
    "iguopin": IguopinAdapter(),  # 国聘央企/国企公开职位搜索 API
    "siemens": SiemensAdapter(),
    "avature": AvatureAdapter(),  # Avature SearchJobs SSR 通用层（详情链接直接取卡片 href）
    "tencent": TencentAdapter(),
    # 腾讯校招独立域名 join.qq.com（careers.tencent.com 的 attrId=2 只有 16 个海外岗）
    "tencent_campus": TencentCampusAdapter(),
    "bytedance": BytedanceAdapter(),
    "bytedance_campus": BytedanceCampusAdapter(),  # 字节校招/实习（与社招同平台）
    "nio_feishu": NioAdapter(),
    "xpeng_feishu": XpengAdapter(),
    "horizon_feishu": HorizonAdapter(),
    "xiaomi_feishu": XiaomiAdapter(),
    # 外企 ATS（通用适配器，按公司加 sources 行；parse 已裁到在华岗位）
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),  # 大量在华跨国企业用此 ATS（外企100强主力）
    "successfactors": SuccessFactorsAdapter(),  # SAP SF Career Site Builder SSR（欧洲/亚洲系大厂 careers 站主力）
    "workday": WorkdayAdapter(),  # 外企100强主力：CXS API + location facet 服务端过滤到在华
    "eightfold": EightfoldAdapter(),  # 外企 ATS：eightfold.ai 公开接口 + location 服务端收窄到在华
    "oracle": OracleAdapter(),  # 外企自建门户主力：Oracle 招聘云 CE API + locationsFacet 过滤到在华
    "amazon": AmazonAdapter(),  # 外企自建巨头：Amazon.jobs 公开 search.json 按国家码筛在华
    "phenom": PhenomAdapter(),  # 外企自建巨头：Phenom People 公开 /api/jobs（AMD/L'Oréal 等）
    "microsoft": MicrosoftAdapter(),  # 外企自建巨头：MS pcsx httpx（apply.careers 子域绕 Akamai）
    "google": GoogleAdapter(),  # 外企自建巨头：Google careers 无头浏览器 DOM 抓取
    # 中国本土 ATS / 企业官网 SPA（通用适配器，按公司加 sources 行；host 从 source_url 动态解析）
    "moka": MokaAdapter(),
    "beisen": BeisenAdapter(),
    "company_spa": CompanySpaAdapter(),
    "feishu": FeishuGenericAdapter(),  # 飞书招聘数据驱动通用层（国内版 Workday）：host 从 source_url 解析
    "hotjob": HotJobAdapter(),  # HotJob / wecruit 通用层：TCL 等国内企业公开招聘站
    "wt": WtAdapter(),  # 老版 WinTalent：伊利/中广核/中国电信/现代等,直连 position/list JSON,零浏览器
    "netease": NeteaseAdapter(),  # 网易自建门户：hr.163.com queryPage 公开接口,零浏览器
    "oppo": OppoAdapter(),  # OPPO 校招门户：careers.oppo.com openapi 公开接口,零浏览器
    "xiaohongshu": XiaohongshuAdapter(),  # 小红书自建门户：job.xiaohongshu.com pageQueryPosition,零浏览器
    "alibaba": AlibabaAdapter(),  # 阿里集团 BU 门户通用层：position/search 公开接口,host 动态解析,零浏览器
    # 阿里校招频道：同接口不传 channel 即校招默认集（2026-08-04 live 对拍），payload 自证 freshman/批次名防误灌
    "alibaba_campus": AlibabaCampusAdapter(),
    "huawei": HuaweiAdapter(),  # 华为自建门户：career.huawei.com getJob 公开接口,零鉴权零浏览器
    "ctrip": CtripAdapter(),  # 携程自建门户：careers.ctrip.com getJobAd 公开接口,零浏览器
    "meituan": MeituanAdapter(),  # 美团自建门户：getJobList 公开接口,零浏览器
    # 美团校招：同接口带板块过滤 jobType=[{code:4,subCode:[1,2,6]}]（对象数组,2026-08-04 截获真实请求确定）
    "meituan_campus": MeituanCampusAdapter(),
    "kuaishou": KuaishouAdapter(),  # 快手自建门户：页面 JS 签名,Playwright 拦截 open positions
    # 快手校招是另一个站(campus.kuaishou.cn)且接口公开：纯 httpx 零鉴权,项目码动态发现(2026-08-04 live)
    "kuaishou_campus": KuaishouCampusAdapter(),
    "bilibili": BilibiliAdapter(),  # B站自建门户：匿名 CSRF + positionList 公开接口,零浏览器
    "pinduoduo": PinduoduoAdapter(),  # 拼多多校招门户：position/list 公开接口,零浏览器
    "vivo": VivoAdapter(),  # vivo 社招门户：portal/page 公开接口,零浏览器
    "byd": BydAdapter(),  # 比亚迪社招：公开列表 + 浏览器批量生成前端加密详情 URL
    "sf_express": SfExpressAdapter(),  # 顺丰社招：SearchJob.do 公开接口,零浏览器
    "tencent_music": TencentMusicAdapter(),  # 腾讯音乐自建门户：job/list + uc-job/list 公开接口,零浏览器
    "antgroup": AntGroupAdapter(),  # 蚂蚁集团自建门户：hrcareersweb position/search 公开接口,零浏览器
    "mihoyo": MihoyoAdapter(),  # 米哈游自建门户：ats-portal v1/job/list+info 公开接口,零浏览器
    "gllue": GllueAdapter(),  # Gllue Next.js SSR 通用层，host 从 source_url 动态解析
    "cnstaff": CnstaffAdapter(),  # 聘客 cnstaff joblist API 通用层，host/tenant 动态解析
    "midea": MideaAdapter(),  # 美的集团自建门户：公开 position/list 接口，零浏览器
    "cmb": CmbAdapter(),  # 招商银行自建门户：公开社会招聘接口，零浏览器
    "cmbc": CmbcAdapter(),  # 中国民生银行自建门户：公开社会招聘接口，零浏览器
    "gree": GreeAdapter(),  # 格力自建门户：公开校招/社招接口，零浏览器
}

# 中国本土公司源（每日后台爬取高优）：本土覆盖优先级 > 外企，排在外企 ATS 前先抓。
# 扩本土覆盖（新增本土 adapter）是当前最高优先 backlog，见 CLAUDE.md「核心产品原则#3」。
DOMESTIC_ADAPTERS = {
    "baidu", "jd", "bytedance", "bytedance_campus", "tencent",
    "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu", "haier", "iguopin",
    "moka", "beisen", "company_spa", "feishu", "hotjob", "wt", "netease", "oppo", "xiaohongshu", "alibaba", "alibaba_campus", "huawei", "ctrip",
    "meituan", "meituan_campus", "kuaishou", "kuaishou_campus", "bilibili", "pinduoduo", "vivo", "byd", "sf_express",  # 本土 ATS / 企业官网 SPA（扩覆盖主攻方向）
    "tencent_music", "antgroup", "mihoyo", "gllue", "cnstaff", "midea", "cmb", "cmbc", "gree",  # 自建门户公开接口（零浏览器；cmb=招商银行，cmbc=中国民生银行）
}


# ── P4 并发提速：按 adapter 抓取方式分档 ──────────────────────────────────────────
# httpx-safe = 纯 httpx 抓取、不起浏览器，线程安全可并发。故意用「白名单」而非「黑名单」：
# 未知 / 浏览器 adapter 一律落串行档（fail-safe），杜绝把 Playwright（sync API，非线程安全）
# 的 adapter 误并发跑崩夜间 cron。新增 httpx adapter 时显式加进来才享受并发。
_HTTPX_SAFE_ADAPTERS = {
    "apple", "apple_cn", "baidu", "jd", "haier", "iguopin", "siemens", "tencent", "tencent_campus", "hikvision",
    "greenhouse", "lever", "ashby", "smartrecruiters", "successfactors", "workday", "eightfold",
    "oracle", "amazon", "phenom", "microsoft", "hotjob", "wt",
    "netease", "oppo", "xiaohongshu", "alibaba", "alibaba_campus", "huawei", "ctrip",
    "meituan", "meituan_campus", "kuaishou_campus", "bilibili", "pinduoduo", "vivo", "sf_express",  # 已逐一核实为纯 httpx fetch
    "tencent_music", "antgroup", "mihoyo", "avature", "gllue", "cnstaff", "midea", "cmb", "cmbc", "gree",  # 公开接口/SSR，纯 httpx
    # 字节：jobs.bytedance.com posts API 已改为纯 httpx offset/limit 全量翻页；
    # sources.crawl_method 仍由运维侧改库，本白名单只控制代码侧并发档。
    "bytedance", "bytedance_campus",
    # feishu 家族：posts API 冷 httpx 直出岗位+正文（2026-06-28 实测 generic/nio/xpeng/xiaomi/zhipu/xtool
    # 全可达），httpx-first + 浏览器回退见 adapters/feishu.py；进 daily-crawl 4×/天（原仅 enrich-crawl 1×/天）。
    "feishu", "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu",
}


def _is_httpx_safe(adapter_name) -> bool:
    return (adapter_name or "") in _HTTPX_SAFE_ADAPTERS


def _source_is_httpx_safe(s) -> bool:
    """单源是否 httpx-safe。beisen 是 **per-source**：详情路由已缓存的租户能纯 httpx（进快车道），
    未缓存的（含老版 SSR/异构，无 JSON API）必须留浏览器档——故不能整体把 beisen 加进 _HTTPX_SAFE_ADAPTERS。"""
    adapter = s.get("adapter_name") or ""
    if adapter == "beisen":
        from adapters.china_ats import beisen_httpx_ready
        return beisen_httpx_ready(s.get("source_url") or "")
    return _is_httpx_safe(adapter)


def _partition_by_tier(sources):
    """拆成 (并发档 httpx-safe, 串行档 浏览器/未知)，各自保持原顺序（本土优先排序不被打乱）。"""
    concurrent, serial = [], []
    for s in sources:
        (concurrent if _source_is_httpx_safe(s) else serial).append(s)
    return concurrent, serial


def _shard_host_of(s):
    from urllib.parse import urlparse
    try:
        return urlparse(s.get("source_url") or "").netloc or ""
    except Exception:
        return ""


# 多租户 ATS 平台主机：同一 host 下每个 tenant 是**不同公司**各自的招聘页，对端是 SaaS 平台
# 而非某家公司的小服务器 → 按 tenant 拆到不同片是安全的。
# 佐证：enrich-backlog-browser.yml 早已在生产每天用 6 个 runner 并行渲染 app.mokahr.com
# （每片 1500 岗），从未触发限流。
# ⚠️ **绝不要**把 wecruit.hotjob.cn 这类加进来——那是单一招聘服务的共享后端，
# 2026-06-10 实锤源级并发即 Errno 35 全灭（89/102 源），必须整体落同一片。
_MULTI_TENANT_SHARD_HOSTS = {"app.mokahr.com", "app-tc.mokahr.com"}


def _shard_key_of(s):
    """分片单位 = 「不希望被多 runner 同时轰的那个对端」。默认就是 host；
    多租户平台细到 host+租户路径前两段（moka 形如 /apply/{tenant}/{id}）。

    动机（2026-07-28 实测 run 30297659211）：串行浏览器档 280 源里 265 源同挂 app.mokahr.com
    → 「同 host 同片」把它们整体压进 enrich(1) 一片，该片 398 源（含 265 个浏览器串行源，
    ~1min/源）跑满 180min 被 GitHub 取消，其余 5 片 12-34min 就跑完闲着。连挂 4 天。"""
    host = _shard_host_of(s)
    if host not in _MULTI_TENANT_SHARD_HOSTS:
        return host
    from urllib.parse import urlparse
    segs = [p for p in urlparse(s.get("source_url") or "").path.split("/") if p][:2]
    return f"{host}/{'/'.join(segs)}" if segs else host


def _shard_by_host(sources, shard_index, shard_count):
    """按「分片单位」分桶分片（替代旧 round-robin 源切片 `sources[i::n]`）。

    重档从「按天 1/shard_count 轮转单 runner」改为「N 片同时并行跨 runner」后，必须保证
    **同一分片单位的所有源落同一片** —— 否则同主机源被切到不同 runner → 多 runner 并发抓同一台
    服务器 → 触发限流（Errno 35，正是单 runner 内 _group_by_host 串行要防的；2026-06-10 实锤
    wecruit 102 源）。分片单位见 _shard_key_of（默认 host，多租户平台按租户细分）。

    分配用**贪心装箱**（LPT：源数降序，每个 key 丢进当前最轻的片），而非旧的 `i % shard_count`
    轮转——轮转只均衡「key 的个数」，把 102 源的大 key 和 1 源的小 key 等价看待，实测各片源数
    能差到 3 倍（112 vs 398）。按源数装箱后各片工作量才真的接近。
    ⚠️ 排序与平局一律用 (源数, key 名) 决定，**禁止用 Python 的 hash()**——各 runner 是独立进程，
    hash() 每进程加盐不同会算出不一致的映射（有的源被漏抓、有的被两片重抓）。
    保持各源原顺序（本土优先不被打乱）。shard_index 须由调用方先 %= shard_count 归一。"""
    counts: dict = {}
    for s in sources:
        key = _shard_key_of(s)
        counts[key] = counts.get(key, 0) + 1

    load = [0] * shard_count
    key_shard: dict = {}
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        target = min(range(shard_count), key=lambda j: (load[j], j))
        key_shard[key] = target
        load[target] += n

    return [s for s in sources if key_shard.get(_shard_key_of(s)) == shard_index]


# 并发档每线程独立 supabase 客户端。根因（2026-06-10 实锤，traceback 指向
# httpcore/_sync/http2.py + postgrest）：supabase-py 客户端走 HTTP/2 单连接多路复用，
# 被多个 worker 线程共享时并发读同一 socket → Errno 35（Resource temporarily unavailable）
# 大面积失败（hotjob 89/102 源全灭）。每线程一个客户端 = 每线程自己的连接，根治。
_TLS = threading.local()


def _get_thread_supabase():
    if not hasattr(_TLS, "sb"):
        _TLS.sb = db.get_supabase()
    return _TLS.sb


def _get_thread_jobs_conn():
    """Phase 1：每线程独立的自建香港 jobs 库连接（psycopg2 连接非线程安全，须每线程一个）。

    ⚠️ 必须每次校验存活、断了重连（jobs_db.live_conn）：重档单片要跑 1-3 小时，跨境链路被中间设备
    掐断后 psycopg2 会把连接标 closed，若继续复用这条死连接，之后每个源的 upsert 全是
    `InterfaceError: connection already closed` —— 2026-07-25 实测某片 20:09 断链后剩余 ~1h50m
    抓的岗一行没写进库，还照样烧满 180min 超时。重连后最多只损失断链当下那一批。"""
    _TLS.jobs_conn = jobs_db.live_conn(getattr(_TLS, "jobs_conn", None))
    return _TLS.jobs_conn


def _group_by_host(sources):
    """并发档按主机分队：同主机一队（队内串行=礼貌爬取），跨主机并行。
    动机（2026-06-10 实锤）：102 个 hotjob 源几乎全在 wecruit.hotjob.cn 一台主机上，
    源级并发=对单服务器并发轰炸 → 对端限流，56 源 Errno 35 全灭。按主机分队后同主机
    请求天然串行，跨主机才吃并发，既礼貌又不触发限流。队序按首现顺序（保本土优先）。"""
    from urllib.parse import urlparse

    queues, index = [], {}
    for s in sources:
        try:
            host = urlparse(s.get("source_url") or "").netloc or f"_bad_{len(queues)}"
        except Exception:
            host = f"_bad_{len(queues)}"
        if host not in index:
            index[host] = len(queues)
            queues.append([])
        queues[index[host]].append(s)
    return queues


def _process_one_source(source, supabase) -> dict:
    """处理单个源：robots → should_skip → fetch → parse → 质量门 → upsert。
    返回 {status, created, updated}；**永不抛异常**（并发档 ex.map 迭代结果时不会炸整批）。
    status：success/partial_success=有效入库；empty/no_valid=无可入库岗；skipped=robots/预检跳过；failed=未知 adapter/异常。"""
    company = source["company"]
    adapter_name = source.get("adapter_name") or ""
    source_url = source["source_url"]
    source_id = source["id"]

    adapter = ADAPTERS.get(adapter_name)
    if not adapter:
        print(f"  [skip] {company}: 未找到 adapter '{adapter_name}'")
        try:
            run_id = db.create_crawl_run(supabase, source_id)
            db.update_crawl_run(supabase, run_id, "failed",
                                error_message=f"Unknown adapter: {adapter_name}")
        except Exception as e:  # DB 瞬时错误（如 Errno 35）也不许炸穿
            print(f"    crawl_run 记录失败: {e}")
        return {"status": "failed", "created": 0, "updated": 0}

    # 每源独立 adapter 实例 —— 并发正确性根治。adapter 实例持有 per-source 可变状态（workday/oracle
    # 在 fetch 里按 source_url 设 self._host/_site/_cxs_base，末尾把 self._host 打进返回 payload）。
    # 并发档按主机多线程**共享 ADAPTERS 单例**时，线程间互相覆写这些字段 → 岗位被打上别家租户的 host →
    # jd_url 张冠李戴、公开站清一色 404（实测曾 98.8% Workday 在库岗位中招）。每源 type()() 新建独立
    # 实例隔离状态：adapter 均无自定义 __init__、浏览器在 fetch 内才起，构造开销可忽略。
    adapter = type(adapter)()
    adapter.regions = _source_regions(source)

    print(f"  [{adapter_name}] {company} ({source_url})")
    # run_id 的创建必须在 try 内：高负载下 Supabase 偶发 Errno 35（实锤于 2026-06-10 hotjob 全量
    # 并发跑），在 try 外抛出会炸穿「永不抛异常」约定 → ex.map 迭代时掀翻整批并发档。
    run_id = None

    try:
        run_id = db.create_crawl_run(supabase, source_id)
        # 1. robots check
        robots_result = check_robots(source_url)
        if not robots_result["allowed"]:
            print(f"    robots blocked: {robots_result['reason']}")
            db.update_crawl_run(supabase, run_id, "skipped",
                                error_message=f"robots.txt: {robots_result['reason']}")
            return {"status": "skipped", "created": 0, "updated": 0}

        # 2. pre-check
        skip_reason = adapter.should_skip(source_url)
        if skip_reason:
            print(f"    skip: {skip_reason}")
            db.update_crawl_run(supabase, run_id, "skipped",
                                error_message=skip_reason)
            return {"status": "skipped", "created": 0, "updated": 0}

        # 3. fetch
        #    cutoff = 开抓前时刻：本次再见到的岗 upsert 会把 last_seen_at 刷成 > cutoff，
        #    故抓全后 last_seen_at < cutoff 的 active 岗 = 本次列表缺席 = 下架（list-absence 探活）。
        cutoff = jobs_db._now() if jobs_db.enabled() else None
        print(f"    fetching...")
        html = adapter.fetch(source_url)

        # 4. parse
        raw_jobs = adapter.parse(html)
        print(f"    parsed {len(raw_jobs)} jobs")

        # 抓全率可观测（阶段①）：fetch 时 adapter 已填 reported_total/fetch_complete。
        # 有 total 才判 complete；无 total（纯 HTML/接口无此字段）→ complete=None 不可判定（诚实盲区）。
        _cov_total = getattr(adapter, "reported_total", None)
        _cov_complete = getattr(adapter, "fetch_complete", False) if _cov_total is not None else None

        if not raw_jobs:
            db.update_crawl_run(supabase, run_id, "success",
                                jobs_found=0,
                                reported_total=_cov_total, coverage_complete=_cov_complete)
            return {"status": "empty", "created": 0, "updated": 0}

        valid_jobs = []
        invalid_reasons = {}
        for raw in raw_jobs:
            is_valid, reason = normalizer.validate_job_quality(raw, source_url)
            if is_valid:
                valid_jobs.append(raw)
            else:
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

        if not valid_jobs:
            reason_text = ", ".join(
                f"{reason}: {count}" for reason, count in invalid_reasons.items()
            )
            print(f"    no high-quality jobs: {reason_text}")
            db.update_source_timestamp(supabase, source_id)
            db.update_crawl_run(
                supabase,
                run_id,
                "partial_success",
                jobs_found=len(raw_jobs),
                error_message=(
                    "Parsed rows, but none had high-quality job detail URLs. "
                    f"{reason_text}"
                ),
                reported_total=_cov_total, coverage_complete=_cov_complete,
            )
            return {"status": "no_valid", "created": 0, "updated": 0}

        # 5. normalize & 批量 upsert
        #    逐岗 upsert 每岗 2 次 Supabase REST（先查后写）是快档 ~30min 瓶颈（全量数万岗→6-10万往返）。
        #    整源攒成一批，db.upsert_jobs_batch 压成「1 次批量 select + 分块 upsert/insert」。
        job_batch = []
        for raw in valid_jobs:
            job_data = normalizer.normalize(raw, source_id=source_id, company=company)
            job_data["summary"] = cap_summary_for_storage(job_data.get("summary"))

            job_batch.append(job_data)

        # jobs 已迁自建香港 PG（Phase 1）：配了 JOBS_DATABASE_URL 写香港库；否则写 Supabase。
        if jobs_db.enabled():
            created, updated = jobs_db.upsert_jobs_batch(_get_thread_jobs_conn(), job_batch)
        else:
            created, updated = db.upsert_jobs_batch(supabase, job_batch)

        # 5b. list-absence 探活（仅 HK 库 + adapter 抓全 + 显式支持）：本次全量列表缺席的 active 岗 → 下架。
        #     env LIVENESS_ABSENCE_APPLY=true 才落库；但 LIVENESS_ABSENCE_OBSERVE 里的 adapter 强制 dry-run
        #     （新接入的源先观察占比，确认列表只返在招岗、不误杀，再从 observe 名单移除开 apply）。默认 beisen 观察。
        if (cutoff is not None and getattr(adapter, "supports_absence_liveness", False)
                and getattr(adapter, "fetch_complete", False)):
            try:
                _observe = {x.strip() for x in os.environ.get("LIVENESS_ABSENCE_OBSERVE", "beisen").split(",") if x.strip()}
                apply_absence = (os.environ.get("LIVENESS_ABSENCE_APPLY", "").lower() in ("1", "true", "yes")
                                 and adapter_name not in _observe)
                ab = jobs_db.sweep_absent_jobs(_get_thread_jobs_conn(), source_id, cutoff, apply=apply_absence)
                if ab["candidates"]:
                    print(f"    [absence] active={ab['active']} absent={ab['candidates']} "
                          f"expired={ab['expired']} action={ab['action']}")
            except Exception as e:  # 探活失败绝不影响抓取主流程
                print(f"    [absence] 跳过(异常不阻断): {type(e).__name__}: {e}")

        # 6. update source timestamp
        db.update_source_timestamp(supabase, source_id)

        # 7. update crawl_run
        db.update_crawl_run(
            supabase,
            run_id,
            "partial_success" if invalid_reasons else "success",
            jobs_found=len(valid_jobs),
            jobs_created=created,
            jobs_updated=updated,
            error_message=(
                "Skipped low-quality rows: "
                + ", ".join(
                    f"{reason}: {count}"
                    for reason, count in invalid_reasons.items()
                )
                if invalid_reasons
                else None
            ),
            reported_total=_cov_total, coverage_complete=_cov_complete,
        )

        if invalid_reasons:
            print(f"    skipped invalid rows: {invalid_reasons}")
        print(f"    created={created}, updated={updated}")
        return {"status": "partial_success" if invalid_reasons else "success",
                "created": created, "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"    FAILED: {error_msg}")
        traceback.print_exc()
        try:
            if run_id is not None:
                db.update_crawl_run(supabase, run_id, "failed",
                                    error_message=error_msg[:1000])
        except Exception as e2:  # 失败路径里 DB 再抛（同类瞬时错误）也不许炸穿
            print(f"    crawl_run 记录失败: {e2}")
        return {"status": "failed", "created": 0, "updated": 0}


def run_crawl(filter_adapter: str = None, tier: str = "all",
              shard_index: int = 0, shard_count: int = 1,
              sources_override: list = None):
    """全库抓取。sources_override 非空时只抓这批源（调用方已自行选源、已过滤 enabled），
    用于校招高频车道等「按业务口径挑一小撮源加密抓」的场景（见 crawler/campus_crawl.py）。
    分档/分片/本土优先等下游逻辑对两条路径完全一致，避免车道走出与主链路不同的抓取行为。"""
    supabase = db.get_supabase()
    sources = list(sources_override) if sources_override is not None else db.get_sources(supabase)

    if not sources:
        print("[crawler] 没有 enabled sources，退出。")
        return

    if filter_adapter:
        sources = [s for s in sources if s.get("adapter_name") == filter_adapter]
        if not sources:
            print(f"[crawler] 没有匹配 adapter_name='{filter_adapter}' 的 enabled source，退出。")
            return

    # 本土优先：CI 时间有限时先抓中国本土公司源（高优），外企 ATS 殿后。
    sources.sort(key=lambda s: 0 if (s.get("adapter_name") or "") in DOMESTIC_ADAPTERS else 1)
    domestic_n = sum(1 for s in sources if (s.get("adapter_name") or "") in DOMESTIC_ADAPTERS)
    # P4 分档：httpx-safe 源并发抓（线程池，墙钟不再逐个叠加），浏览器(Playwright 非线程安全)/未知源串行抓。
    concurrent_sources, serial_sources = _partition_by_tier(sources)
    # 分档：快档 daily 只跑 httpx 并发档；重档 enrichment 跑 browser 串行档（或 all 全量）。默认 all=两档都跑（向后兼容）。
    if tier == "httpx":
        serial_sources = []
    elif tier == "browser":
        concurrent_sources = []
    # 源分片：按主机分桶（_shard_by_host），同主机源落同一片。重档现为「N 片并行跨 runner」（matrix），
    # 全量一次覆盖；旧「按天 1/shard_count 轮转单 runner」也兼容（仍是合法分片）。默认 shard_count=1 = 不分片。
    # 注意：按主机分桶（非源 round-robin）是并行跨 runner 的正确性前提——防同主机被多 runner 并发轰致限流。
    if shard_count > 1:
        shard_index %= shard_count
        concurrent_sources = _shard_by_host(concurrent_sources, shard_index, shard_count)
        serial_sources = _shard_by_host(serial_sources, shard_index, shard_count)
    workers = max(1, int(os.environ.get("CRAWL_CONCURRENCY", "6") or "6"))
    active_n = len(concurrent_sources) + len(serial_sources)
    print(f"[crawler] tier={tier} shard={shard_index}/{shard_count}；本次抓取 {active_n}/{len(sources)} 源"
          f"（本土优先 {domestic_n} / 外企 {len(sources) - domestic_n}）"
          f"；并发档 {len(concurrent_sources)} 源 × {workers} 线程 / 串行档 {len(serial_sources)} 源（浏览器）...")

    results = []
    # 并发档先跑（httpx 快，CI 即便超时也先把这批收完）；workers=1 时退化为串行（安全阀，可用 CRAWL_CONCURRENCY=1 回退）。
    # 并发单位 = 主机队列（同主机串行防把单服务器打爆，跨主机并行吃满 workers）。
    if concurrent_sources and workers > 1:
        host_queues = _group_by_host(concurrent_sources)
        print(f"[crawler] 并发档按主机分 {len(host_queues)} 队（同主机串行、跨主机并行）")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # 注意每线程用 _get_thread_supabase()（线程局部客户端），不共享主线程的 supabase。
            for queue_results in ex.map(
                    lambda q: [_process_one_source(s, _get_thread_supabase()) for s in q],
                    host_queues):
                results.extend(queue_results)
    else:
        results.extend(_process_one_source(s, supabase) for s in concurrent_sources)
    # 串行档：浏览器源逐个跑（domestic-browser 已被本土优先排序排在前，优先抓）。
    for s in serial_sources:
        results.append(_process_one_source(s, supabase))

    total_created = sum(r["created"] for r in results)
    total_updated = sum(r["updated"] for r in results)
    success_count = sum(1 for r in results if r["status"] in ("success", "partial_success"))
    fail_count = sum(1 for r in results if r["status"] == "failed")
    # "empty" = 抓取链路完全正常、只是这个源当下一个岗都没有（列表返回空）。
    # 它既不是成功也不是失败，此前两个计数器都不统计它 → 调用方看到 0 成功 0 失败，
    # 分不清「源坏了」和「源是空的」。校招场景下这个区分是刚需：板块在正式批开闸前
    # 空着是常态，误判成失败会让它吃长退避、错过整个开闸窗口（campus_board_verify 实测踩到）。
    empty_count = sum(1 for r in results if r["status"] == "empty")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    partial_count = sum(1 for r in results if r["status"] in ("partial_success", "no_valid"))
    failed_ratio = (fail_count / active_n) if active_n else 0
    all_empty = active_n > 0 and empty_count == active_n
    # ops_runs 只允许 success/partial/failed；全空是可观测预警而不是执行失败，
    # 因此保留 success 并以 all_empty 指标供 ops-watchdog 识别。
    ops_status = "failed" if failed_ratio >= 0.5 else "success"
    ops_runs.record_ops_run(
        supabase,
        "daily_crawl",
        {
            "sources_total": active_n,
            "success_count": success_count,
            "empty_count": empty_count,
            "failed_count": fail_count,
            "partial_count": partial_count,
            "jobs_found_total": total_created + total_updated,
            "all_empty": all_empty,
        },
        status=ops_status,
    )

    print(f"\n[crawler] 完成: {success_count} 成功, {fail_count} 失败, "
          f"{empty_count} 空源, {skipped_count} 跳过, "
          f"created={total_created}, updated={total_updated}")
    return {"created": total_created, "updated": total_updated,
            "success": success_count, "failed": fail_count,
            "empty": empty_count, "skipped": skipped_count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Radar Crawler")
    parser.add_argument("--source", type=str, default=None,
                        help="只跑指定 adapter (apple/baidu/jd/haier/siemens)")
    parser.add_argument("--tier", choices=["all", "httpx", "browser"],
                        default=(os.environ.get("CRAWL_TIER") or "all"),
                        help="all=两档都跑(默认/全量) | httpx=只跑并发档(快档 daily) | browser=只跑浏览器串行档(重档)")
    parser.add_argument("--shard-index", type=int,
                        default=int(os.environ.get("CRAWL_SHARD_INDEX", "0") or "0"),
                        help="源分片轮转：本次跑第 index 片（0-based；重档按星期几传 0-6）")
    parser.add_argument("--shard-count", type=int,
                        default=int(os.environ.get("CRAWL_SHARD_COUNT", "1") or "1"),
                        help="源分片轮转：共分几片（重档按天 1/7 轮转传 7；默认 1=不分片）")
    args = parser.parse_args()

    # 按需「浏览器发现」模式（GitHub Actions workflow_dispatch 触发，通过 DISCOVERY_* 环境变量传参）。
    # 命中则跑发现并退出；否则走常规全量/单源抓取（受 --tier / --shard-* 收窄）。
    import discovery
    if discovery.run_from_env():
        sys.exit(0)

    run_crawl(filter_adapter=args.source, tier=args.tier,
              shard_index=max(0, args.shard_index),
              shard_count=max(1, args.shard_count))
