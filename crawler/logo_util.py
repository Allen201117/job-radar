"""企业 logo 抓取的纯函数（域名解析 / 平台域名排除 / 占位指纹 / data URI / 图片宽度）。

不打网络，便于单测（crawler/test_logo_util.py）。抓取编排在 fetch_company_logos.py。
"""
from __future__ import annotations

import base64
import hashlib
import re
import struct
from typing import Optional
from urllib.parse import urlparse

# 招聘托管 / 共享 ATS 平台域名：取其根域名会拿到平台自己的 logo，不是公司的 → 必须排除。
PLATFORM_DOMAINS = {
    "feishu.cn", "mioffice.cn", "mokahr.com", "zhiye.com",
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com",
    "ashbyhq.com", "smartrecruiters.com", "teamtailor.com", "pinpointhq.com",
}
# 子串命中即视为平台（北森系多变体域名）。
_PLATFORM_SUBSTRINGS = ("beisen", "italent")

# 命中平台域名（飞书/北森/moka 等）的公司 → 用这张手工「公司名→品牌域名」覆盖表兜底。
# key 用「原始公司名」（模块加载时统一 lower(trim) 归一匹配，见文件末构造）；
# 只收录官方域名【高把握】的公司——配错=张冠李戴，宁缺毋滥（不确定的一律留空，前端首字母兜底）。
_DOMAIN_OVERRIDES_RAW = {
    # —— 造车 / 新能源车 / 商用车 ——
    "蔚来": "nio.com", "NIO": "nio.com",
    "小鹏": "xpeng.com", "小鹏汽车": "xpeng.com", "XPeng": "xpeng.com",
    "理想": "lixiang.com", "理想汽车": "lixiang.com", "理想汽车 Li Auto": "lixiang.com",
    "地平线": "horizon.cc", "Horizon": "horizon.cc",
    "小米": "mi.com", "小米集团": "mi.com", "Xiaomi": "mi.com",
    "零跑汽车": "leapmotor.com", "奇瑞汽车": "chery.cn", "奇瑞汽车 CHERY": "chery.cn",
    "江淮汽车 JAC": "jac.com.cn", "长安汽车": "changan.com.cn", "长安汽车 Changan": "changan.com.cn",
    "浙江吉利控股集团": "geely.com", "徐工机械": "xcmg.com", "潍柴集团": "weichai.com",
    "三一集团": "sanygroup.com", "雅迪科技集团": "yadea.com",

    # —— AI 独角兽（国内外）——
    "OpenAI": "openai.com", "Perplexity": "perplexity.ai", "Cohere": "cohere.com",
    "ElevenLabs": "elevenlabs.io", "Replit": "replit.com", "Supabase": "supabase.com",
    "LangChain": "langchain.com", "Linear": "linear.app", "Harvey": "harvey.ai",
    "Vanta": "vanta.com", "Mercor": "mercor.com", "Meshy": "meshy.ai", "Baseten": "baseten.co",
    "Fireworks AI": "fireworks.ai", "Docebo": "docebo.com", "Instructure": "instructure.com",
    "MiniMax 稀宇科技": "minimaxi.com", "智谱AI Zhipu": "zhipuai.cn", "月之暗面 Kimi": "moonshot.cn",
    "零一万物 01AI": "01.ai", "硅基流动": "siliconflow.cn",
    "第四范式": "4paradigm.com", "第四范式 4Paradigm": "4paradigm.com",
    "云从科技": "cloudwalk.com", "商汤科技 SenseTime": "sensetime.com", "旷视科技": "megvii.com",
    "云知声": "unisound.com", "思必驰": "aispeech.com", "科大讯飞": "iflytek.com",

    # —— 自动驾驶 ——
    "小马智行": "pony.ai", "小马智行 Pony.ai": "pony.ai",
    "文远知行": "weride.ai", "文远知行 WeRide": "weride.ai", "Momenta": "momenta.ai",

    # —— 机器人 / 智能硬件 / 消费电子 ——
    "宇树科技（杭州）有限公司": "unitree.com", "智元机器人 AGIBot": "agibot.com",
    "深圳市普渡科技有限公司": "pudurobotics.com", "上海擎朗智能科技有限公司": "keenon.com",
    "极智嘉 Geek+": "geekplus.com", "新松机器人自动化股份有限公司": "siasun.com",
    "大疆": "dji.com", "安克创新 Anker": "anker.com", "科沃斯": "ecovacs.com",
    "石头科技": "roborock.com", "追觅科技": "dreametech.com", "添可": "tineco.com",
    "涂鸦智能": "tuya.com", "极米科技": "xgimi.com", "极米科技 XGIMI": "xgimi.com",
    "拓竹科技": "bambulab.com", "创想三维科技股份有限公司": "creality.com",
    "小天才 eebbk": "eebbk.com", "XREAL": "xreal.com", "xTool": "xtool.com",
    "美图公司": "meitu.com", "传音控股 Transsion": "transsion.com", "深圳传音控股": "transsion.com",
    "海信集团": "hisense.com", "九号公司": "ninebot.com", "海能达": "hytera.com",
    "大华股份 Dahua": "dahuatech.com", "浙江大华技术": "dahuatech.com", "大族激光": "hanslaser.com",
    "老板电器": "robam.com", "欧派家居集团股份有限公司": "oppein.com",
    "顾家家居股份有限公司": "kukahome.com",

    # —— 互联网 / 平台 / 生活服务 ——
    "作业帮": "zuoyebang.com", "作业帮 Zuoyebang": "zuoyebang.com",
    "猿辅导": "yuanfudao.com", "猿辅导 Yuanfudao": "yuanfudao.com",
    "好未来": "100tal.com", "好未来（学而思）": "100tal.com", "新东方 New Oriental": "xdf.cn",
    "高途": "gaotu.cn", "携程集团 Trip.com": "trip.com", "途牛旅游网": "tuniu.com",
    "知乎": "zhihu.com", "知乎 Zhihu": "zhihu.com", "搜狐 Sohu": "sohu.com",
    "搜狐畅游 Changyou": "changyou.com", "新浪集团": "sina.com.cn",
    "斗鱼": "douyu.com", "斗鱼直播 Douyu": "douyu.com", "虎牙": "huya.com", "虎牙直播 Huya": "huya.com",
    "爱奇艺股份有限公司": "iqiyi.com", "芒果TV": "mgtv.com",
    "唯品会 VIP.com": "vip.com", "贝壳找房": "ke.com", "自如": "ziroom.com", "我爱我家": "5i5j.com",
    "转转": "zhuanzhuan.com", "得物 POIZON": "dewu.com", "脉脉": "maimai.cn",
    "雪球": "xueqiu.com", "雪球 Xueqiu": "xueqiu.com", "五八同城": "58.com",
    "名创优品": "miniso.com", "名创优品 MINISO": "miniso.com",
    "瑞幸咖啡": "luckincoffee.com", "喜茶": "heytea.com", "海底捞": "haidilao.com",
    "滴滴": "didiglobal.com", "滴滴出行 DiDi": "didiglobal.com",
    "货拉拉 Lalamove": "huolala.cn", "货拉拉科技": "huolala.cn", "申通快递": "sto.cn",
    "途虎养车": "tuhu.cn", "懂车帝 Dcar": "dongchedi.com", "易车控股有限公司": "yiche.com",

    # —— 游戏 ——
    "莉莉丝游戏 Lilith": "lilithgames.com", "鹰角网络 Hypergryph": "hypergryph.com",
    "完美世界": "wanmei.com", "完美世界 Perfect World": "wanmei.com",
    "巨人网络": "ztgame.com", "巨人网络 Giant": "ztgame.com", "沐瞳科技": "moonton.com",

    # —— 半导体 / 芯片 / 通信设备 ——
    "中兴通讯股份有限公司": "zte.com.cn", "兆易创新": "gigadevice.com", "寒武纪": "cambricon.com",
    "摩尔线程": "mthreads.com", "壁仞科技": "birentech.com", "燧原科技": "enflame-tech.com",
    "芯驰科技": "semidrive.com", "芯海科技（深圳）股份有限公司": "chipsea.com",
    "移远通信": "quectel.com", "广和通": "fibocom.com", "全志科技股份有限公司": "allwinnertech.com",
    "长江存储": "ymtc.com", "长鑫存储技术有限公司": "cxmt.com", "安谋科技 Arm China": "armchina.com",
    "新华三信息技术": "h3c.com", "神州数码集团": "digitalchina.com",

    # —— 消费 / 食品 / 服饰 / 零售 ——
    "三只松鼠": "3songshu.com", "三只松鼠 Three Squirrels": "3songshu.com",
    "农夫山泉 养生堂": "nongfuspring.com", "东鹏饮料": "eastroc.com",
    "蒙牛": "mengniu.com.cn", "蒙牛乳业 MENGNIU": "mengniu.com.cn",
    "李宁 LI-NING": "lining.com", "安踏 ANTA": "anta.com", "安踏体育用品集团": "anta.com",
    "特步": "xtep.com", "森马集团": "semir.com", "江南布衣": "jnbygroup.com",
    "周大福": "chowtaifook.com", "永辉超市": "yonghui.com.cn", "屈臣氏": "watsons.com",
    "泡泡玛特": "popmart.com", "泡泡玛特 POP MART": "popmart.com",

    # —— 医药 / 医疗器械 ——
    "信达生物": "innoventbio.com", "百济神州": "beigene.com", "复星医药": "fosunpharma.com",
    "药明康德": "wuxiapptec.com", "药明生物": "wuxibiologics.com",
    "迈瑞医疗": "mindray.com", "迈瑞医疗 Mindray": "mindray.com", "微创医疗": "microport.com",
    "联影医疗 UIH": "united-imaging.com", "江苏恒瑞医药": "hengrui.com", "三生制药": "3sbio.com",
    "康龙化成（北京）新药技术股份有限公司": "pharmaron.com", "凯莱英": "asymchem.com",
    "华大基因": "genomics.cn",

    # —— 新能源 / 光伏 / 电池 / 电气 ——
    "宁德时代 CATL": "catl.com", "欣旺达": "sunwoda.com", "欣旺达电子": "sunwoda.com",
    "天合光能": "trinasolar.com", "天合光能 Trina": "trinasolar.com",
    "阳光电源": "sungrowpower.com", "阳光电源 Sungrow": "sungrowpower.com",
    "金风科技": "goldwind.com", "正泰集团": "chint.com",
    "汇川技术": "inovance.com", "汇川技术 Inovance": "inovance.com", "深圳市汇川技术": "inovance.com",

    # —— 企业软件 / SaaS / 网络安全 ——
    "金山办公": "wps.cn", "金山办公 WPS": "wps.cn", "广联达": "glodon.com", "广联达 Glodon": "glodon.com",
    "有赞": "youzan.com", "神策数据": "sensorsdata.cn", "聚水潭": "jushuitan.com",
    "上海汉得信息技术股份有限公司": "hand-china.com", "上海法大大网络科技有限公司": "fadada.com",
    "上海星环信息科技有限公司": "transwarp.io", "e签宝": "esign.cn",
    "深信服": "sangfor.com.cn", "锐捷网络": "ruijie.com.cn", "锐捷网络 Ruijie": "ruijie.com.cn",
    "绿盟科技": "nsfocus.com", "奇安信 QiAnXin": "qianxin.com",
    "启明星辰信息技术集团股份有限公司": "venustech.com.cn",
    "山石网科通信技术股份有限公司": "hillstonenet.com",
    "北京天融信科技股份有限公司": "topsec.com.cn", "北京微步在线科技有限公司": "threatbook.cn",

    # —— 金融 / 证券 / 保险 / 地产 ——
    "东方财富": "eastmoney.com", "中金公司": "cicc.com", "国信证券": "guosen.com.cn",
    "国泰君安证券股份有限公司": "gtja.com", "众安保险": "zhongan.com", "乐信集团": "lexin.com",
    "度小满金融科技（北京）有限公司": "duxiaoman.com", "老虎国际 Tiger Brokers": "tigerbrokers.com",
    "360集团": "360.cn", "万科 Vanke": "vanke.com", "万科企业": "vanke.com",
    "东软集团股份有限公司": "neusoft.com",

    # —— 外企科技 / 半导体 / 软件 ——
    "3M": "3m.com", "Adobe": "adobe.com", "Autodesk 欧特克": "autodesk.com",
    "NVIDIA": "nvidia.com", "Salesforce": "salesforce.com", "Samsung": "samsung.com",
    "ServiceNow": "servicenow.com", "Workday": "workday.com", "Marvell": "marvell.com",
    "Mastercard 万事达": "mastercard.com", "Visa": "visa.com", "Cadence 铿腾": "cadence.com",
    "思科 Cisco": "cisco.com", "英特尔 Intel": "intel.com", "美光 Micron": "micron.com",
    "恩智浦 NXP": "nxp.com", "博通 Broadcom": "broadcom.com", "科磊 KLA": "kla.com",
    "应用材料 Applied Materials": "appliedmaterials.com", "亚德诺 ADI": "analog.com",
    "惠普 HP": "hp.com", "慧与 HPE": "hpe.com", "Snap Inc": "snap.com", "Grab": "grab.com",
    "Shopee": "shopee.com", "SHEIN": "shein.com", "Wise": "wise.com",

    # —— 外企消费 / 工业 / 医药 / 金融 ——
    "Nike": "nike.com", "Shell": "shell.com", "Ubisoft": "ubisoft.com", "Supercell": "supercell.com",
    "UPS": "ups.com", "Boeing": "boeing.com", "Bosch 博世": "bosch.com", "Continental": "continental.com",
    "可口可乐 Coca-Cola": "coca-cola.com", "卡特彼勒 Caterpillar": "caterpillar.com",
    "博格华纳 BorgWarner": "borgwarner.com", "丹纳赫 Danaher": "danaher.com",
    "亿滋 Mondelez": "mondelezinternational.com", "星巴克 Starbucks": "starbucks.com",
    "飞利浦 Philips": "philips.com", "马士基 Maersk": "maersk.com", "麦格纳 Magna": "magna.com",
    "开利 Carrier": "carrier.com", "江森自控 Johnson Controls": "johnsoncontrols.com",
    "特灵 Trane": "trane.com", "奥的斯 Otis": "otis.com", "安波福 Aptiv": "aptiv.com",
    "帝亚吉欧 Diageo": "diageo.com", "保乐力加 Pernod Ricard": "pernod-ricard.com",
    "强生 Johnson & Johnson": "jnj.com", "Pfizer 辉瑞": "pfizer.com", "诺华 Novartis": "novartis.com",
    "罗氏 Roche": "roche.com", "美敦力 Medtronic": "medtronic.com", "葛兰素史克 GSK": "gsk.com",
    "赛诺菲 Sanofi": "sanofi.com", "赛默飞 Thermo Fisher": "thermofisher.com", "雅培 Abbott": "abbott.com",
    "阿斯利康 AstraZeneca": "astrazeneca.com", "武田制药 Takeda": "takeda.com", "渤健 Biogen": "biogen.com",
    "安进 Amgen": "amgen.com", "史赛克 Stryker": "stryker.com", "因美纳 Illumina": "illumina.com",
    "陶氏化学 Dow": "dow.com", "杜邦 DuPont": "dupont.com",
    "摩根士丹利 Morgan Stanley": "morganstanley.com", "德意志银行 Deutsche Bank": "db.com",
    "贝莱德 BlackRock": "blackrock.com", "Citi 花旗": "citi.com",
    "GE医疗 GE HealthCare": "gehealthcare.com", "AbbVie": "abbvie.com", "Baxter 百特": "baxter.com",
    "MSD 默沙东": "merck.com", "Kenvue 科赴": "kenvue.com", "Zoetis": "zoetis.com",
    "Regeneron": "regeneron.com", "The Walt Disney Company 迪士尼": "disney.com",
    "DBS Bank 星展银行": "dbs.com", "Fidelity Investments 富达": "fidelity.com",
    "米其林（中国）投资有限公司": "michelin.com", "资生堂（中国）投资有限公司": "shiseido.com",
    "麦当劳（中国）有限公司": "mcdonalds.com.cn", "日立能源（中国）有限公司": "hitachienergy.com",
    "伊顿电气（上海）有限公司": "eaton.com", "空气产品 Air Products": "airproducts.com",
    "Rockwell Automation 罗克韦尔": "rockwellautomation.com", "Illinois Tool Works": "itw.com",
    "Jabil": "jabil.com", "JLL 仲量联行 Jones Lang LaSalle": "jll.com",
}
# 统一 lower(trim) 归一，与 domain_for_company 里 company.strip().lower() 匹配同口径。
COMPANY_DOMAIN_OVERRIDES = {k.strip().lower(): v for k, v in _DOMAIN_OVERRIDES_RAW.items()}

