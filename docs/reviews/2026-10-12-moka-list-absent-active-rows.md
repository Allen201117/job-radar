# Moka 在招里「列表早就没有」的岗：逐岗核验与处置方案（2026-10-12）

只读调查，没有写库、没有改代码。要不要下架、用哪种机制，等创始人定。
好未来校招那 987 行不在本报告里（门户搬去了自建站，另有会话在处理）。

## 结论

- **底数**（香港库，北京 10-12 20:02）：Moka 源在招 54,289 行。其中最近一轮完整列表（当天 09:18 那一轮）里没有的
  6,934 行 / 102 条源；这里面超过 7 天没见到的 6,245 行。
- **逐岗真渲染 6,934 行**（不抽样）：**6,879 行页面写着「抱歉，该职位已停止招聘」**（97 个门户），55 行不是：
  25 行是当天白天被对方重新开放的，19 行挂在已停用的源下面，4 行是宝洁的台湾岗，7 行是乐元素旧门户的链接。
- 当天白天才掉出列表的 239 行（09:18 那轮还在、21:14 那轮没有）也逐岗渲染了：239 行全部是「已停止招聘」。
- **两个方向都数了，反例是 0**：
  - 列表里没有、页面却在招：0 行（上面那 4 行宝洁台湾岗其实在对方列表里，是我们按口径不收）。
  - 页面写着已停、列表里却有：0 行（7,118 行判停招的，没有一行被 21:14 那轮完整列表见到）。
  - 反过来，列表里有的 410 行（388 行对照 + 白天重新开放后又回到列表的 25 行，其中 3 行对照白天下线了）页面都在招。
    ⚠️ 这一条是抽的对照（每个门户 4 行），不是全集。
- **为什么攒下来**：不是判不出，是轮不到。巡检每晚约 6,800 次渲染按源平摊，每条源每晚约 7 行（必投公司约 11 行），
  宁德时代社招 2,712 行转一圈要八个月以上；而 Moka 每个工作日约有 240 行掉出列表。另有 39 行是英文版停招文案，巡检词表不认。
- **建议**：做方案 d（「这一轮抓全了的列表里没有」+「逐岗再问一次详情确认已停」，两条都满足才下架），
  它的第一轮顺带把这 7 千行存量清掉。下架写成 expired（与现行巡检同一口径）。不建议单独开方案 b。

## 一、怎么量的

**目标集。** Moka 源（`sources.adapter_name='moka'`，443 条，量的时候 409 条在用）名下 `status='active'` 的行里，
`last_seen_at` 早于「该源最近一轮抓取开始时刻」的行，去掉好未来校招。只取 active：年限口径下架的 3,705 行是 removed，不在里面。

**四轮完整列表**（Moka 抓全率修好之后的全部四轮，时间是 UTC）：

| 轮 | 时间 | 触发 | 说明 |
|---|---|---|---|
| 第一轮 | 10-11 17:53 | 手动浏览器档 | 翻页修复上线后首轮 |
| 第二轮 | 10-11 21~22 点 | 夜里重档 | |
| 第三轮 | 10-12 01:18 | 手动浏览器档 | 年限口径首轮；目标集按它定 |
| 第四轮 | 10-12 13:14~13:38 | 手动浏览器档（别的会话触发的） | 恰好和本次核验同时，拿来做对拍 |

目标集 6,934 行里 6,908 行所在的 368 条源，前三轮每一轮都记抓全，而且每条源「这一轮抓到的条数」与「库里这一轮被刷新的在招行数」
逐源相等（第三轮合计 45,289 对 45,289；第四轮 372 条抓全的源合计 45,605 对 45,605，0 条对不上）。
其余 26 行：19 行在 4 条已停用的源下面，7 行在乐元素校招（这条源从 6 月起一直抓取失败）。

**逐岗渲染。** 本机系统 Chrome、直连、最多 3 个并发，北京 20:26~22:10。每个岗都是整页重新加载（先回空白页再打开链接），
不走只换 `#` 后面的同文档跳转。判据只认页面上的正面证据：

- 已停：页面出现「停止招聘」/ "stopped recruiting"，且没有申请按钮。
- 在招：页面有申请按钮（「申请职位」/ "Apply now"），且没有停招文案。
- 其余原文留档人看；没渲染出来的重试。

**第二个独立量法。** 详情页自己会发一个请求（`POST /api/outer/ats-apply/website/job`，带租户、岗位 id、门户 id），回包是密文。
不解密，只看长度：已停的岗（和不存在的 id）回 152 个字符（英文门户 172），在招的回 1,708 个字符以上（中位 4,204）。
这个请求匿名直接发也有答复，所以把 7,558 行不开浏览器又各问了一遍。它按门户算：同一个岗换另一个门户 id 去问，回的是 152。

**对照。** 每条有目标行的源各取 4 行「第三轮列表里见到的」在招行，共 388 行，同样渲染 + 直接问。

## 二、结果

**6,934 行目标：**

| 页面上是什么 | 行数 | 其中超过 7 天没见到 | 门户数 |
|---|---:|---:|---:|
| 写着「已停止招聘」 | 6,879 | 6,201 | 97 |
| 在招：白天被重新开放，第四轮列表已重新见到 | 25 | 18 | 6 |
| 在招：所在的源已停用（残留行） | 19 | 19 | 4 |
| 在招：在对方列表里，但我们按口径不收（宝洁台湾岗） | 4 | 0 | 1 |
| 链接跳到别的门户首页，不显示岗位（乐元素） | 7 | 7 | 1 |

判停招的 6,879 行按最后见到的月份：6 月 489、7 月 836、8 月 1,734、9 月 3,103、10 月 717。其中 1,817 行从没被巡检看过。
这 6,934 行上的用户动作一共 5 条（看过 4、收藏 1）。

**两条量法对拍（7,558 行，含对照与当天新掉出的）：** 页面判已停的 7,118 行，直接请求全部回短密文；页面判在招的 433 行全部回长密文；
冲突 0 行。乐元素那 7 行页面跳走了，不计入。

**拿第四轮列表对拍（只看第四轮抓全的 372 条源）：**

| | 页面在招 | 页面已停 |
|---|---:|---:|
| 第四轮列表里有 | 410 | 0 |
| 第四轮列表里没有 | 4（宝洁台湾岗，见下） | 7,118 |

- 那 4 行宝洁岗页面地点写的是 Taiwan。它们在对方列表里，是入库质量门按台湾红线拒收，所以库里的旧行没人刷新。
  算上这一点，「列表里没有却在招」的真实例子是 0。
- 白天重新开放的 25 行（特斯拉 12、徐工校招 5、吉利社招 4、药明生物 2、宁德时代校招 1、远景校招 1）：
  第三轮时不在列表里，我核的时候页面已经在招，第四轮列表又见到了它们。特斯拉门户首页数据里写着这些岗的关闭时间和重新开放时间
  （例：「服务顾问-山西太原」10-08 关闭、10-12 重新开放，岗位本身 2021 年就建了）。
  对方是把旧岗位关了再开，岗位编号不变。
- 只缺席一轮的也都是已停：第三轮见到、第四轮没见到的 239 行，239 行页面写着已停。

**四轮下来的判断：在抓全的前提下，Moka 门户列表就是该门户在招岗的全集。**

## 三、为什么攒下来

- **巡检轮不到。** 浏览器巡检每晚 6 片、合计约 6,800 次渲染，要分给 16 种来源、1,143 条源，按源平摊：每条源每晚 7 行，
  必投公司另加 4 行。宁德时代社招 2,712 行，按 11 行一晚要 247 晚。近 9 天每晚合计下架约 190 行，命中率 2.8%——
  绝大部分渲染花在本来就在招的岗上。Moka 源近 14 天每天被巡检下架 70~173 行。
