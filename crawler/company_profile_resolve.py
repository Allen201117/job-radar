"""公司名 → 公司画像：建画像之前先认别名（网站侧同口径：lib/insight-profile-resolve.ts）。

❌ 2026-10-11 全库对拍：1,511 个画像里 136 家公司各有 2~5 个画像（知乎 / 知乎 Zhihu、云尖信息 / 云尖信息 校招、
   腾讯音乐 / 腾讯音乐 TME…）。说法挂在一个没有岗位的画像上、岗位挂在另一个没有说法的画像上，17 家公司在洞察库里
   一张带说法的卡都出不来；同一家公司还各自排队花搜索额度。
✅ 根因：每个建画像的入口都拿「名字完全相等」当去重键（`upsert(on_conflict="company")`），别名列从不参与——
   同一家公司的源叫「X」「X 校招」「X 英文名」，就各建一个。
✅ 防：建之前一律先过这里。归属规则不另写一份，直接用 bu_extract 给岗位认画像的那一套
   （正名精确 → 别名精确 → 归一名唯一），所以「这个名字归哪个画像」全仓只有一个答案。
   归一名先去掉招聘渠道后缀（「X 校招」「X 实习」），见 bu_extract.profile_name_key。
"""
import bu_extract
import db

LIGHT_COLUMNS = "id,company,aliases"


def load_index(supabase, columns: str = LIGHT_COLUMNS):
    """全量画像 → bu_extract 的索引三元组。columns 必须含 id / company / aliases。"""
    profiles = db.fetch_all_rows(lambda: supabase.table("company_profiles").select(columns))
    return bu_extract.build_profile_index(profiles)


def resolve(name: str, index):
    """名字归哪个画像；不归任何画像返回 None。"""
    exact, normalized, _ = index
    return bu_extract.resolve_profile(name, exact, normalized)


def unresolved(names, index) -> list[str]:
    """names 里还没有画像、需要新建的那些（保持传入顺序）。

    同一批里归一键相同的（「X」和「X 校招」都是新的）只留先出现的那个：另一个建出来就是重复画像，
    不建的话下一轮按归一键会认到先建的那个。调用方把名字排好序再传，基名自然排在带后缀的前面。
    """
    out, seen_keys = [], set()
    for name in names:
        if resolve(name, index):
            continue
        key = bu_extract.profile_name_key(name)
        if key and key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(name)
    return out


def find_profile(supabase, name: str, columns: str = LIGHT_COLUMNS):
    """按正名查一行；查不到再按别名 / 归一名找。只读。"""
    name = str(name or "").strip()
    if not name:
        return None
    rows = (supabase.table("company_profiles").select(columns).eq("company", name).limit(1).execute().data) or []
    if rows:
        return rows[0]
    return resolve(name, load_index(supabase, columns))


def ensure_profile(supabase, name: str, columns: str = LIGHT_COLUMNS, requeue: bool = False):
    """取这家公司的画像，没有才新建。requeue=True 时把已有画像重新排进官方事实富化队列。

    返回画像行（新建失败 / 名字为空返回 None）。⚠️ 返回行的 company 可能不是传进来的 name
    （name 是它的别名时）——调用方要用返回行里的 company，别继续用 name。
    """
    name = str(name or "").strip()
    if not name:
        return None
    hit = find_profile(supabase, name, columns)
    if hit:
        if requeue and hit.get("id"):
            supabase.table("company_profiles").update({"insight_checked_at": None}).eq("id", hit["id"]).execute()
        return hit
    payload = {"company": name}
    if requeue:
        payload["insight_checked_at"] = None
    supabase.table("company_profiles").upsert(payload, on_conflict="company").execute()
    rows = (supabase.table("company_profiles").select(columns).eq("company", name).limit(1).execute().data) or []
    return rows[0] if rows else None
