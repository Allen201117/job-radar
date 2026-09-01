"""存量修复：清掉被 `"intern" in text` 裸子串误标成实习的岗，用修好的 extract_job_type 重算。

⚠️ **只处理「标题+正文里压根没有实习词」的那批**，不碰其余 job_type='实习' 的岗。
全量重算试过，会把原本标对的弄坏：extract_job_type 里校招 / 留学生 / 管培生 的判定排在实习
之前，而实习 JD 里常写「面向应届生」「留学生亦可」→ `研发实习生@文远知行` 被重算成「校招」、
`运维实习生` 被重算成「留学生专项」。那个规则顺序问题是独立 bug，不在本次范围。
本批的判据是机器可验证的（词边界正则），且人工抽样 22/22 全为误标。

dry-run 默认；--apply 才写库。口径与爬虫一致（直接 import 修好的 normalizer）。"""
import json, os, subprocess, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "crawler"))
import normalizer

URL = os.environ["JOBS_DATABASE_URL"]
APPLY = "--apply" in sys.argv

SQL = r"""select coalesce(json_agg(t),'[]'::json)::text from (
  select id, title, company, job_type, coalesce(summary,'') as summary
  from jobs
  where status='active' and job_type='实习'
    and lower(coalesce(title,'')||' '||coalesce(summary,'')) !~ '(实习|\yintern(ship)?s?\y)') t"""
raw = subprocess.run(["psql", URL, "-t", "-A", "-c", SQL], capture_output=True, text=True, check=True).stdout.strip()
rows = json.loads(raw)
print(f"待重算: {len(rows)}")

changes, dist = [], collections.Counter()
for r in rows:
    new = normalizer.extract_job_type(r["title"] or "", r["summary"])
    old = r["job_type"]
    dist[f"{old} → {new}"] += 1
    if new != old:
        changes.append((r["id"], new, r["title"], r["company"]))

print("\n新旧分布:")
for k, v in dist.most_common():
    print(f"  {v:6}  {k}")
print(f"\n需要改的: {len(changes)}")
print("\n改判样例（每种新值抽 4 条）:")
seen = collections.Counter()
for _id, new, title, company in changes:
    if seen[new] >= 4:
        continue
    seen[new] += 1
    print(f"  实习 → {new or 'NULL':6}  {title[:54]}  @ {company}")

if not APPLY:
    print("\n（dry-run，未写库。加 --apply 生效）")
    sys.exit(0)

# 分批写回，只动 job_type 一列
BATCH = 500
done = 0
for i in range(0, len(changes), BATCH):
    chunk = changes[i:i + BATCH]
    vals = ",".join(
        "('%s'::uuid, %s)" % (cid, "NULL" if nv is None else "'" + nv.replace("'", "''") + "'")
        for cid, nv, _t, _c in chunk
    )
    stmt = f"update jobs j set job_type = v.jt from (values {vals}) as v(id, jt) where j.id = v.id;"
    subprocess.run(["psql", URL, "-q", "-c", stmt], check=True)
    done += len(chunk)
    print(f"  写入 {done}/{len(changes)}")
print("完成")
