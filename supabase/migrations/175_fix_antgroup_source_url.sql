-- 175 — 修蚂蚁集团源 URL：174 用了社招列表页 /off-campus-position 作 source_url，
-- 但蚂蚁社招详情页与列表页同 host+path、仅差 ?positionId=（normalizer _url_key 比较忽略 query）
-- → 质量门把全部 948 个社招岗误判「jd_url equals source url」拦掉（校招 path 不同幸存）。
-- 修法 = source_url 改为站点根路径（adapter 本就不读 source_url，接口端点写死在 adapters/antgroup.py）。
update sources
set source_url = 'https://talent.antgroup.com/',
    notes = '蚂蚁集团（2026-07-06 live 验证：hrcareersweb position/search 公开接口 1272 岗社招+校招，逐岗 positionId 详情可渲染，标题核验通过；source_url 用根路径避免与社招详情页同 path 撞质量门）'
where source_url = 'https://talent.antgroup.com/off-campus-position'
  and not exists (select 1 from sources where source_url = 'https://talent.antgroup.com/');