- **流入比清得快。** 第三轮到第四轮之间（12 小时，覆盖一个工作日）掉出列表 239 行；国庆那一周几乎为 0。
- **英文版文案不认。** 宝洁 20 行、富途 10 行、光子跳动 9 行的停招页写的是 "has stopped recruiting"，巡检词表里没有，
  轮到了也只能判「疑似」。
- **机制上没有别的出口。** Moka 没开「列表缺席即撤岗」；那个开关目前也只在快档（纯 HTTP 那一档）落库，Moka 所在的重档没开。

## 四、方案比较

**a. 只把这批存量下架。** 6,879 行（加当天新掉出的 239 行共 7,118 行）。机制不变的话，每个工作日约 240 行掉出列表、
巡检清掉一百来行，存量一个月长回三千行上下。必须和 b / c / d 之一一起做。

**b. 给 Moka 开「抓全的那一轮里没见到就下架」。**

- 证据支持它：四轮、7,118 行缺席的岗全部已停，反例 0；只缺席一轮的 239 行也是。项目立过的碑要求「先证明列表是全集」，这一条现在满足。
- 但它只凭列表下架，而下架是 expired，次日就被永久删除。风险全压在「这一轮抓全了」这个判断上：
  - 这个判断是 10-12 凌晨才有的（拿门户自报总数当分母），只跑过四轮。Moka 的列表抓取此前出过多次「读少了却记成功」。
  - 现在「抓全」允许比门户自报少 2 个或 1%（吉利社招门户自报 2,484 个岗，少 24 个以内仍记抓全）。要按缺席下架，得另加一个「一个不少」的条件。
  - **占比安全闸在存量清掉之后基本不起作用。** 现在带着存量，它只拦得住李宁一条源（168 / 328，超过一半）。
    清完之后，一个工作日里掉出最多的源是九毛九 5 / 37（13.5%），372 条源没有一条接近 50%。
    也就是说它只拦得住「一轮少了一半以上」，少 10%~40% 的漏读它放行；在招不足 8 行的小门户它根本不管。
  - 在对方列表里、但我们不入库的岗（台湾岗、标题解析为空的卡片）会被当成缺席。
- 要改的地方：adapter 声明支持缺席撤岗并给出「一个不少」的条件、重档 workflow 打开落库开关、改掉现有那条钉着「Moka 不开」的单测。

**c. 维持机制，只加巡检量。** 不可行：要让宁德时代这种门户一周转一圈，巡检量得翻 35 倍以上。
变体是让巡检先看「列表里已经没有」的岗：每晚约 240 次渲染就够。要改三处——取岗顺序、等待方式（现在固定等 2.5 秒，
页面慢就落到「判不了」）、词表加英文文案。证据是页面文字，最保守；代价是每晚多跑二十来分钟浏览器，慢页面要多轮才能清掉。

**d. b 的候选 + 逐岗再确认（建议）。** 「这一轮抓全了的列表里没有」只当候选；对每个候选再问一次详情请求，
回的是已停才下架；仍在招的不动并单独计数。和 10-12 给比亚迪上的那套是同一个思路（不在全量列表 + 详情接口确认）。

- 两个证据互相独立，任何一个出问题都不会下架：列表漏读时详情请求会说「还在招」；详情请求哪天变了样，由对照拦住
  （每条源先问几行这一轮见到的岗，必须读到在招；再问一个不存在的 id，必须读到已停；不过就整条源不下架）。
- 成本：每晚约 240 个请求，不用浏览器。
- 第一轮顺带清存量：约 7 千个候选逐个确认后下架。李宁那条会被 50% 的闸拦住，清存量那一次要由人显式放宽。
- 边界：详情请求的回包是密文，这里只看长短、不解密。这类证据此前没用过，用不用由创始人定；
  不想用的话，c 的变体（渲染后看页面文字）是替代，慢一些。
- 没在 CI 上验过：本次的 7,558 个请求都是从国内网络发的，CI 在境外。上线前先在 CI 上跑一轮只报告、不落库的。

**建议的顺序：** 创始人选定方案 → 在草稿分支写代码和测试 → 同意后推 main，CI 上先跑只报告的一轮，
把它点名的行和本报告的清单对一遍 → 再次同意后落库。

## 五、下架写成 expired 还是 removed

- **已停止招聘的 7,118 行：建议 expired。** 与巡检、比亚迪那条同一口径（逐岗确认已撤）。次日 purge 永久删除，删之前立墓碑。
  对方日后把同一个岗重新开放时，它会作为一条新岗重新入库（今天 12 小时内就有 25 行这样的；Moka 历史墓碑 4,792 条里复活过 58 条）。
- 换成 removed 的话可以随时恢复，岗位重新开放时沿用原来那一行；代价是这些行永远留在库里（Moka 名下已有 10,284 行 removed），
  而且「确认已撤」和「口径外 / 源停用」混成一个状态。
- **另外 30 行不是「已撤岗」，建议用 removed**（见下一节）。

## 六、不属于「已撤岗」的 55 行

| 哪些 | 行数 | 现状 | 建议 |
|---|---:|---|---|
| 白天重新开放的 | 25 | 第四轮已重新见到 | 不动 |
| 巨人网络、锐捷的旧地址（`apply/…`，源已停用） | 15 | 同一个岗在新地址的源下另有一行在招，现在是一岗两行 | 标 removed |
| 作业帮（门户 150144）、中兴校招（门户 94063），源已停用 | 4 | 页面在招，但没有源在刷新它们 | 标 removed，或重新启用源，创始人定 |
| 宝洁社招的台湾岗 | 4 | 在对方列表里，按红线不收 | 标 removed（另一个会话的回填清单里也有台湾岗，合并处理） |
| 乐元素校招旧门户 | 7 | 链接跳到新门户首页，看不到岗位；这条源 6 月起一直失败 | 标 removed；源要换地址，另案 |

## 七、逐门户清单

「已停止招聘」= 逐岗渲染页面写着已停的行，含当天白天才掉出列表的。「另行处理」= 上一节的残留 / 台湾岗 / 乐元素。
数字是 10-12 北京 22:10 的；真正落库时以那一轮的抓取和确认为准，会有出入（每天都有岗下线和重新开放）。

合计：122 个门户，已停止招聘 7,118 行（其中超过 7 天没见到 6,201 行、当天新掉出 239 行），仍在招 25 行，另行处理 30 行。