# 中国等多级公共后缀：注册域名要多取一段（com.cn 等）。
_MULTI_LEVEL_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
    "com.hk", "com.tw", "co.jp", "co.uk", "co.kr", "com.sg",
}


def registrable_domain(host: str) -> str:
    """从 host 取「注册域名」（去子域）。talent.baidu.com→baidu.com；nio.jobs.feishu.cn→feishu.cn。"""
    if not host:
        return ""
    host = host.strip().lower()
    host = host.split("@")[-1].split(":")[0].rstrip(".")  # 去认证段 / 端口 / 尾点
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    last2 = ".".join(parts[-2:])
    if last2 in _MULTI_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_platform_domain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.strip().lower()
    if domain in PLATFORM_DOMAINS:
        return True
    return any(s in domain for s in _PLATFORM_SUBSTRINGS)


def _host_from_source(source_url: str) -> str:
    """从 source_url 取 host，兼容无 scheme（如 talent.baidu.com/xx）。"""
    if not source_url:
        return ""
    parsed = urlparse(source_url)
    if parsed.netloc:
        return parsed.netloc
    # 无 scheme：path 首段当 host
    return parsed.path.split("/")[0]


def _slug_from_ats(source_url: str) -> Optional[str]:
    """greenhouse / lever 的公司 slug：.../boards/{slug}/... 或 .../postings/{slug}。"""
    try:
        parts = [p for p in urlparse(source_url).path.split("/") if p]
    except Exception:
        return None
    for marker in ("boards", "postings"):
        if marker in parts:
            i = parts.index(marker)
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def domain_for_company(company: str, source_url: str, override_map: Optional[dict] = None) -> Optional[str]:
    """按优先级推导品牌域名：覆盖表 > 非平台的 source host 注册域名 > greenhouse/lever slug 猜 {slug}.com > None。"""
    override_map = COMPANY_DOMAIN_OVERRIDES if override_map is None else override_map
    key = (company or "").strip().lower()
    if key in override_map:
        return override_map[key]
    domain = registrable_domain(_host_from_source(source_url))
    if domain and not is_platform_domain(domain):
        return domain
    if domain in ("greenhouse.io", "lever.co"):
        slug = _slug_from_ats(source_url)
        if slug:
            return f"{slug.lower()}.com"
    return None


