-- 301 — 接入兴业银行招聘门户（job.cib.com.cn/portal，新 adapter cib，浏览器档）：1574 岗
--
-- 为什么：兴业银行是必投缺口公司，台账把入口记成 branch.cib.com.cn/ChengDu/jobs/（某分行旧页面）。
-- 2026-09-23 缺口复核找到统一门户：总行 + 全部分行 + 信用卡中心 + 子公司，社招/校招/实习同一个列表。
--
-- ── 先判定「现场签算的令牌」是什么性质（「项目更新汇总与验收」会话代创始人定的前置条件）──
--   读前端源码逐段核过（证据全文见 docs/crawler-adapter-notes.md「cib 兴业银行」）：
--   X-VALID-TOKEN = 请求体的 SM3-HMAC；X-AntiReplay-Token = SM4(访问令牌|随机数|时间戳)；密钥来自 SM2 握手。
--   输入只有请求体、时间戳、随机数、服务端下发的会话密钥 → 是 JUP 框架自带的请求完整性签名 + 防重放；
--   没有滑块、没有设备指纹、没有行为校验，图形验证码只在登录框里。→ 属于「前端公开算法的普通接口参数」，可接。
--   抓法：打开门户后调用页面自己的 jup__ajax，签名由页面代码完成，不在 Python 里复刻国密。
--
-- ── 接入前 live 验过的事实（2026-09-23，本机 adapter 端到端 fetch→parse→validate_job_quality）──
--   valid 1573 / jd_url 唯一 1573 / 站点自报 1574（差 1，fetch_complete 如实为 False）/ 正文≥60字 1573（100%）
--   社招 1167 · 校招 386 · 实习 20；地点识别为国内 1563，另 10 个站点没填工作地（总行/子公司），按国内归类。
--   逐岗详情 hash 路由：社招、校招各开一个真 id 渲染出岗位名/机构/地点/截止，假 id 只剩空壳。
--   约 19% 发布于 2023~2024 年，站点仍标「发布中 + 截止：长期」，是银行常设岗，按站点口径收。
-- ⚠️ 浏览器档（不在 httpx 快车道）：由夜间重档抓取；CI 美国出口能否打开这个门户以上线后的 crawl_runs 为准。
-- 回滚：update sources set enabled=false where adapter_name='cib';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '兴业银行', 'https://job.cib.com.cn/portal/recruit/814456617331937281?recruitType=SR', 'official', 'cib',
       'playwright', true, '{CN}', 'soe', '银行', '金融', 'soe',
       '2026-09-23 缺口复核接入：兴业银行统一招聘门户（社招/校招/实习同一列表）。live 1573 岗，正文 100%。请求签名是 JUP 框架的完整性签名+防重放（非风控），调用页面自己的请求函数抓取。'
where not exists (
  select 1 from public.sources
   where source_url = 'https://job.cib.com.cn/portal/recruit/814456617331937281?recruitType=SR');
