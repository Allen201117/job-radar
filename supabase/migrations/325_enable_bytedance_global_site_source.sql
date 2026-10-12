-- 325 — 启用字节跳动全球站那条源（迁移 324 以 enabled = false 入库的 bytedance_global）
--
-- 为什么现在可以开：324 里写的前置条件已经做完——存量行已由 bytedance-global-rehome.yml 原地挪到这条源名下
--   （2026-10-12 run 38193386893）。CI 上先 dry-run 再 apply，两次报数相同：
--   · 三份公开门户列表都抓全：全球站自报 1,433 / 过地区白名单 1,089，校招官网 7,469，社招官网 10,961；
--   · 中文站两条源在招 20,201 行：中文站上在招 18,062 行不动；挪 968 行（社招 541 / 校招 427）；
--     剩 1,171 行哪个公开门户都不在、或在全球站但地区不在白名单内，留在原源等缺席撤岗下架。
--   · 写库回读：这条源名下在招 968 行，968 行都是全球站链接、canonical 跟着变了、首见时间没动
--     （2026-07-07 ~ 2026-10-11）；中文站两条源名下没有残留的全球站链接；全球站链接在 active 里无重复。
--     抽 15 行库里现在的链接真渲染：15 个在招。
-- 开了之后：这条源下一轮按同一个 canonical upsert 这 968 行（刷新地点英文名 / 国家 / 类型），
--   并补进全球站上我们从没抓到过的岗（约 120 个）。
-- 回滚：update sources set enabled = false where source_url = 'https://joinbytedance.com/search';
-- Idempotent：where 带 enabled，重复执行无副作用。

update public.sources
   set enabled = true,
       notes = coalesce(notes, '') || E'\n\n' || '2026-10-12 启用：存量 968 行已原地挪到这条源（bytedance-global-rehome run 38193386893），回读无残留、无重复。'
 where source_url = 'https://joinbytedance.com/search'
   and adapter_name = 'bytedance_global'
   and not enabled;

-- 这条源不存在（324 没应用上）时上面是安静的 0 行：让迁移红。
do $$
begin
  if not exists (select 1 from public.sources where source_url = 'https://joinbytedance.com/search'
                 and adapter_name = 'bytedance_global' and enabled) then
    raise exception '325: 字节全球站源没有处于启用状态（324 没应用？）';
  end if;
end $$;