| 公司（源表里的写法） | 渠道 | 门户 | 库里在招 | 已停止招聘（拟下架） | └ 其中超过 7 天没见到 | └ 今天白天才掉出列表 | 仍在招（不动） | 另行处理 | 最早的「最后见到」 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 宁德时代 | 社招 | talent.catl.com/social-recruitment/catlhr/96144 | 2,712 | 892 | 843 | 24 |  |  | 06-15 |
| 浙江吉利控股集团 | 社招 | app.mokahr.com/social-recruitment/geely/96123 | 3,184 | 707 | 678 | 5 | 4 |  | 07-02 |
| 江苏恒瑞医药 | 社招 | app.mokahr.com/social-recruitment/hengrui/145996 | 1,537 | 556 | 516 | 12 |  |  | 06-15 |
| 安踏体育用品集团 | 社招 | app.mokahr.com/social-recruitment/antahr/146041 | 2,066 | 447 | 421 | 5 |  |  | 06-15 |
| SHEIN | 社招 | app.mokahr.com/apply/shein/2933 | 1,117 | 445 | 404 | 6 |  |  | 06-15 |
| 东风汽车 | 社招 | app.mokahr.com/social-recruitment/dfmc/168368 | 1,990 | 418 | 412 | 0 |  |  | 07-22 |
| 药明生物 | 社招 | app.mokahr.com/social-recruitment/wuxibiologics/99960 | 871 | 385 | 350 | 13 | 2 |  | 06-15 |
| 滴滴 | 社招 | app.mokahr.com/social-recruitment/didiglobal/6222 | 1,020 | 376 | 308 | 1 |  |  | 08-04 |
| 吉利汽车 | 校招 | campus.geely.com/campus-recruitment/geely/78436 | 2,634 | 354 | 337 | 3 |  |  | 06-15 |
| 特斯拉 | 社招 | app.mokahr.com/social-recruitment/tesla/46129 | 1,161 | 256 | 217 | 7 | 12 |  | 07-27 |
| 舜宇集团 | 社招 | app.mokahr.com/social-recruitment/sunnyoptical/45601 | 943 | 242 | 213 | 2 |  |  | 06-15 |
| 李宁 | 社招 | app.mokahr.com/social-recruitment/lining/166080 | 328 | 168 | 114 | 3 |  |  | 08-27 |
| 宁德时代 CATL | 校招 | app.mokahr.com/campus-recruitment/catlhr/148948 | 645 | 149 | 99 | 1 | 1 |  | 08-20 |
| 恒瑞医药 | 校招 | app.mokahr.com/campus-recruitment/hengrui/145997 | 1,092 | 143 | 143 | 0 |  |  | 07-31 |
| 康龙化成（北京）新药技术股份有限公司 | 校招 | app.mokahr.com/campus-recruitment/pharmaron/44352 | 709 | 140 | 91 | 18 |  |  | 09-04 |
| 百济神州 | 社招 | app.mokahr.com/social-recruitment/beigene/98934 | 611 | 135 | 131 | 0 |  |  | 07-21 |
| 作业帮 Zuoyebang | 社招 | app.mokahr.com/social-recruitment/zuoyebang/41328 | 356 | 117 | 82 | 2 |  |  | 09-01 |
| 宁波均胜电子 | 社招 | app.mokahr.com/social-recruitment/joyson/94310 | 421 | 111 | 92 | 4 |  |  | 08-19 |
| 九号公司 | 社招 | app.mokahr.com/social-recruitment/ninebot/45626 | 490 | 92 | 69 | 13 |  |  | 08-17 |
| 牧原实业集团 | 社招 | app.mokahr.com/social-recruitment/muyuan/70115 | 222 | 83 | 83 | 0 |  |  | 09-15 |
| 徐工集团 | 校招 | app.mokahr.com/campus-recruitment/xcmg/148091 | 657 | 72 | 56 | 6 | 5 |  | 09-07 |
| 鹰角网络 Hypergryph | 社招 | app.mokahr.com/apply/hypergryph/26325 | 412 | 61 | 48 | 6 |  |  | 08-17 |
| 特斯拉 | 校招 | app.mokahr.com/campus-recruitment/tesla/41460 | 486 | 58 | 43 | 7 |  |  | 09-03 |
| 锐捷网络 | 社招 | app.mokahr.com/social-recruitment/ruijie/26518 | 670 | 56 | 47 | 8 |  |  | 06-22 |
| 岚图汽车科技有限公司 | 社招 | app.mokahr.com/social-recruitment/voyah/146292 | 1,396 | 47 | 37 | 10 |  |  | 06-22 |
| 徐工机械 | 社招 | app.mokahr.com/social-recruitment/xcmg/148090 | 847 | 45 | 38 | 0 |  |  | 07-29 |
| 伊顿电气（上海）有限公司 | 社招 | app.mokahr.com/social-recruitment/eaton/147226 | 171 | 40 | 24 | 2 |  |  | 09-16 |
| 正泰集团 | 社招 | app.mokahr.com/social-recruitment/chint/40744 | 335 | 39 | 33 | 3 |  |  | 08-26 |
| 云顶新耀医疗科技有限公司 | 社招 | app.mokahr.com/social-recruitment/everestmedicines/150886 | 215 | 36 | 27 | 2 |  |  | 08-13 |
| 大疆创新 | 社招 | apply.careers.dji.com/social-recruitment/dji/170070 | 539 | 34 | 30 | 0 |  |  | 08-18 |
| 华测检测认证集团股份有限公司 | 社招 | app.mokahr.com/social-recruitment/cti/145979 | 446 | 33 | 33 | 0 |  |  | 08-05 |
| 牧原实业集团 | 校招 | app.mokahr.com/campus-recruitment/muyuan/70116 | 504 | 31 | 31 | 0 |  |  | 09-04 |
| 完美世界 | 社招 | app.mokahr.com/social-recruitment/pwrd/142341 | 330 | 30 | 24 | 0 |  |  | 09-07 |
| Shopee | 社招 | app.mokahr.com/apply/shopee/2963 | 469 | 22 | 19 | 1 |  |  | 08-12 |
| 阳光电源 Sungrow | 校招 | app.mokahr.com/campus-recruitment/sungrow/94416 | 220 | 15 | 12 | 3 |  |  | 09-23 |
| 宝洁 | 社招 | app.mokahr.com/social-recruitment/pg/91934#/candidateHome/applications | 48 | 12 | 10 | 0 |  | 4 | 09-07 |
| 上海保隆汽车科技股份有限公司 | 社招 | app.mokahr.com/social-recruitment/baolong/45811 | 143 | 10 | 3 | 4 |  |  | 09-28 |
| 富途控股 | 社招 | app.mokahr.com/social-recruitment/futu5/141927 | 146 | 10 | 4 | 0 |  |  | 09-24 |
| 远景能源 Envision | 校招 | app.mokahr.com/campus_apply/envisiongroup/43123 | 368 | 10 | 9 | 0 | 1 |  | 09-10 |
| 光子跳动 Photon Dance | 社招 | app.mokahr.com/social-recruitment/guangzi/142129 | 51 | 9 | 9 | 0 |  |  | 06-25 |
| 毕马威中国 | 校招 | app.mokahr.com/campus-recruitment/kpmg/74356 | 193 | 9 | 0 | 0 |  |  | 10-09 |
| 滴滴 | 校招 | app.mokahr.com/campus-recruitment/didiglobal/96064 | 126 | 9 | 0 | 5 |  |  | 10-08 |
| 华东医药 | 校招 | app.mokahr.com/campus-recruitment/eastchinapharm/67935 | 81 | 8 | 0 | 8 |  |  | - |
| 宝洁 | 校招 | app.mokahr.com/campus-recruitment/pg/91935 | 16 | 8 | 8 | 0 |  |  | 09-29 |
| 特步 | 社招 | app.mokahr.com/social-recruitment/xtep/148870 | 102 | 8 | 0 | 2 |  |  | 10-08 |
| 菲尼克斯（南京）智能制造技术工程有限公司 | 社招 | app.mokahr.com/social-recruitment/phoenixcontact/99349 | 82 | 8 | 0 | 3 |  |  | 10-08 |
| 中控技术 | 社招 | app.mokahr.com/social-recruitment/supcon/78261 | 120 | 7 | 0 | 0 |  |  | 10-08 |
| 新浪集团 | 社招 | app.mokahr.com/social-recruitment/sina/43535 | 186 | 7 | 5 | 1 |  |  | 09-17 |
| 特步 | 校招 | app.mokahr.com/campus-recruitment/xtep/148871 | 116 | 7 | 0 | 7 |  |  | - |
| SHEIN | 校招 | app.mokahr.com/campus-recruitment/shein/2932 | 75 | 6 | 0 | 0 |  |  | 10-09 |
| 中微公司 AMEC | 校招 | app.mokahr.com/campus_apply/amec/4362 | 184 | 6 | 2 | 0 |  |  | 09-22 |
| 猿辅导 | 社招 | app.mokahr.com/social-recruitment/fenbi/45505 | 140 | 6 | 5 | 0 |  |  | 08-12 |
| 阳光电源 | 社招 | app.mokahr.com/social-recruitment/sungrow/94415 | 433 | 6 | 6 | 0 |  |  | 09-10 |
| 九毛九 | 社招 | app.mokahr.com/social-recruitment/jiumaojiu/72282 | 37 | 5 | 0 | 5 |  |  | - |
| 华润万象生活 | 社招 | app.mokahr.com/social-recruitment/crland/143066 | 274 | 5 | 4 | 0 |  |  | 09-16 |
| 唯品会 VIP.com | 社招 | app-tc.mokahr.com/social-recruitment/vipshophr/10038 | 100 | 5 | 1 | 4 |  |  | 09-24 |
| 宁波均胜电子 | 校招 | app.mokahr.com/campus-recruitment/joyson/94311 | 132 | 5 | 2 | 0 |  |  | 09-30 |
| 希望学 | 校招 | app.mokahr.com/campus-recruitment/xiwang/146380 | 35 | 5 | 0 | 3 |  |  | 10-10 |
| 森马集团 | 社招 | app.mokahr.com/social-recruitment/senma/95960 | 58 | 5 | 0 | 5 |  |  | - |
| 正泰集团 | 校招 | app.mokahr.com/campus-recruitment/chint/40745 | 208 | 5 | 1 | 0 |  |  | 09-28 |
| 西山居 | 校招 | app.mokahr.com/campus-recruitment/xishanju/37430 | 46 | 5 | 0 | 0 |  |  | 10-10 |
| 九号公司 | 校招 | app.mokahr.com/campus-recruitment/ninebot/45627 | 268 | 4 | 3 | 0 |  |  | 09-02 |
| 亚朵酒店 | 社招 | app.mokahr.com/social-recruitment/atour/151068 | 116 | 4 | 0 | 0 |  |  | 10-08 |
| 华润置地 | 校招 | app.mokahr.com/campus-recruitment/crland/168540 | 445 | 4 | 4 | 0 |  |  | 09-23 |
| 江南布衣 | 社招 | app.mokahr.com/social-recruitment/jnby/53908 | 94 | 4 | 1 | 1 |  |  | 09-28 |
| 药明合联生物技术有限公司 | 社招 | app.mokahr.com/social-recruitment/wuxixdc/164235 | 219 | 4 | 1 | 0 |  |  | 09-20 |
| 雅迪科技集团 | 校招 | app.mokahr.com/campus-recruitment/yadea/26985 | 214 | 4 | 4 | 0 |  |  | 09-14 |
| 思摩尔国际控股有限公司 | 社招 | app.mokahr.com/social-recruitment/smoore/126055 | 80 | 3 | 0 | 0 |  |  | 10-08 |
| 诺亚控股 | 校招 | app.mokahr.com/campus-recruitment/noah/26537 | 23 | 3 | 0 | 0 |  |  | 10-10 |
| 三七互娱 | 校招 | app.mokahr.com/campus-recruitment/37/58016 | 24 | 2 | 0 | 2 |  |  | - |
| 中兴通讯股份有限公司 | 社招 | app.mokahr.com/social-recruitment/zte/47588 | 240 | 2 | 1 | 1 |  |  | 09-23 |
| 兆易创新 | 校招 | app.mokahr.com/campus_apply/gigadevice/92215 | 45 | 2 | 0 | 1 |  |  | 10-08 |
| 光迅科技 | 社招 | app.mokahr.com/social-recruitment/accelink/139972 | 52 | 2 | 0 | 0 |  |  | 10-08 |
| 声网Agora | 社招 | app.mokahr.com/social-recruitment/agora/6334 | 31 | 2 | 2 | 0 |  |  | 06-30 |
| 宇通集团 | 校招 | app.mokahr.com/campus-recruitment/yutong/172567 | 40 | 2 | 0 | 2 |  |  | - |
| 安踏 ANTA | 校招 | app.mokahr.com/campus-recruitment/antahr/142914 | 177 | 2 | 0 | 2 |  |  | - |
| 巨人网络 | 社招 | app.mokahr.com/social-recruitment/ztgame/37485 | 91 | 2 | 2 | 0 |  |  | 08-02 |
| 巨人网络 | 校招 | app.mokahr.com/campus-recruitment/ztgame/92438 | 39 | 2 | 0 | 0 |  |  | 10-10 |
| 广州万孚生物技术股份有限公司 | 社招 | app.mokahr.com/social-recruitment/wondfo/19912 | 78 | 2 | 1 | 0 |  |  | 08-26 |
| 广立微电子科技（杭州）有限公司 | 社招 | app.mokahr.com/social-recruitment/semitronix/140042 | 107 | 2 | 0 | 1 |  |  | 10-09 |
| 晨光文具 | 社招 | app.mokahr.com/social-recruitment/mg/142712 | 34 | 2 | 0 | 2 |  |  | - |
| 月之暗面 Kimi | 社招 | app.mokahr.com/apply/moonshot/148506 | 102 | 2 | 0 | 0 |  |  | 10-08 |
| 沐曦集成电路 | 社招 | app.mokahr.com/social-recruitment/metax-tech/58147 | 74 | 2 | 0 | 0 |  |  | 10-08 |
| 涂鸦智能 | 社招 | app.mokahr.com/social-recruitment/tuya/3236 | 102 | 2 | 1 | 0 |  |  | 09-08 |
| 移远通信 | 社招 | app.mokahr.com/social-recruitment/quectel/24304 | 618 | 2 | 0 | 2 |  |  | - |
| 药明生物 | 校招 | app.mokahr.com/campus-recruitment/wuxibiologics/99961 | 194 | 2 | 0 | 0 |  |  | 10-09 |
| 金赛药业 | 社招 | app.mokahr.com/social-recruitment/gensci/43519 | 49 | 2 | 0 | 0 |  |  | 10-10 |
| 顾家家居股份有限公司 | 社招 | app.mokahr.com/social-recruitment/kuka/98960 | 27 | 2 | 0 | 0 |  |  | 10-09 |
| 58同城 | 社招 | jobs.58.com/social-recruitment/58/150952 | 470 | 1 | 1 | 0 |  |  | 07-21 |
| 东方财富 | 校招 | app.mokahr.com/campus-recruitment/eastmoney/92400 | 102 | 1 | 0 | 0 |  |  | 10-08 |
| 佛吉亚（中国）投资有限公司 | 社招 | app.mokahr.com/social-recruitment/faurecia/146092 | 146 | 1 | 1 | 0 |  |  | 09-30 |
| 作业帮 | 校招 | app.mokahr.com/campus-recruitment/zuoyebang/39595 | 72 | 1 | 0 | 1 |  |  | - |
| 元戎启行科技有限公司 | 社招 | app.mokahr.com/social-recruitment/deeproute/143885 | 90 | 1 | 0 | 0 |  |  | 10-09 |
| 凤凰网 | 社招 | app.mokahr.com/social-recruitment/ifeng/7541 | 27 | 1 | 0 | 0 |  |  | 10-10 |
| 南京诺唯赞生物科技股份有限公司 | 社招 | app.mokahr.com/social-recruitment/vazyme/7812 | 33 | 1 | 0 | 0 |  |  | 10-08 |
| 博乐科技 Bole Games | 社招 | app.mokahr.com/social-recruitment/bolegames/37642 | 25 | 1 | 0 | 1 |  |  | - |
| 嘉会国际医院 | 社招 | app.mokahr.com/social-recruitment/jiahui/2126 | 77 | 1 | 1 | 0 |  |  | 08-18 |
| 天数智芯（上海）半导体有限公司 | 社招 | app.mokahr.com/social-recruitment/iluvatar/98705 | 68 | 1 | 0 | 0 |  |  | 10-09 |
| 安谋科技 Arm China | 社招 | app.mokahr.com/apply/armchina/885 | 47 | 1 | 0 | 0 |  |  | 10-08 |
| 屈臣氏 | 社招 | app.mokahr.com/social-recruitment/watsons/4264 | 53 | 1 | 0 | 0 |  |  | 10-08 |
| 岚图汽车 | 校招 | app.mokahr.com/campus-recruitment/voyah/146293 | 75 | 1 | 0 | 0 |  |  | 10-10 |
| 广东培正学院控股有限公司旗下广州中望龙腾软件股份有限公司 | 社招 | app.mokahr.com/social-recruitment/zwcad/28355 | 63 | 1 | 0 | 1 |  |  | - |
| 广东联塑科技实业 | 社招 | app.mokahr.com/social-recruitment/lesso/70302 | 57 | 1 | 0 | 0 |  |  | 10-08 |
| 广联达 | 社招 | app.mokahr.com/social-recruitment/glodon/1751 | 20 | 1 | 0 | 1 |  |  | - |
| 延锋 | 社招 | app.mokahr.com/social-recruitment/yanfeng/45085 | 490 | 1 | 1 | 0 |  |  | 09-24 |
| 松下 | 社招 | app.mokahr.com/apply/panasonic/5215 | 84 | 1 | 0 | 1 |  |  | - |
| 极智嘉 Geek+ | 社招 | app.mokahr.com/apply/geekplus/5030 | 61 | 1 | 0 | 1 |  |  | - |
| 沐曦集成电路 | 校招 | app.mokahr.com/campus-recruitment/metax-tech/58131 | 97 | 1 | 0 | 0 |  |  | 10-08 |
| 深信服 | 社招 | app.mokahr.com/social-recruitment/sangfor/5367 | 92 | 1 | 0 | 1 |  |  | - |
| 盛趣游戏 Shengqu | 校招 | app.mokahr.com/campus_apply/shengqu/4078 | 53 | 1 | 1 | 0 |  |  | 09-09 |
| 福瑞泰克智能系统有限公司 | 社招 | app.mokahr.com/social-recruitment/freetech/42354 | 72 | 1 | 0 | 0 |  |  | 10-08 |
| 科华数据 | 社招 | app.mokahr.com/social-recruitment/kehua/116137 | 253 | 1 | 1 | 0 |  |  | 09-14 |
| 老板电器 | 社招 | app.mokahr.com/social-recruitment/robam/27897 | 64 | 1 | 0 | 1 |  |  | - |
| 腾讯微保 WeSure | 社招 | app-tc.mokahr.com/apply/wesure/6018 | 22 | 1 | 0 | 1 |  |  | - |
| 途虎养车 | 社招 | app.mokahr.com/social-recruitment/tuhu/6848 | 101 | 1 | 1 | 0 |  |  | 09-28 |
| 速腾聚创 | 校招 | app.mokahr.com/campus-recruitment/robosense/69887 | 101 | 1 | 0 | 1 |  |  | - |
| 顾家家居股份有限公司 | 校招 | app.mokahr.com/campus-recruitment/kuka/172508 | 53 | 1 | 0 | 1 |  |  | - |
| 中兴通讯股份有限公司（源已停用） | 校招 | app.mokahr.com/campus-recruitment/zte/94063 | 1 | 0 | 0 | 0 |  | 1 | 09-04 |
| 乐元素 Happy Elements | 校招 | app.mokahr.com/campus_apply/leyuansu/2357 | 7 | 0 | 0 | 0 |  | 7 | 06-15 |
| 作业帮（源已停用） | 社招 | app.mokahr.com/social-recruitment/zuoyebang/150144 | 3 | 0 | 0 | 0 |  | 3 | 09-23 |
| 巨人网络 Giant（源已停用） | 社招 | app.mokahr.com/apply/ztgame/37485 | 8 | 0 | 0 | 0 |  | 8 | 06-15 |
| 锐捷网络 Ruijie（源已停用） | 社招 | app.mokahr.com/apply/ruijie/26518 | 7 | 0 | 0 | 0 |  | 7 | 06-15 |

