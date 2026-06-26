# 源能力表：哪些源详情页带服务端 JSON-LD JobPosting（02 spec §3.2 step 3）

> live 抽样于 2026-06-25（57 个样本，覆盖按 active 量 top-45 host + greenhouse/lever/workday/eightfold/smartrecruiters/amazon/apple/phenom 各几条）。
> 抽样脚本：原始 `httpx.get(jd_url)` 拿**服务端 HTML**，跑 `normalizer.extract_jobposting_ld(html)`。
> 关键口径：**只算服务端渲染的 JSON-LD**。JS 在浏览器里注入的 `application/ld+json` 抓不到（httpx 看不见）——
> 这正是绝大多数源拿不到官方 `posted_at` 的根因。

## 结论（一句话）

**服务端 JSON-LD JobPosting（含 `datePosted`/`validThrough`）实测只在 Workday 外站 HTML 页 + 个别 bespoke ATS（HSBC）上有；
国内 SPA 源（moka/zhiye/hotjob/feishu/byd/kuaishou/meituan/vivo/163/ctrip/aliyun/taotian/xiaohongshu…）全 JS 渲染、抓不到；
greenhouse 板页现也是 JS 渲染、服务端无 JSON-LD。**

## 有服务端 JSON-LD（可拿官方 posted_at + deadline）

| 源 / host | adapter | 实测 datePosted | validThrough | 备注 |
|---|---|---|---|---|
| `*.myworkdayjobs.com`（sanofi/astrazeneca/citi/cat/danaher/otis…） | workday | ✅（如 2026-06-15 / 2026-06-02 / 2026-05-22） | ✅ 多数有 | **最大价值**：workday 是最大外企 ATS，恰是 spec 说 `posted_at=None` 最缺时间的源 |
| `portal.careers.hsbc.com` | （bespoke/workday 系） | ✅ 2026-06-02 | ✅ 2026-11-29 | 个别 tenant |

⚠️ 同为 workday，少数 tenant/页（如 medtronic.wd1）抽不到——按 tenant/页有方差，**逐岗探测、拿不到自然回退**，不假设全有。

## 无服务端 JSON-LD（JS 渲染，httpx 抓不到 → 官方时间只能靠 adapter 接口字段或留 NULL）

moka(`app.mokahr.com`) · 智阅 `*.zhiye.com`（catl/cpgroup/cttq/genomics/cxmt/heytea/chery/…全家） · hotjob `*.hotjob.cn`（gwm/faw/tbea/yili/minmetals/tcl/sinomach/zoomlion…） · feishu `*.jobs.feishu.cn` / `*.mioffice.cn`（nio/poizon/xiaopeng/xiaomi/agirobot…） · byd(`job.byd.com`) · kuaishou(`zhaopin.kuaishou.cn`) · meituan(`zhaopin.meituan.com`) · vivo(`hr.vivo.com`) · 网易(`hr.163.com`) · ctrip(`careers.ctrip.com`) · aliyun/taotian(`careers.aliyun.com`/`talent.taotian.com`，有 ld 标签但非 JobPosting) · xiaohongshu(`job.xiaohongshu.com`) · **greenhouse `boards.greenhouse.io`**（3 样本均无，已转 JS 渲染） · amazon/apple/sf_express 的逐岗 HTML（我们富化抓的那页也无 JobPosting JSON-LD）。

## 接线现状与下一步（诚实）

- ✅ 抽取器 `normalizer.extract_jobposting_ld(html)` + 优先级合并器 `normalizer.resolve_official_times(detail_html, adapter_posted, adapter_deadline, body_text)`（**官方 JSON-LD > adapter 直填 > 正文正则**；`posted_at` 刻意不取正文正则，§4 官方 only）已就绪 + 测好（`crawler/test_jobposting_ld.py`）。
- ⏸️ **逐源 HTML 抓取接线暂缓**：唯一有 JSON-LD 的 workday，富化链路抓的是 **cxs JSON**（非 HTML），要拿它的 JSON-LD 得**额外抓一次 HTML 逐岗页**。当前 `NEWLY_DISCOVERED`（官方 posted_at 的唯一消费方）**未上 C 端**（02 §4.2），保鲜 sweep 又是热路径——**此刻为零收益加每岗一次额外抓取不划算**。
- 🎯 **触发条件**：等 `NEWLY_DISCOVERED` 真要上时，再给 workday 富化/发现链路加「逐岗 HTML 抓 JSON-LD → `resolve_official_times` 填 posted_at/deadline（仅当前为 NULL）」。本表即那时的实现地图（只对 workday/HSBC 类做，国内 SPA 别做、抓不到）。
