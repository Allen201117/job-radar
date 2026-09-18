"""可报名门：一条公告「现在还能不能报」。纯函数，不联网。

为什么单靠标题门不够（2026-09-18 逐条 live 复核后立的碑）：
标题门只在**首次入库**那一刻看一眼标题，此后这行就一直 active 躺着。可现实是——
- 「江苏省水利科学研究院…**关闭报名系统**公告」标题含「招聘」，正向门直接放行；
- 报名窗是在**正文**里写的，官方随时可以另发一条公告把它关掉；
- 截止日抽取此前跑在**整页文本**上，侧栏别的公告的日期会被当成本公告的截止日。
⇒ 判据必须落在**正文**上，并且每天复验一次，而不是入库时判一次就算数。

三档结论（`Verdict.action`）：
- `reject`  不该展示：过程/结果通知、报名已关闭、报名截止日已过。
- `flag`    可展示但要标注：官方汇总索引页（有真信息，但报名入口在别处，得再跳一次）。
- `ok`      正常可报。

⚠️ 宁可漏判不可错杀：判据一律要求**正文里的明确表述**，抽不到就返回 ok 交给 TTL 兜底，
   绝不因为「没看到报名方式」就判死 —— 高校人才引进类公告常年只写邮箱，没有「报名时间」字样。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .deadline import extract_deadline, normalize

# ── 1. 标题层：过程 / 结果 / 附件 / 索引类，不是「可报名公告本体」 ──────────────
# 与 classify._EXCLUDE 的分工：那条门管「一眼就不是招聘」（成绩/公示/名单），
# 这条补的是「**是**招聘流程的一部分、但报名这一步已经过去了」的那些。
_TITLE_PROCESS = re.compile(
    # ⚠️ 只收「关闭报名」，**绝不能收「重启报名」**：江苏农牧那条「重启报名系统公告」正文写着
    #    「部分岗位未录满，9月16日重启考生报名系统，报名9月16日09:00-9月24日16:00」——它是一个
    #    **新开的报名窗**，按过程通知毙掉就是白扔一条在招公告（2026-09-18 逐条复核时当场抓到的误杀）。
    #    同理不收裸「报名系统」：它对开、关两种公告一视同仁。
    r"(关闭报名|停止报名|报名确认|报名人数|"
    r"专业测试|技能测试|综合测试|面试公告|面试确认|面试人选|进入面试|"
    r"笔试公告|笔试时间|考试时间|考场|领取准考证|"
    r"岗位表$|岗位一览表$|计划表$|公告汇总|汇总表$|"
    r"修改.{0,8}(条件|要求)|调整.{0,8}(公告|岗位|计划)|取消.{0,6}岗位)"
)

# ── 2. 正文层：官方明说报名这一步已经关了 ────────────────────────────────
_BODY_CLOSED = re.compile(
    r"(关闭报名系统|报名系统.{0,8}关闭|停止报名|报名.{0,6}(?:已|于).{0,12}(?:结束|截止)|"
    r"报名工作.{0,8}(?:已)?结束|不再接受报名)"
)

# ── 3. 正文层：汇总索引页（本页不收报名，让你去别处）────────────────────────
_BODY_INDEX = re.compile(r"(请登录.{0,20}(?:查询|查看|网站)|详见.{0,15}(?:网站|官网|公告)|公告发布网址)")
# 本页自己就收报名的证据——有它就不是索引页。
# ⚠️ 必须收全「报名」的各种说法：浙江音乐学院那条正文只写「网上报名」「报名网站」，
#    不写「报名方式/报名时间」，早期版本因此把一条本页自收报名的正常公告标成了汇总索引页
#    （它那句「请登录招聘报名网站下载打印**准考证**」还正好命中了 _BODY_INDEX）。
#    这道门是「否定性判断」，收窄一点就会误伤——宁可漏标几个索引页，不可把正常公告标成索引页。
_BODY_SELF_APPLY = re.compile(
    r"(报名方式|报名时间|报名地点|报名材料|报名网址|报名网站|报名系统|报名入口|"
    r"网上报名|网络报名|现场报名|在线报名|扫码报名|应聘方式|投递方式|"
    r"简历.{0,6}(?:发送|投递|递交)|邮箱.{0,10}@|应聘者.{0,10}(?:将|把).{0,10}简历)"
)


# 书名号里是**对另一份文件的引用**，不是对本公告的陈述。判「本公告报名关没关」之前必须先剥掉它：
# 江苏农牧那条「重启报名系统公告」正文开头写着「根据《…公开招聘(A类岗位)**关闭报名系统**公告》要求…
# 部分岗位未录满，9月16日重启考生报名系统」—— 不剥就会被引用的标题命中，把一条正在报名
# （9/16-9/24）的公告判死。2026-09-18 实测抓到，是同一处误杀换了条路进来。
_QUOTED_TITLE = re.compile(r"《[^》]{0,120}》")


@dataclass(frozen=True)
class Verdict:
    action: str          # "ok" | "flag" | "reject"
    reason: str          # 机器可读原因码，"" 表示 ok
    detail: str = ""     # 命中的原文片段（写台账 / 人工复核用）
    deadline: date | None = None      # 从**正文**抽到的报名截止日
    deadline_text: str | None = None

    @property
    def ok(self) -> bool:
        return self.action == "ok"


def assess(
    title: str,
    body: str,
    published_at: date | None = None,
    today: date | None = None,
) -> Verdict:
    """判一条公告现在还能不能报。body 必须是 `body.extract_body` 切过的**正文**，不是整页文本。"""
    today = today or date.today()
    norm = normalize(body)
    # 剥掉引用的文件名后再判「报名关没关」；截止日抽取仍用原文（引用里不含报名窗）。
    norm_unquoted = _QUOTED_TITLE.sub("", norm)
    deadline, deadline_text = extract_deadline(body, published_at=published_at, today=today)

    m = _TITLE_PROCESS.search(title or "")
    if m:
        return Verdict("reject", "process_notice", m.group(0), deadline, deadline_text)

    m = _BODY_CLOSED.search(norm_unquoted)
    if m:
        return Verdict("reject", "registration_closed", m.group(0)[:40], deadline, deadline_text)

    if deadline and deadline < today:
        return Verdict("reject", "deadline_passed", deadline_text or "", deadline, deadline_text)

    if _BODY_INDEX.search(norm) and not _BODY_SELF_APPLY.search(norm):
        return Verdict("flag", "index_page", "", deadline, deadline_text)

    return Verdict("ok", "", "", deadline, deadline_text)
