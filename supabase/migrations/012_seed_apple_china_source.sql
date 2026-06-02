-- ============================================================
-- Seed Apple 在华岗位源（保留原有全球 apple 源）
-- ============================================================
-- 现有 'apple' 源把 location 固定为 united-states-USA，只抓美国岗。新增 'apple_cn'
-- 用 AppleChinaAdapter：不固定地点全局搜索 → 只保留在华/remote 岗（live 验证有
-- Shenzhen/Shanghai 岗）。两源并存：全球 + 在华。
-- 幂等：按 adapter_name 守卫。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Apple（中国区）', 'https://jobs.apple.com/en-us/search', 'official', 'apple_cn', 'http', 'Apple 在华岗位（全局搜索 + 在华过滤）'
where not exists (select 1 from sources where adapter_name = 'apple_cn');
