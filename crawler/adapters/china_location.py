"""国内企业招聘 API 的结构化地点判定。

共享 normalizer 覆盖常见中英文地点；这里补充官网 API 常见的中国行政区格式和实际
小城市，同时显式排除台湾及海外城市。仅供已确认是中国企业官方招聘源的结构化地点字段。
"""
import normalizer


_OVERSEAS_MARKERS = (
    "台湾", "台北", "高雄",
    "新加坡", "日本", "东京", "大阪", "韩国", "首尔",
    "美国", "纽约", "洛杉矶", "西雅图",
    "加拿大", "多伦多", "温哥华",
    "英国", "伦敦", "法国", "巴黎", "德国", "柏林",
    "澳大利亚", "悉尼", "墨尔本",
    "巴西", "圣保罗", "沙特", "利雅得",
    "阿联酋", "迪拜", "科威特", "卡塔尔", "巴林", "阿曼",
    "越南", "胡志明", "印度", "班加罗尔",
)

_KNOWN_CHINA_CITIES = (
    "沈阳", "东莞", "长春", "珠海", "嘉兴", "济南", "芜湖",
    "烟台", "淮安", "铜仁", "吉首", "澄迈", "雄安", "湛江",
)

_ADMIN_SUFFIXES = (
    "省", "市", "自治区", "特别行政区", "自治州", "地区", "盟", "新区",
)


def is_china_company_location(location: str) -> bool:
    text = str(location or "").strip()
    if not text or any(marker in text for marker in _OVERSEAS_MARKERS):
        return False
    if normalizer.is_china_location(text):
        return True
    if "全国" in text or "多省" in text:
        return True
    if any(city in text for city in _KNOWN_CHINA_CITIES):
        return True
    return any(text.endswith(suffix) for suffix in _ADMIN_SUFFIXES)