# ============================================================
# slug 兜底（覆盖率主力）：平台托管公司（北森 zhiye / moka / 飞书 / workday / smartrecruiters / ashby）
# 的 source_url 里带公司 slug（多为公司拼音或英文名）→ 猜品牌域名，再用「页面核验门」确认该域名
# 确实属于这家公司才认。核验门是防张冠李戴的唯一防线：实测 轻松集团 slug=qsc → qsc.cn 其实是
# 美国音响公司 QSC，靠核验（页面不含「轻松」）正确拒绝。核验不过一律丢弃 → 首字母兜底。
# ============================================================

# 子域即 slug 的平台
_SUBDOMAIN_SLUG_HOSTS = ("zhiye.com", "jobs.feishu.cn", "mioffice.cn", "myworkdayjobs.com")
# 平台通用子域/路径段，不是公司标识
_GENERIC_SLUGS = {"app", "www", "jobs", "api", "campus", "hr", "m", "app-tc", "recruit", "career", "careers"}
# 候选顶级域（按中国公司常见度排序，命中即停）
_CANDIDATE_TLDS = (".com", ".cn", ".com.cn")


def platform_slug(source_url: str) -> Optional[str]:
    """从平台托管 URL 提取公司 slug；提不出返回 None。"""
    if not source_url:
        return None
    host = _host_from_source(source_url).lower()
    try:
        parts = [p for p in urlparse(source_url).path.split("/") if p]
    except Exception:
        parts = []

    slug: Optional[str] = None
    if any(h in host for h in _SUBDOMAIN_SLUG_HOSTS):
        sub = host.split(".")[0]
        slug = sub
    elif "mokahr.com" in host:
        # app.mokahr.com/social-recruitment/{slug}/... | /campus-recruitment/{slug} | /apply/{slug}/...
        slug = parts[1] if len(parts) > 1 else None
    elif "smartrecruiters.com" in host or "ashbyhq.com" in host:
        for marker in ("companies", "job-board"):
            if marker in parts:
                i = parts.index(marker)
                if i + 1 < len(parts):
                    slug = parts[i + 1]
                    break
    if not slug:
        return None
    slug = slug.split("?")[0].strip().lower()
    # 只留域名合法字符；过滤平台通用段与过短 slug
    slug = "".join(ch for ch in slug if ch.isalnum() or ch == "-").strip("-")
    if not slug or slug in _GENERIC_SLUGS or len(slug) < 2 or slug.isdigit():
        return None
    return slug


