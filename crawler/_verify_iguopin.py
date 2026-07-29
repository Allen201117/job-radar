"""国聘 live 验收：python3 crawler/_verify_iguopin.py（只读公开 API）。"""
from urllib.parse import quote

from adapters.iguopin import IguopinAdapter


COMPANIES = [
    "招商银行", "工商银行", "中国银行", "中国石油", "中国石化", "国家电网",
    "中国建筑", "中国中铁", "中国铁建", "中国电建", "中国平安", "中信证券",
]


def main():
    passed = 0
    for company in COMPANIES:
        adapter = IguopinAdapter()
        source_url = f"https://www.iguopin.com/job?company={quote(company)}"
        try:
            jobs = adapter.parse(adapter.fetch(source_url))
            linked = [job for job in jobs if job.jd_url]
            quality = [job for job in linked if len(job.summary or "") >= 60]
            sample = linked[0].jd_url if linked else "-"
            print(f"{company} | {len(jobs)} | {len(linked)} | {len(quality)} | {sample}")
            passed += bool(quality)
        except Exception as exc:
            print(f"{company} | ERROR | 0 | 0 | {type(exc).__name__}: {exc}")
    print(f"达标公司数（有至少一条 jd_url + summary≥60）：{passed}/{len(COMPANIES)}")


if __name__ == "__main__":
    main()
