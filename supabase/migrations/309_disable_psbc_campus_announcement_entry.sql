-- 309：邮储银行 2027 届校招公告的投递入口先下线（创始人 2026-10-10 同意）。
--
-- 现象：这条入口指向的当期公告已被官网撤下（报名 10-07 截止）。2026-10-09 浏览器实开、
--       2026-10-10 再次请求，两次都被带到官网的「页面不存在」页；用户从 /programs 点进去就是 404。
-- 处理：只关不删。enabled = false 后读策略（enabled and verified_at is not null）不再对外展示，
--       看门狗规则 J 也不再催这条复查。
-- 重开：邮储发下一期校招公告后，把 entry_url 换成新公告、verified_at / recheck_after 往后推，
--       再把 enabled 置回 true。
update apply_programs
   set enabled = false,
       notes = coalesce(notes || E'\n', '')
               || '2026-10-10 下线：当期公告已被官网撤下（跳到页面不存在），待下一期校招公告发布后换链接重开。',
       updated_at = now()
 where entry_url = 'https://www.psbc.com/cn/gyyc/rczp/xyzp/202609/t20260907_460394.html'
   and enabled;