## 八、没验到的

- 「列表里有的岗页面都在招」只验了 410 行，是每个门户抽 4 行，不是全集。它不影响下架安全，
  影响的是「列表里夹不夹已关闭的岗」这个问题——没有全集证据。
- 详情请求这条信号只在国内网络上量过，没在 CI 上跑过。
- 巡检自己的判定代码没拿这批页面重跑过。中文停招文案在它的词表里，英文那 39 行不在。
- 判停招是 10-12 北京 20:26~22:10 的状态。之后对方重新开放的岗不在清单里体现，落库前必须重新确认。
- 「岗位在这个门户已停」不等于「这家公司不招这个岗了」：对方把岗挪到另一个门户时，旧链接同样显示已停。
  李宁社招一半在招行已停（168 / 328），没查它是不是把岗挪去了别的门户。
- 特斯拉门户首页数据里有一个岗状态写着 closed，详情页却有申请按钮。没查这个字段到底指什么，判定以页面为准。
- 调查脚本和逐岗结果在会话临时目录，没有进仓库。

## 九、后续（2026-10-12 晚，创始人定：按建议做）

定的是：方案 d；已停的行写 expired；不属于撤岗的行标 removed。推 main、落库之前各再确认一次。

**做了的（草稿分支，没推 main、没写库）：**