def candidate_domains(slug: str) -> list:
    """slug → 候选品牌域名（按常见度排序）。"""
    if not slug:
        return []
    return [f"{slug}{tld}" for tld in _CANDIDATE_TLDS]


# 公司名里的地域前缀 / 组织后缀 / 行业尾巴，剥掉后得到用于核验的「主名」
_REGION_PREFIXES = (
    "上海", "北京", "深圳", "广州", "杭州", "浙江", "江苏", "广东", "天津", "山东", "厦门", "无锡",
    "苏州", "南京", "成都", "武汉", "西安", "重庆", "福建", "安徽", "湖南", "湖北", "河南", "河北",
    "山西", "陕西", "江西", "云南", "贵州", "辽宁", "吉林", "黑龙江", "内蒙古", "新疆", "甘肃",
    "青海", "宁夏", "西藏", "海南", "青岛", "大连", "宁波", "合肥", "长沙", "郑州", "济南", "福州",
)
_ORG_SUFFIXES = (
    "股份有限公司", "有限责任公司", "控股集团有限公司", "集团股份有限公司", "有限公司", "控股有限公司",
    "集团有限公司", "科技集团", "控股集团", "实业集团", "投资集团", "集团", "控股", "公司", "实业",
)
_INDUSTRY_TAILS = (
    "信息技术", "网络科技", "智能科技", "生物科技", "医疗科技", "数字科技", "文化科技", "信息科技",
    "科技", "网络", "信息", "技术", "生物", "医药", "医疗", "汽车", "教育", "电器", "食品", "服饰",
    "能源", "电子", "半导体", "软件", "数据", "智能", "机械", "材料", "电气", "地产", "金融", "证券",
    "保险", "银行", "证券股份", "投资", "物流", "传媒", "文化", "娱乐", "游戏", "餐饮", "服务",
)
# 页面上的「企业指示词」：2 字主名太短易误撞，要求页面同时像个公司官网
_CORP_HINTS = ("有限公司", "股份", "集团", "官网", "公司", "科技", "控股", "企业")


