-- 249 — 携程校招：关掉与 careers.ctrip.com 重复的 moka 影子源（2026-09-09 查实）
--
-- 现象：校招专区携程卡面「114 个校招在招岗位」，官网自报 2027 届秋招只有 56 个。
-- 根因：同一批岗进了两次——
--   ① 源「携程」https://careers.ctrip.com/（ctrip adapter，category=2 校招）→ company=携程，jd_url careers.ctrip.com/#/campus/job-detail/{id}
--   ② 源「携程集团 Trip.com」https://app.mokahr.com/campus_apply/trip/37757（moka）→ company=携程集团 Trip.com
--   两边公司名不同，canonical 唯一索引拦不住；必投清单 %携程% 又把两边都归到携程 → 卡面翻倍。
-- 证据（香港库 live）：按标题归一（去掉「（2027届秋招）」与 careers 侧的「(MJ 编号)」后缀）对拍，
--   ① 的 2027 届 52 个标题 与 ② 的 54 个标题 **重叠 52 个**，就是同一批岗。
-- 处置：留 careers.ctrip.com（官网主域，同一后端），moka 这行 disable（保留可回滚，别删）；
--   ② 名下 56 个 active 岗同日在香港库置 removed（可复活，不是 expired）。
update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-09 disable：与 careers.ctrip.com 校招（ctrip adapter category=2）是同一批岗（标题归一后 52/52 重叠），公司名不同导致重复入库、校招专区卡面翻倍（114 vs 官网 56）。moka 门户本身仍在线可渲染，这不是死源，是影子源。$md$
 where source_url = 'https://app.mokahr.com/campus_apply/trip/37757'
   and company = '携程集团 Trip.com';