- `crawler/moka_liveness.py` + `crawler/test_moka_liveness.py`（75 个用例）+ `.github/workflows/moka-liveness.yml`。
  判据、对照、各道闸写在模块注释里。workflow 现在只能手动触发、默认只报数；定时和落库等同意后再加。
- 测试先写、先看着它红再写实现。写完把 39 处关键判据逐个改坏（172 也算已停、只问一次就下架、对照不过也继续、
  下架不带「那一轮之后没再见到」的条件、dry-run 也写库、一条源都用不上也报成功……），39 处单测全部变红。
- 提交前另派了三路只读审查（复用 / 正确性 / 效率）。采纳的：所有源都用不上时整轮变红（原先会安静地报成功）；
  加总时限，早于 workflow 超时，保证报告和台账写得出来；统计查询把 `status='active'` 放进连接条件
  （否则用不上索引、整表扫）；只认密文信封；这一轮一个岗都没见到的源记跳过而不是变红；
  库里这一轮见到的行数比抓取记录少一截的源不核；不再依赖比亚迪那个模块的线程设置。
- 本机对真库 + 真接口跑了只读演练（读库换成 psql，其余是模块自己的流程），结果见下。

**第六节那 30 行，实际处置和当时写的有一处不同：**

- 巨人网络旧地址 8 行、锐捷旧地址 7 行、乐元素 7 行、宝洁台湾岗 4 行：用现成的 `remove-jobs-by-url-prefix.yml` 跑了只报数的一轮，
  点名的行数 8 / 7 / 7 / 4，与清单一致。巨人、锐捷带了「只标在新地址下有同一个岗的」条件。