def company_core_names(company: str) -> list:
    """公司名 → 用于核验的候选 token（长→短）。含中文主名与英文名。"""
    raw = (company or "").strip()
    if not raw:
        return []
    # 去括号内容、去「校招/社招/实习」等抓取侧后缀
    cleaned = re.sub(r"[（(][^）)]*[）)]", "", raw)
    cleaned = re.sub(r"\s*(校招|社招|实习|招聘)\s*$", "", cleaned).strip()

    chinese = "".join(re.findall(r"[一-鿿]+", cleaned))
    latin = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9.\-]*", cleaned)).strip()

    tokens: list = []
    if chinese:
        core = chinese
        # 多轮剥组织后缀（「米其林投资有限公司」→ 剥「有限公司」→ 再剥「投资」→「米其林」），每轮保底留 2 字
        for _ in range(3):
            for suf in _ORG_SUFFIXES:  # 长后缀在前
                if core.endswith(suf) and len(core) - len(suf) >= 2:
                    core = core[: -len(suf)]
                    break
            else:
                break
        for pre in _REGION_PREFIXES:
            if core.startswith(pre) and len(core) > len(pre) + 1:
                core = core[len(pre):]
                break
        if len(core) >= 2:
            tokens.append(core)
            for tail in _INDUSTRY_TAILS:  # 再剥行业尾巴得到更短主名（如「观安信息技术」→「观安」）
                if core.endswith(tail) and len(core) - len(tail) >= 2:
                    tokens.append(core[: -len(tail)])
                    break
    if latin:
        drop = {"inc", "ltd", "llc", "corp", "corporation", "group", "company", "co", "holdings", "limited"}
        words = [w for w in latin.split() if w.lower().strip(".") not in drop]
        if words:
            tokens.append(" ".join(words))
            if len(words) > 1 and len(words[0]) >= 4:
                tokens.append(words[0])
    # 去重保序
    out: list = []
    for t in tokens:
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


