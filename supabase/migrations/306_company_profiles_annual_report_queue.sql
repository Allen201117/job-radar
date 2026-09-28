-- 306 — 年报官方事实链（crawler/official_annual_report.py）的队列状态列
--
-- ❌ 现象：insight-annual-report 自 09-22 起天天 checked=40 / written=0，看门狗规则 A 开了 issue #40。
--    CI 日志逐日 stat：09-03 parsed 30 / already_latest 3 → 09-04 already_latest 32 → 09-20 already_latest 36
--    → 09-27 already_latest 37 + section_not_found 3。
-- ✅ 根因：候选 = company_profiles 按 id 排序后与 A 股匹配、再截前 --limit（40）家 → 每天都是同一批 40 家。
--    它们的最新年报 09-03 那一轮就写完了，第 41 家往后的 A 股公司一次都轮不到（画像共 1,163+ 家）；
--    解析不出员工章节的 3 家则每天重新下载同一份 PDF。
-- ✅ 改法（代码在 official_annual_report.select_queue）：
--    ① 已写过「此刻可能存在的最新年度」年报的公司直接跳过——不占名额、不发请求（FY Y 的年报只能在 Y 年结束后发布）；
--    ② 每查一家都记下时间与结果；其余按上次尝试时间 LRU 轮转（从没查过的最先）；
--    ③ 得出定论的（写入 / 已是最新 / 找不到员工章节 / 扫描件）90 天内不再查（与 T2 insight_checked_at 的
--       TTL 同口径）；接口报错 / 查不到年报不退避、但排到队尾（「接口返 0」不能当结论，也不许插队）。
--
-- 全部幂等，只加两列、不改存量行。加无默认值的可空列只改元数据（company_profiles ≥1,163 行，
-- 取自 09-27 insight-enrich 日志「seed-from-sources：1163 源公司」）。

alter table company_profiles add column if not exists annual_report_checked_at timestamptz;  -- 空 = 从没查过
alter table company_profiles add column if not exists annual_report_result text;             -- 上次结果

comment on column company_profiles.annual_report_checked_at is
  '年报链上次查这家的时间（official_annual_report.py 写，dry-run 不写）；空=从没查过。';
comment on column company_profiles.annual_report_result is
  '年报链上次结果：parsed / already_latest / section_not_found / scanned_pdf 为定论（90 天内不重查）；failed / no_reports 不退避。';
