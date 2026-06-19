-- 153 — 定向补缺失大厂（续 152）。Track 4 第二批，2026-06-19 live 探活。
-- 1) 荣耀 Honor：**hotjob**（非 moka——URL 是 wecruit SU{hash}/pb/social.html 形态，custom 域名）。
--    live 验证 career.honor.com/wecruit/positionInfo/listPosition 返回真岗（端侧AI架构师/影像ISP算法专家/
--    AI语音交互算法专家…）。httpx 档，快档 daily-crawl 即抓。
-- 2) 微众银行 WeBank：moka 租户 webankhr（app.mokahr.com 302 解析在线）。浏览器档，靠首次爬取验证产岗。
-- 3) 美团 Meituan：**company_spa 探路**（验证「通用 SPA 浏览器拦截」打法）。自建门户 zhaopin.meituan.com
--    岗位 API 走 mtgsig 签名（直连 401），page JS 渲染时浏览器自带签名→company_spa 渲染页面拦截 JSON 取岗。
--    若 anti-bot 拦无头则 0 产出（届时 disable，说明该路线对美团这类强反爬不通，需更重手段）。
-- Idempotent: guarded by source_url。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '荣耀 Honor', 'https://career.honor.com/SU61b9b9992f9d24431f5050a5/pb/social.html', 'official', 'hotjob', 'http', 'private', '手机/智能终端', '荣耀（手机/智能终端，2026-06-19 live 探活 社招真岗：端侧AI架构师/影像ISP算法专家等）'
where not exists (select 1 from sources where source_url = 'https://career.honor.com/SU61b9b9992f9d24431f5050a5/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '微众银行 WeBank', 'https://app.mokahr.com/social-recruitment/webankhr', 'official', 'moka', 'playwright', 'private', '数字银行/金融科技', '微众银行（数字银行，moka 租户 webankhr，2026-06-19 租户在线，靠首次浏览器爬取验证产岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/webankhr');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '美团 Meituan', 'https://zhaopin.meituan.com/web/position', 'official', 'company_spa', 'playwright', 'private', '本地生活/互联网', '美团（本地生活/即时配送，company_spa 探路：自建门户 mtgsig 签名 API，验证通用 SPA 浏览器拦截打法；0 产出=anti-bot 拦无头需重手段）'
where not exists (select 1 from sources where source_url = 'https://zhaopin.meituan.com/web/position');