- 作业帮（门户 150144）3 行、中兴校招（门户 94063）1 行：**不标了**。查到 9 月清这类停用门户时定的口径是
  「只在停用门户出现的岗不动」，这 4 行页面在招、在别处没有第二份；这种小源名下的行每晚都能被浏览器巡检看到，停了会被正常下架。

**本机只读演练的结果（北京 10-12 23:00~00:05，读库走 psql，其余是模块自己的流程，没带 `--apply`）：**

- 全量一轮（380 条在用的源，按清存量那一次的设定把占比上限放到 0.6）：候选 7,122 行，点名要下架 7,118 行，
  读到在招 4 行（宝洁台湾岗），判不了 0 行，被闸拦下的源 0 条。**点名的 7,118 行与逐岗渲染判已停的 7,118 行逐个相同**
  （工具有而渲染清单没有 0 行，渲染清单有而工具没点名 0 行）。
  ⚠️ 这一轮跑的是审查意见修改之前的版本；判定逻辑（候选、两次都已停、对照）没变，变的是上面列的那几处闸和取数 SQL。
- 修改之后的版本另跑了三处：特步两个门户 15 个候选、15 个点名；麦当劳（带筛选的源）整条跳过；
  乐元素（源连续失败）一条源都用不上、进程退出码 2。
- 跳过的 16 条源：7 条校招源的地址不带门户号（`campus_apply/<租户>`，岗位链接里也就没有门户号，问不了详情请求）、
  6 条最近一轮没有可判的抓全率（空门户）、2 条最近一轮失败、1 条带筛选。它们名下的岗仍由浏览器巡检负责。

**还没做的：** 没在 CI 上跑过（境外出口对这个请求的回答是否一样，要推上去跑一轮只报数的才知道）。

## 十、上线（2026-10-14）

创始人 10-14 说「推」，工具推上 main（`71e6dcd8`），只能手动触发、默认只报数。

**CI 上只报数的一轮**（run 38528808621，境外 runner，占比上限放到 0.6）：382 条在用的源里 373 条可核；候选 7,189 行，
点名要下架 7,176 行，读到在招 13 行，判不了 0 行，被闸拦下的源 0 条。境外网络对详情请求的回答与国内一致（判不了 0 行就是证据）。

**和逐岗渲染对拍：** CI 点名的 7,176 行**全部有「已停止招聘」的渲染证据**——6,936 行是 10-12 渲染的，240 行是这两天新掉出列表、
10-14 补渲染的（240 / 240 已停）。10-12 渲染判已停、这次没被点名的 182 行：158 行这两天已被浏览器巡检删掉，12 行对方重新开放、
列表又见到了，9 行现在读到在招（重新开放了、列表还没刷到；10-14 渲染确认 9 / 9 在招），3 行所在的源这一轮没抓全被跳过。
读到在招的 13 行 = 这 9 行 + 宝洁台湾岗 4 行。

**落库清单**（按这一轮的点名，真正落库时以那一轮的确认为准）：115 个门户、7,176 行；占在招过半的只有李宁（167 / 331），
所以清存量那一次要把占比上限放到 0.6。

