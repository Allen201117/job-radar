-- 322 — 字节跳动全球站 joinbytedance.com 接成第三条源（adapter = bytedance_global），先以 enabled = false 入库
--
-- 为什么（2026-10-12 全集核实，创始人同日确认「接，按现行规则收」）：
--   字节这个招聘租户挂着 society（中文社招官网）/ campus（中文校招官网）/ en（全球站）/ jp / referral 五个门户。
--   两条官网源过去不带 website-path 头取列表，取到的不是任何一个公开门户的列表：
--     · 官网上在招、我们从没抓到的 368 个（社招 285 / 校招 83）；
--     · 我们挂着在招、中文站链接打开是「该职位已下线」的 2,148 个（社招 1,443 / 校招 705），
--       其中 1,302 个只挂在全球站（en 门户与 society / campus 两份列表交集为 0），库里字节的海外岗 1,201 行里 1,195 行在这批里。
--   同一提交把两条官网源改成按各自门户取（crawler/adapters/bytedance.py）；海外岗的官方页面在全球站，所以单开这一条。
--
-- 接入前 live 验过的事实（2026-10-12，BytedanceGlobalAdapter 端到端 robots → should_skip → fetch → parse →
--   validate_job_quality → normalize，不写库）：
--   · jobs.bytedance.com/robots.txt：Allow /experienced /society /campus /en /jp，Disallow /referral（内推门户不碰）；
--     joinbytedance.com/robots.txt 404（无限制）；should_skip = None。
--   · 列表：同一个 posts 接口带 website-path: en，自报 1,433 = 全球站页面「1,433 open」；不封顶，直接翻完，fetch_complete = True。
--   · 链接 https://joinbytedance.com/search/{编号}：30 个真渲染 30 个在招（同一批岗的中文站链接 30 个「该职位已下线」）；
--     详情接口带 en 头读状态，列表里的 120 个抽样全部在线、不在列表里的 120 个全部下线。
--   · 地点用接口给的英文名（中文名「圣地亚哥」会被判成智利，实为 San Diego）。按 regions 白名单逐岗过滤后留 1,089 个：
--     美国 594 / 新加坡 466 / 香港 28 / 北京 1；质量门 1,089/1,089。不收的 344 个是其它国家，或地点认不出国家的
--     （塔吉格 76、东京 37、迪拜 35、伦敦 30…，阿什本 7 个其实在美国但词表不认）。
--   · 类型按每岗自报的 recruit_type：社招 632 / 实习 230 / 校招 227。
--
-- regions = {CN,US,SG,Remote}：与迁移 169 给外企 ATS 源定的口径相同。带 CN 是为了全球站上的香港岗（28 个，
--   按项目口径属国内范围）不被白名单丢掉；全球站与中文站两个门户的列表交集为 0，不会和另外两条源重复。
--
-- ⚠️ 为什么先 enabled = false：库里已有约 1,000 行这批岗（挂在另外两条源名下、存的是中文站链接）。
--   先跑 bytedance-global-rehome.yml 把它们原地换成全球站链接并挪到这条源（保住 id 和首见时间），再启用。
--   反过来先启用，这条源会把同一批岗当新岗插进来，首见时间全是当天。启用另起一条迁移。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
--    segment / industry / industry_group / ownership 沿用社招那条的取值。
-- 回滚：update sources set enabled = false where source_url = 'https://joinbytedance.com/search';
-- Idempotent：where not exists，重复执行无副作用。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '字节跳动', 'https://joinbytedance.com/search', 'official',
       'bytedance_global', 'http', false, '{CN,US,SG,Remote}',
       s.segment, s.industry, s.industry_group, s.ownership,
       '2026-10-12 接入：字节跳动全球站（同一招聘租户的 en 门户），海外岗的官方页面在这里，中文站链接打开是「该职位已下线」。posts 接口带 website-path: en，live 自报 1,433、按 regions 过滤后 1,089（美国 594 / 新加坡 466 / 香港 28 / 北京 1）。先 enabled=false，存量行由 bytedance-global-rehome.yml 原地挪过来之后再启用。'
from public.sources s
where s.source_url = 'https://jobs.bytedance.com/experienced/position'
  and s.adapter_name = 'bytedance'
  and not exists (
    select 1 from public.sources where source_url = 'https://joinbytedance.com/search'
  );

-- 上面那条靠社招源的 URL 精确匹配取行业 / 归属列：对不上会安静地插 0 行。没插进去就让迁移红，别装成功。
do $$
begin
  if not exists (select 1 from public.sources where source_url = 'https://joinbytedance.com/search'
                 and adapter_name = 'bytedance_global') then
    raise exception '322: 字节全球站源没插进去（社招源 https://jobs.bytedance.com/experienced/position 没匹配上？）';
  end if;
end $$;
