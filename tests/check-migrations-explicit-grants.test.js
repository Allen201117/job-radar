const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// scripts/check-migrations.sh 的第 ④ 条：新迁移在 public 建表，必须同文件开 RLS + 写 grant（serial 列还要序列授权）。
// 背景：Supabase 2026-10-30 起新表不再自动授权 anon / authenticated / service_role，不写 grant 网站和爬虫读写就 42501；
// 不开 RLS 又给了读权限 = Security Advisor 的 rls_disabled_in_public。
// 这条检查跑在 migrate.yml 的 apply 之前，错放会让新表上线即坏、错拦会挡住正常迁移，两个方向都要钉住。

const SCRIPT = path.join(__dirname, "..", "scripts", "check-migrations.sh");

// 基线编号从脚本里读：只查前缀大于它的文件。
const BASELINE = Number(/^GRANT_BASELINE=(\d+)$/m.exec(fs.readFileSync(SCRIPT, "utf8"))[1]);
const NEXT = String(BASELINE + 1);

function runOn(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mig-grant-"));
  try {
    for (const [name, body] of Object.entries(files)) fs.writeFileSync(path.join(dir, name), body, "utf8");
    const r = spawnSync("bash", [SCRIPT.replace(/\\/g, "/"), dir.replace(/\\/g, "/")], { encoding: "utf8" });
    return { code: r.status, out: `${r.stdout}${r.stderr}` };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const sql = (...lines) => lines.join("\n") + "\n";

test("该拦：新表没写 grant → 点名文件与表", () => {
  const r = runOn({
    [`${NEXT}_new_table.sql`]: sql(
      "create table if not exists public.foo (id uuid primary key default gen_random_uuid());",
      "alter table public.foo enable row level security;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, new RegExp(`${NEXT}_new_table\\.sql 在 public 建了表 foo，没写 grant`));
});

test("该拦：新表没开 RLS（grant 写了也不行）", () => {
  const r = runOn({
    [`${NEXT}_no_rls.sql`]: sql(
      "create table foo (id uuid primary key);",
      "grant select on public.foo to anon;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 foo，没开 RLS/);
  assert.doesNotMatch(r.out, /没写 grant/);
});

test("该拦：bigserial 列没给序列授权", () => {
  const r = runOn({
    [`${NEXT}_serial.sql`]: sql(
      "create table public.bar (id bigserial primary key, v int);",
      "alter table public.bar enable row level security;",
      "grant select, insert on public.bar to service_role;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /表 bar 用了 serial 自增列，没给序列授权/);
});

test("该拦：跨行、大写、带引号的建表语句；只给了名字更长的另一张表授权不算", () => {
  const r = runOn({
    [`${NEXT}_multiline.sql`]: sql(
      "CREATE TABLE IF NOT EXISTS",
      '  public."Foo" (',
      "  id uuid primary key",
      ");",
      "ALTER TABLE public.foo ENABLE ROW LEVEL SECURITY;",
      "grant select on public.foo_log to service_role;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 foo，没写 grant/);
});

test("不该拦：写全了的新表（多表一条 grant、identity 列、serial + 序列授权、DO 块里建表）", () => {
  const r = runOn({
    [`${NEXT}_ok.sql`]: sql(
      "create table public.a (id bigint generated always as identity primary key);",
      "create table public.b (id uuid primary key);",
      "create table public.c (id bigserial primary key);",
      "alter table public.a enable row level security;",
      "alter table public.b enable row level security;",
      "alter table public.c enable row level security;",
      "revoke all on table public.a, public.b from anon, authenticated;",
      "grant select, insert, update, delete on public.a, public.b, public.c to service_role;",
      "grant usage, select on sequence public.c_id_seq to service_role;",
      "do $$ begin",
      "  create table if not exists public.d (id uuid primary key);",
      "  alter table public.d enable row level security;",
      "  grant select on public.d to authenticated;",
      "end $$;",
    ),
  });
  assert.equal(r.code, 0, r.out);
});

test("不该拦：-- no-data-api 标记（写在分号后 / 跨行建表的首行）+ 开了 RLS", () => {
  const r = runOn({
    [`${NEXT}_marker.sql`]: sql(
      "create table public.psql_only (version text primary key); -- no-data-api：只有 db-migrate.sh 用",
      "alter table public.psql_only enable row level security;",
      "create table public.psql_only2 ( -- no-data-api",
      "  version text primary key",
      ");",
      "alter table public.psql_only2 enable row level security;",
    ),
  });
  assert.equal(r.code, 0, r.out);
});

test("no-data-api 标记只管它那一张表，下一张表照查", () => {
  const r = runOn({
    [`${NEXT}_marker_scope.sql`]: sql(
      "create table public.psql_only (version text); -- no-data-api",
      "create table public.web_table (id uuid);",
      "alter table public.psql_only enable row level security;",
      "alter table public.web_table enable row level security;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 web_table，没写 grant/);
  assert.doesNotMatch(r.out, /psql_only，没写 grant/);
});

test("不该拦：基线及以前的文件、临时表、别的 schema、注释里的建表、all tables in schema", () => {
  const r = runOn({
    [`${BASELINE}_old.sql`]: "create table public.legacy (id int);\n",
    [`${NEXT}_misc.sql`]: sql(
      "-- create table public.ghost (id int);",
      "create temp table tmp_x (id int);",
      "create temporary table tmp_y (id int);",
      "create table archive.merge_snapshot as select 1 as x;",
      "create table public.e (id uuid primary key);",
      "alter table public.e enable row level security;",
      "grant select on all tables in schema public to service_role;",
    ),
  });
  assert.equal(r.code, 0, r.out);
});

// —— 以下是评审挑出来的边界，各钉一条 ——

test("该拦：URL 里的 -- 不是注释，不能把分号吃掉、让下一张表漏检", () => {
  const r = runOn({
    [`${NEXT}_url_dashes.sql`]: sql(
      "create table public.a (u text default 'https://x.example/job/Analyst--Wealth');",
      "create table public.b (id uuid primary key);",
      "alter table public.a enable row level security;",
      "alter table public.b enable row level security;",
      "grant select on public.a to service_role;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 b，没写 grant/);
});

test("该拦：给名字以表名结尾的别的序列授权（catalog_id_seq）不算 log 表的", () => {
  const r = runOn({
    [`${NEXT}_seq_boundary.sql`]: sql(
      "create table public.log (id bigserial primary key);",
      "alter table public.log enable row level security;",
      "grant select, insert on public.log to service_role;",
      "grant usage on sequence public.catalog_id_seq to service_role;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /表 log 用了 serial 自增列/);
});

test("该拦：grant execute on function public.x() 不算给表 x 授权", () => {
  const r = runOn({
    [`${NEXT}_fn_grant.sql`]: sql(
      "create table public.x (id uuid primary key);",
      "alter table public.x enable row level security;",
      "grant execute on function public.x() to authenticated;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 x，没写 grant/);
});

test("该拦：单独一行注释里提到 -- no-data-api，不免下一张表", () => {
  const r = runOn({
    [`${NEXT}_marker_doc.sql`]: sql(
      "-- 只走 psql 的表加 -- no-data-api 免授权检查",
      "create table public.web_table (id uuid primary key);",
      "alter table public.web_table enable row level security;",
    ),
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 web_table，没写 grant/);
});

test("不该拦：叫 serial 的普通列、大写标记 -- NO-DATA-API", () => {
  const r = runOn({
    [`${NEXT}_misc2.sql`]: sql(
      "create table public.s (id uuid primary key, serial text);",
      "alter table public.s enable row level security;",
      "grant select on public.s to service_role;",
      "CREATE TABLE public.psql_only (version text); -- NO-DATA-API",
      "ALTER TABLE public.psql_only ENABLE ROW LEVEL SECURITY;",
    ),
  });
  assert.equal(r.code, 0, r.out);
});

test("不该拦：授权写在最前、后面跟着几百 KB 的大文件（pipefail + grep 提前退出不能误判成没写）", () => {
  const filler = Array.from({ length: 6000 }, (_, i) => `grant select on public.other_${i} to service_role;`);
  const rlsFiller = Array.from({ length: 6000 }, (_, i) => `alter table public.other_${i} enable row level security;`);
  const r = runOn({
    [`${NEXT}_big.sql`]: sql(
      "create table public.big (id uuid primary key);",
      "alter table public.big enable row level security;",
      ...rlsFiller,
      "grant select on public.big to service_role;",
      ...filler,
    ),
  });
  assert.equal(r.code, 0, r.out);
});

test("no-data-api 标记只免授权，不免 RLS", () => {
  const r = runOn({
    [`${NEXT}_marker_no_rls.sql`]: "create table public.psql_only (version text); -- no-data-api\n",
  });
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /建了表 psql_only，没开 RLS/);
  assert.doesNotMatch(r.out, /没写 grant/);
});
