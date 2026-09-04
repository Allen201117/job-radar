-- 同一个 Moka 门户被登记成两个源（公司自有域名 + app.mokahr.com），岗位在库里存了两份。
--
-- 2026-09-04 live 实证：campus.geely.com 与 app.mokahr.com 指向同一个 portal（geely/78436），
-- 首页 30 个岗位 uuid 30/30 相同、总页数都是 76。后果是用户在看板上每个吉利校招岗看到两次，
-- 且「校招岗位数」虚高 —— 吉利 2,595 个在招里 2,372 个是影子。
-- 三个租户合计 3,366 行纯重复（geely 2,372 / dji 523 / 58 471）。
--
-- 保留**公司自有域名**、关掉 app.mokahr.com 那一份。依据是产品核心原则：
-- 「公开企业官网岗位 → 点击跳转官网详情」——app.mokahr.com 是第三方 ATS 域名，
-- 自有域名对用户才是官方入口。（其余 190 多个 moka 源没有自有域名，仍走 app.mokahr.com，不受影响。）
--
-- 只 disable 不删行：口径判错可以随时改回 enabled=true。
-- 对应的存量重复岗位另行标成 removed（可复活，不进 purge-expired 的永久删除）。
update sources set enabled = false
where adapter_name = 'moka'
  and source_url like '%app.mokahr.com%'
  and (   source_url like '%campus-recruitment/geely/78436%'
       or source_url like '%social-recruitment/dji/170070%'
       or source_url like '%social-recruitment/58/150952%');