| 公司（源表里的写法） | 渠道 | 门户 | 库里在招 | 拟下架 | 占在招 |
|---|---|---|---:|---:|---:|
| 宁德时代 | 社招 | talent.catl.com/social-recruitment/catlhr/96144 | 2,722 | 904 | 33% |
| 浙江吉利控股集团 | 社招 | app.mokahr.com/social-recruitment/geely/96123 | 3,213 | 712 | 22% |
| 江苏恒瑞医药 | 社招 | app.mokahr.com/social-recruitment/hengrui/145996 | 1,546 | 561 | 36% |
| 安踏体育用品集团 | 社招 | app.mokahr.com/social-recruitment/antahr/146041 | 2,075 | 452 | 22% |
| SHEIN | 社招 | app.mokahr.com/apply/shein/2933 | 1,117 | 435 | 39% |
| 东风汽车 | 社招 | app.mokahr.com/social-recruitment/dfmc/168368 | 1,997 | 423 | 21% |
| 药明生物 | 社招 | app.mokahr.com/social-recruitment/wuxibiologics/99960 | 884 | 390 | 44% |
| 滴滴 | 社招 | app.mokahr.com/social-recruitment/didiglobal/6222 | 1,032 | 385 | 37% |
| 吉利汽车 | 校招 | campus.geely.com/campus-recruitment/geely/78436 | 2,637 | 355 | 13% |
| 特斯拉 | 社招 | app.mokahr.com/social-recruitment/tesla/46129 | 1,166 | 257 | 22% |
| 舜宇集团 | 社招 | app.mokahr.com/social-recruitment/sunnyoptical/45601 | 946 | 245 | 26% |
| 李宁 | 社招 | app.mokahr.com/social-recruitment/lining/166080 | 331 | 167 | 50% |
| 宁德时代 CATL | 校招 | app.mokahr.com/campus-recruitment/catlhr/148948 | 645 | 150 | 23% |
| 百济神州 | 社招 | app.mokahr.com/social-recruitment/beigene/98934 | 633 | 144 | 23% |
| 康龙化成（北京）新药技术股份有限公司 | 校招 | app.mokahr.com/campus-recruitment/pharmaron/44352 | 727 | 143 | 20% |
| 恒瑞医药 | 校招 | app.mokahr.com/campus-recruitment/hengrui/145997 | 1,090 | 140 | 13% |
| 作业帮 Zuoyebang | 社招 | app.mokahr.com/social-recruitment/zuoyebang/41328 | 358 | 127 | 35% |
| 宁波均胜电子 | 社招 | app.mokahr.com/social-recruitment/joyson/94310 | 421 | 113 | 27% |
| 九号公司 | 社招 | app.mokahr.com/social-recruitment/ninebot/45626 | 486 | 89 | 18% |
| 徐工集团 | 校招 | app.mokahr.com/campus-recruitment/xcmg/148091 | 658 | 70 | 11% |
| 牧原实业集团 | 社招 | app.mokahr.com/social-recruitment/muyuan/70115 | 220 | 69 | 31% |
| 鹰角网络 Hypergryph | 社招 | app.mokahr.com/apply/hypergryph/26325 | 412 | 61 | 15% |
| 锐捷网络 | 社招 | app.mokahr.com/social-recruitment/ruijie/26518 | 677 | 58 | 9% |
| 特斯拉 | 校招 | app.mokahr.com/campus-recruitment/tesla/41460 | 486 | 56 | 12% |
| 岚图汽车科技有限公司 | 社招 | app.mokahr.com/social-recruitment/voyah/146292 | 1,397 | 47 | 3% |
| 徐工机械 | 社招 | app.mokahr.com/social-recruitment/xcmg/148090 | 847 | 45 | 5% |
| 伊顿电气（上海）有限公司 | 社招 | app.mokahr.com/social-recruitment/eaton/147226 | 171 | 41 | 24% |
| 完美世界 | 社招 | app.mokahr.com/social-recruitment/pwrd/142341 | 329 | 41 | 12% |
| 云顶新耀医疗科技有限公司 | 社招 | app.mokahr.com/social-recruitment/everestmedicines/150886 | 213 | 39 | 18% |
| 正泰集团 | 社招 | app.mokahr.com/social-recruitment/chint/40744 | 332 | 36 | 11% |
| 大疆创新 | 社招 | apply.careers.dji.com/social-recruitment/dji/170070 | 537 | 31 | 6% |
| 牧原实业集团 | 校招 | app.mokahr.com/campus-recruitment/muyuan/70116 | 504 | 31 | 6% |
| 华测检测认证集团股份有限公司 | 社招 | app.mokahr.com/social-recruitment/cti/145979 | 438 | 27 | 6% |
| Shopee | 社招 | app.mokahr.com/apply/shopee/2963 | 472 | 22 | 5% |
| 滴滴 | 校招 | app.mokahr.com/campus-recruitment/didiglobal/96064 | 126 | 15 | 12% |
| 特步 | 校招 | app.mokahr.com/campus-recruitment/xtep/148871 | 115 | 15 | 13% |
| 阳光电源 Sungrow | 校招 | app.mokahr.com/campus-recruitment/sungrow/94416 | 219 | 14 | 6% |
| 法国圣戈班（中国）投资有限公司 | 社招 | app.mokahr.com/social-recruitment/saint-gobain/142246 | 74 | 13 | 18% |
| 宝洁 | 社招 | app.mokahr.com/social-recruitment/pg/91934#/candidateHome/applications | 48 | 12 | 25% |
| 富途控股 | 社招 | app.mokahr.com/social-recruitment/futu5/141927 | 146 | 11 | 8% |
| 特步 | 社招 | app.mokahr.com/social-recruitment/xtep/148870 | 108 | 10 | 9% |
| 远景能源 Envision | 校招 | app.mokahr.com/campus_apply/envisiongroup/43123 | 367 | 10 | 3% |
| 光子跳动 Photon Dance | 社招 | app.mokahr.com/social-recruitment/guangzi/142129 | 51 | 9 | 18% |
| 上海保隆汽车科技股份有限公司 | 社招 | app.mokahr.com/social-recruitment/baolong/45811 | 142 | 8 | 6% |
| 宝洁 | 校招 | app.mokahr.com/campus-recruitment/pg/91935 | 16 | 8 | 50% |
| 毕马威中国 | 校招 | app.mokahr.com/campus-recruitment/kpmg/74356 | 196 | 8 | 4% |
| 菲尼克斯（南京）智能制造技术工程有限公司 | 社招 | app.mokahr.com/social-recruitment/phoenixcontact/99349 | 86 | 7 | 8% |
| 中微公司 AMEC | 校招 | app.mokahr.com/campus_apply/amec/4362 | 185 | 6 | 3% |
| 中控技术 | 社招 | app.mokahr.com/social-recruitment/supcon/78261 | 120 | 6 | 5% |
| 新浪集团 | 社招 | app.mokahr.com/social-recruitment/sina/43535 | 187 | 6 | 3% |
| 松下 | 社招 | app.mokahr.com/apply/panasonic/5215 | 84 | 6 | 7% |
| 阳光电源 | 社招 | app.mokahr.com/social-recruitment/sungrow/94415 | 433 | 6 | 1% |
| 九毛九 | 社招 | app.mokahr.com/social-recruitment/jiumaojiu/72282 | 38 | 5 | 13% |
| 华东医药 | 校招 | app.mokahr.com/campus-recruitment/eastchinapharm/67935 | 84 | 5 | 6% |
| 唯品会 VIP.com | 社招 | app-tc.mokahr.com/social-recruitment/vipshophr/10038 | 101 | 5 | 5% |
| 宁波均胜电子 | 校招 | app.mokahr.com/campus-recruitment/joyson/94311 | 134 | 5 | 4% |
| 森马集团 | 社招 | app.mokahr.com/social-recruitment/senma/95960 | 57 | 5 | 9% |
| 正泰集团 | 校招 | app.mokahr.com/campus-recruitment/chint/40745 | 208 | 5 | 2% |
| 猿辅导 | 社招 | app.mokahr.com/social-recruitment/fenbi/45505 | 139 | 5 | 4% |
| 移远通信 | 社招 | app.mokahr.com/social-recruitment/quectel/24304 | 618 | 5 | 1% |
| 药明合联生物技术有限公司 | 社招 | app.mokahr.com/social-recruitment/wuxixdc/164235 | 219 | 5 | 2% |
| 华润万象生活 | 社招 | app.mokahr.com/social-recruitment/crland/143066 | 273 | 4 | 1% |
| 华润置地 | 校招 | app.mokahr.com/campus-recruitment/crland/168540 | 445 | 4 | 1% |
| 虎牙 Huya | 社招 | app.mokahr.com/apply/huya/4111 | 106 | 4 | 4% |
| 九号公司 | 校招 | app.mokahr.com/campus-recruitment/ninebot/45627 | 268 | 3 | 1% |
| 作业帮 | 校招 | app.mokahr.com/campus-recruitment/zuoyebang/39595 | 72 | 3 | 4% |
| 太古地产有限公司 | 社招 | app.mokahr.com/social-recruitment/swireproperties/126011 | 103 | 3 | 3% |
| 希望学 | 校招 | app.mokahr.com/campus-recruitment/xiwang/146380 | 33 | 3 | 9% |
| 思摩尔国际控股有限公司 | 社招 | app.mokahr.com/social-recruitment/smoore/126055 | 79 | 3 | 4% |
| 沐曦集成电路 | 校招 | app.mokahr.com/campus-recruitment/metax-tech/58131 | 97 | 3 | 3% |
| 西山居 | 校招 | app.mokahr.com/campus-recruitment/xishanju/37430 | 44 | 3 | 7% |
| 雅迪科技集团 | 社招 | app.mokahr.com/social-recruitment/yadea/26984 | 37 | 3 | 8% |
| 中兴通讯股份有限公司 | 社招 | app.mokahr.com/social-recruitment/zte/47588 | 241 | 2 | 1% |
| 亚朵酒店 | 社招 | app.mokahr.com/social-recruitment/atour/151068 | 113 | 2 | 2% |
| 安踏 ANTA | 校招 | app.mokahr.com/campus-recruitment/antahr/142914 | 178 | 2 | 1% |
| 岚图汽车 | 校招 | app.mokahr.com/campus-recruitment/voyah/146293 | 75 | 2 | 3% |
| 巨人网络 | 社招 | app.mokahr.com/social-recruitment/ztgame/37485 | 91 | 2 | 2% |
| 广州万孚生物技术股份有限公司 | 社招 | app.mokahr.com/social-recruitment/wondfo/19912 | 78 | 2 | 3% |
| 广立微电子科技（杭州）有限公司 | 社招 | app.mokahr.com/social-recruitment/semitronix/140042 | 107 | 2 | 2% |
| 晨光文具 | 社招 | app.mokahr.com/social-recruitment/mg/142712 | 34 | 2 | 6% |
| 月之暗面 Kimi | 社招 | app.mokahr.com/apply/moonshot/148506 | 102 | 2 | 2% |
| 沐曦集成电路 | 社招 | app.mokahr.com/social-recruitment/metax-tech/58147 | 76 | 2 | 3% |
| 涂鸦智能 | 社招 | app.mokahr.com/social-recruitment/tuya/3236 | 102 | 2 | 2% |
| 科华数据 | 社招 | app.mokahr.com/social-recruitment/kehua/116137 | 253 | 2 | 1% |
| 紫光同芯 Tsinghua IC | 社招 | app.mokahr.com/social-recruitment/tsinghuaic/39655 | 20 | 2 | 10% |
| 老板电器 | 社招 | app.mokahr.com/social-recruitment/robam/27897 | 65 | 2 | 3% |
| 药明生物 | 校招 | app.mokahr.com/campus-recruitment/wuxibiologics/99961 | 195 | 2 | 1% |
| 诺亚控股 | 校招 | app.mokahr.com/campus-recruitment/noah/26537 | 21 | 2 | 10% |
| 58同城 | 社招 | jobs.58.com/social-recruitment/58/150952 | 470 | 1 | 0% |
| SHEIN | 校招 | app.mokahr.com/campus-recruitment/shein/2932 | 70 | 1 | 1% |
| 三七互娱 | 校招 | app.mokahr.com/campus-recruitment/37/58016 | 23 | 1 | 4% |
| 东方财富 | 校招 | app.mokahr.com/campus-recruitment/eastmoney/92400 | 102 | 1 | 1% |
| 众安保险 | 社招 | app.mokahr.com/social-recruitment/zhongan/102015 | 84 | 1 | 1% |
| 佛吉亚（中国）投资有限公司 | 社招 | app.mokahr.com/social-recruitment/faurecia/146092 | 146 | 1 | 1% |
| 元戎启行科技有限公司 | 社招 | app.mokahr.com/social-recruitment/deeproute/143885 | 90 | 1 | 1% |
| 兆易创新 | 校招 | app.mokahr.com/campus_apply/gigadevice/92215 | 44 | 1 | 2% |
| 光迅科技 | 社招 | app.mokahr.com/social-recruitment/accelink/139972 | 51 | 1 | 2% |
| 北京微步在线科技有限公司 | 社招 | app.mokahr.com/social-recruitment/threatbook/27229 | 33 | 1 | 3% |
| 嘉会国际医院 | 社招 | app.mokahr.com/social-recruitment/jiahui/2126 | 78 | 1 | 1% |
| 天数智芯（上海）半导体有限公司 | 社招 | app.mokahr.com/social-recruitment/iluvatar/98705 | 68 | 1 | 1% |
| 宇通集团 | 校招 | app.mokahr.com/campus-recruitment/yutong/172567 | 39 | 1 | 3% |
| 巨人网络 | 校招 | app.mokahr.com/campus-recruitment/ztgame/92438 | 38 | 1 | 3% |
| 广东培正学院控股有限公司旗下广州中望龙腾软件股份有限公司 | 社招 | app.mokahr.com/social-recruitment/zwcad/28355 | 63 | 1 | 2% |
| 广东联塑科技实业 | 社招 | app.mokahr.com/social-recruitment/lesso/70302 | 57 | 1 | 2% |
| 延锋 | 社招 | app.mokahr.com/social-recruitment/yanfeng/45085 | 492 | 1 | 0% |
| 无忧传媒 | 校招 | app.mokahr.com/campus_apply/joymedia/7674 | 22 | 1 | 5% |
| 极智嘉 Geek+ | 社招 | app.mokahr.com/apply/geekplus/5030 | 61 | 1 | 2% |
| 江南布衣 | 社招 | app.mokahr.com/social-recruitment/jnby/53908 | 91 | 1 | 1% |
| 深信服 | 社招 | app.mokahr.com/social-recruitment/sangfor/5367 | 91 | 1 | 1% |
| 温氏食品集团 | 社招 | app.mokahr.com/social-recruitment/wens/92365 | 70 | 1 | 1% |
| 炎魂网络 | 校招 | app.mokahr.com/campus-recruitment/yanhun/24017 | 60 | 1 | 2% |
| 申通快递 | 社招 | app.mokahr.com/social-recruitment/sto/42337 | 128 | 1 | 1% |
| 速腾聚创 | 校招 | app.mokahr.com/campus-recruitment/robosense/69887 | 101 | 1 | 1% |
| 金赛药业 | 社招 | app.mokahr.com/social-recruitment/gensci/43519 | 48 | 1 | 2% |
| 顾家家居股份有限公司 | 校招 | app.mokahr.com/campus-recruitment/kuka/172508 | 53 | 1 | 2% |

