"""存量修复第二批：标题明写实习、却被标成校招/留学生专项/管培生的岗，改回实习类。
口径与修好的 crawler/normalizer.extract_job_type 一致。dry-run 默认，--apply 才写库。"""
import json, os, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "crawler"))
import normalizer

URL = os.environ["JOBS_DATABASE_URL"]
APPLY = "--apply" in sys.argv

# 只看「标题里明写实习词」的岗——这是本次规则改动唯一影响到的集合
SQL = r"""select coalesce(json_agg(t),'[]'::json)::text from (
  select id, title, company, job_type, coalesce(summary,'') as summary
  from jobs
  where status='active'
    and (title like '%实习%' or lower(title) ~ '\yintern(ship)?s?\y')
    and coalesce(job_type,'') not in ('实习','暑期实习','日常实习')) t"""
rows = json.loads(subprocess.run(["psql", URL, "-t", "-A", "-c", SQL],
                                 capture_output=True, text=True, check=True).stdout.strip())
print(f"标题写着实习、但 job_type 不是实习类的岗: {len(rows)}")

changes, dist = [], collections.Counter()
for r in rows:
    new = normalizer.extract_job_type(r["title"] or "", r["summary"])
    old = r["job_type"] or "NULL"
    dist[f"{old} → {new or 'NULL'}"] += 1
    if new != r["job_type"]:
        changes.append((r["id"], new, r["title"], r["company"], old))

print("\n新旧分布:")
for k, v in dist.most_common():
    print(f"  {v:6}  {k}")
print(f"\n需要改的: {len(changes)}")
seen = collections.Counter()
print("\n样例（每种旧值抽 4 条）:")
for _id, new, title, company, old in changes:
    if seen[old] >= 4:
        continue
    seen[old] += 1
    print(f"  {old:8} → {new or 'NULL':6}  {title[:50]}  @ {company}")

if not APPLY:
    print("\n（dry-run，未写库。加 --apply 生效）")
    sys.exit(0)

BATCH, done = 500, 0
for i in range(0, len(changes), BATCH):
    chunk = changes[i:i + BATCH]
    vals = ",".join("('%s'::uuid, %s)" % (c[0], "NULL" if c[1] is None else "'" + c[1].replace("'", "''") + "'")
                    for c in chunk)
    subprocess.run(["psql", URL, "-q", "-c",
                    f"update jobs j set job_type = v.jt from (values {vals}) as v(id, jt) where j.id = v.id;"],
                   check=True)
    done += len(chunk)
    print(f"  写入 {done}/{len(changes)}")
print("完成")
