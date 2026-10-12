-- 329 — 华润置地 Moka 校招门户（crland/168540）：notes 记一笔「这个门户的岗按行归属到两家公司」（2026-10-12，创始人同日同意）
--
-- 只在 notes 末尾追加一段，不改 company / enabled / source_url，不动别的源。写给以后改这条源的人看。
-- 逐岗证据与全集数字：docs/reviews/2026-10-11-moka-source-identity-and-closed-portals.md §10
--
-- 背景：租户 crland 是华润置地的，这个门户（门户名「华润置地2027届秋招」）自报 441 个岗，
-- 其中 372 个的部门挂在「华润万象生活」节点下（必投清单里是另一家公司），69 个是华润置地其它航道。
-- 抓取端改成按标题末尾括号里的业务段逐行归属（crawler/adapters/china_ats.py 的 _MOKA_SHARED_PORTALS）之后，
-- 这条源名下的岗会写成两个公司名。源名「华润置地」是门户自报的名字，没挂错。
--
-- 为什么要记在 notes 里：登记是按「租户/门户号」认的，而 Moka 校招每换一期就换一个门户号。
-- 到时候改 source_url 的人如果不知道这件事，新门户的岗会全部贴回「华润置地」，且不报错。
--
-- 幂等：notes 里已经有这段就不再追加。

update sources
   set notes = concat_ws(E'\n\n', nullif(btrim(notes), ''),
       '2026-10-12 这个门户的岗按行归属到两家公司：标题末尾括号里的业务段是 商业 / 物业 / 写字楼 / 万象生活总部 的归「华润万象生活」，'
       || '其余（开发 / 文体 / 有巢 / 酒管，以及认不出的）留在「华润置地」。门户自报 441 个岗逐个对过部门：372 个归万象生活、69 个归置地。'
       || '规则登记在 crawler/adapters/china_ats.py 的 _MOKA_SHARED_PORTALS，按「租户/门户号」认——'
       || '校招换期换门户号、改这条源的 source_url 时，要先对拍新门户的标题写法再把新门户号登记进去，否则全部岗会贴回「华润置地」。'
       || '源名「华润置地」是门户自报名，别改。')
 where source_url = 'https://app.mokahr.com/campus-recruitment/crland/168540'
   and company = '华润置地'
   and coalesce(notes, '') not like '%\_MOKA\_SHARED\_PORTALS%';
