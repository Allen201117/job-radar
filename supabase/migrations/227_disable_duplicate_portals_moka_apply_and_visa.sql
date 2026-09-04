-- 规则 H 第二批：同一个门户的**两种 URL 写法**各登记了一个源，同一批岗在库里存两份。
-- （224 处理的是「自有域名 vs 厂商域名」，这里是同域名不同写法 + Workday 大小写。）
--
-- ① Moka：`/apply/{tenant}/{id}` 与 `/social-recruitment/{tenant}/{id}` 是同一个门户。
--    live 用岗位 uuid 重合率验过 10 组（不是只看 URL 形态）：
--      特斯拉 1,043 个 uuid 两边都有 / 滴滴 832 / 李宁 326 / 锐捷 280 / 巨人 24 /
--      万科 20 / 广联达 19 / 同盾 16 / 金山 16 / 搜狐 13 —— 合计约 2,589 行影子。
--    保留 `-recruitment/` 写法：库里 334 个源用它、只有 62 个用 /apply/，留多数派口径统一。
--
-- ② Workday：`/wday/cxs/visa/Visa/jobs` 与 `/wday/cxs/visa/visa/jobs` **只差大小写**，
--    但大小写会一路带进 jd_url（/en-US/Visa/job/… vs /en-US/visa/job/…），
--    而 canonical_jd_url **区分大小写** ⇒ active 唯一索引拦不住 ⇒ 同岗两行。
--    live 实测：visa/Visa 833 个在招、visa/visa 703 个，其中 703 个两边都有。
--    保留租户注册的大小写 visa/Visa（岗位更全）。
--    （同形态的 Shell 由 225 处理，那条是另一个 session 引入并当天修掉的。）
--
-- 只 disable 不删行，判错可随时改回 enabled=true；存量影子行另行标 removed（可复活）。
-- 常设告警见 crawler/ops_watchdog.py 规则 H —— auto_discover 猜 slug 会让这个坑自己长回来。

-- ① Moka：只关「同 tenant/portalId 确实存在 -recruitment/ 孪生源」的那条 /apply/
update sources s set enabled = false
where s.enabled
  and s.adapter_name = 'moka'
  and s.source_url ~ '/(apply|campus_apply)/[^/]+/[0-9]+'
  and exists (
    select 1 from sources t
    where t.enabled
      and t.adapter_name = 'moka'
      and t.id <> s.id
      and t.source_url ~ '/(campus|social)-recruitment/[^/]+/[0-9]+'
      and substring(t.source_url from '/(?:campus|social)-recruitment/([^/?#]+/[0-9]+)')
        = substring(s.source_url from '/(?:apply|campus_apply)/([^/?#]+/[0-9]+)'));

-- ② Workday：关掉全小写那条（LIKE 在 Postgres 里区分大小写）
update sources set enabled = false
where enabled and source_url like '%/wday/cxs/visa/visa/%';