## 十一、落库（2026-10-14 晚，创始人「同意，落库」）

**写库那一轮**（run 38586264097，apply=true、占比上限 0.6，UTC 15:05~16:17）：382 条源里 373 条可核，候选 7,180 行，
**下架 7,124 行**（114 条源，写 expired，次日 02:30 purge 时立墓碑），读到在招 15 行，判不了 0 行；撤岗事件 CLOSED 同样 7,124 条。
回读库：门户列表超过 3 天没见到、却还显示在招的 Moka 岗（每日体检 `jobs.moka_stale_active` 的口径）从约 7 千降到 **54**。

**三方逐行对：** 下架的 7,124 行全部在 CI 只报数那一轮的 7,176 行点名里（点名外下架 0 行），且**每一行都有「已停止招聘」的真渲染证据**
（6,890 行 10-12 渲染、234 行 10-14 渲染）。点名了却没下架的 52 行：伊顿 41 行（见下）、9 行写库前已被浏览器巡检下架、2 行这次读到在招。

**伊顿被闸拦下（control_failed）——闸门在按设计工作，不是误判：** 那一轮列表（10-13 22:47 UTC）里见到的 12 个岗，10-14 白天再问，
4 个读到已停。真渲染 4 / 4 写着「该职位已停止招聘」；本机重抓它当时的列表是 125 个岗（前一晚 130），这 4 个不在列表里、读到在招的 2 个在。
即对方在列表之后又撤了一批，列表与详情口径一致；闸门分不清「接口坏了」和「这期间又撤了」，于是整条源这一轮不下架，等下一轮列表之后再核。
⚠️ 白天撤岗勤的源会偶尔这样被跳过一天（定时排在北京 11:10，HR 已上班）——代价是晚下架一天，不会误下架。

**不属于撤岗的 26 行**（锐捷旧地址 7、巨人旧地址 8、乐元素 7、宝洁台湾岗 4）：`remove-jobs-by-url-prefix.yml` 七次运行合计标 removed 26 行（可逆，purge 不删）。
作业帮 3 行、中兴校招 1 行按 9 月「只在停用门户出现的岗不动」口径没标。

**此后：** 定时每天 UTC 03:10 写库，占比上限 0.5；体检 `pipeline.moka_liveness_ran`（当天有没有跑成）与 `jobs.moka_stale_active`（≤150）。

**次日回读（2026-10-15）：**
- 清理：purge 07:39 UTC 跑过（定时 02:30，被 GitHub 推迟），这 7,124 行全部删掉、墓碑正好 7,124 条，「既没删也没墓碑」0 行，删后同链接又插回来的在招行 0 行。
  有 4 条墓碑记着 `reopen_count=1`，是 9-14 ~ 10-12 之间那一次「关了又重开」留下的，不是这两天的事。
- 第一轮定时（run 38703914775，08:11 UTC，定时 03:10 被推迟约 5 小时）：可核 373 条源，候选 326 行，**下架 326 行**（59 条源），被闸拦下 0 条；
  伊顿 53 行（含前一天被拦的 41 行）这轮补上。326 行**逐个真渲染，326 / 326 写着「已停止招聘」**，读到在招 0。
- 陈旧在招 Moka 岗：54（10-14 晚）→ 43（10-15 体检时）→ **4**（这轮之后）。
- 体检 `pipeline.moka_liveness_ran` 10-15 记 breach（值 0），符合设计：体检北京 08:50 跑，当天的核验被推迟到下午，体检只看得到前一晚那轮，
  那轮因伊顿被拦记的是 failed。10-15 下午那轮记 success，10-16 的体检窗口含 10-15，应转绿——**要是 10-16 仍红，才是真问题**。