def page_verifies_company(company: str, slug: str, page_text: str) -> bool:
    """核验门：候选域名的页面文本（title + description 等）是否自证属于这家公司。

    通过条件（任一）：
      · 页面含公司中文主名，长度 ≥3 → 直接通过；
      · 页面含 2 字中文主名 **且** 页面像公司官网（含「有限公司/股份/集团/官网…」）→ 通过（防「轻松」撞无关页）；
      · 无中文名时，页面含英文公司名或 slug（长度 ≥4）→ 通过。
    其余一律 False（宁缺毋滥，交回首字母兜底）。
    """
    text = (page_text or "").strip()
    if not text:
        return False
    low = text.lower()
    has_corp_hint = any(h in text for h in _CORP_HINTS)

    for token in company_core_names(company):
        if re.search(r"[一-鿿]", token):  # 中文主名
            if token in text and (len(token) >= 3 or has_corp_hint):
                return True
        else:  # 英文名
            t = token.lower()
            if len(t) >= 4 and t in low:
                return True
    s = (slug or "").lower()
    if len(s) >= 4 and s in low:
        return True
    return False


def is_placeholder(img_bytes: bytes, placeholder_md5_set) -> bool:
    """md5 命中占位指纹集（icon.horse 对任何域名都返回占位图，靠此过滤）。空内容也算占位。"""
    if not img_bytes:
        return True
    return hashlib.md5(img_bytes).hexdigest() in placeholder_md5_set


def normalize_mime(content_type: Optional[str], img_bytes: bytes = b"") -> str:
    """把 content-type 归一为 data URI 用的 mime；不可信时按内容嗅探。"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ("image/vnd.microsoft.icon", "image/icon"):
        return "image/x-icon"
    if ct in ("image/png", "image/svg+xml", "image/jpeg", "image/gif", "image/webp", "image/x-icon"):
        return ct
    # content-type 缺失/异常 → 内容嗅探
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    head = img_bytes[:256].lower()
    if head[:5] == b"<?xml" or b"<svg" in head:
        return "image/svg+xml"
    if img_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/png"


def build_data_uri(content_type: Optional[str], img_bytes: bytes) -> str:
    mime = normalize_mime(content_type, img_bytes)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def image_width(img_bytes: bytes) -> Optional[int]:
    """best-effort 取像素宽（PNG 读 IHDR / ICO 读第一个目录项），拿不到返回 None。不依赖 Pillow。"""
    if not img_bytes:
        return None
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(img_bytes) >= 24:
        try:
            return struct.unpack(">I", img_bytes[16:20])[0]
        except Exception:
            return None
    if img_bytes[:4] == b"\x00\x00\x01\x00" and len(img_bytes) >= 7:
        w = img_bytes[6]  # ICO 目录项 width，0 表示 256
        return 256 if w == 0 else w
    return None
