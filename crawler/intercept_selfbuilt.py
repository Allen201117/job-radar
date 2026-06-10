"""逆向自建门户的岗位 list API：playwright 加载招聘页，拦截所有 XHR/fetch，
打印「返回 JSON 且含岗位列表」的接口 URL + 请求方法 + 样例，供判断能否建 httpx adapter。
只读、不入库。用法：python3 intercept_selfbuilt.py
"""
import json
from playwright.sync_api import sync_playwright

TARGETS = {
    "网易": "https://hr.163.com/job-list.html",
    "小红书": "https://job.xiaohongshu.com/social",
    "大疆": "https://we.dji.com/zh-CN/social",
    "OPPO": "https://careers.oppo.com/university/oppo/campus/post?recruitType=Graduate",
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def jobish(j):
    s = json.dumps(j, ensure_ascii=False)[:4000]
    keys = ("position", "job", "post", "recruit", "岗位", "招聘", "title", "list", "data")
    return sum(k in s for k in keys) >= 3 and ("[" in s)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for name, url in TARGETS.items():
            hits = []
            ctx = b.new_context(user_agent=UA, locale="zh-CN")
            page = ctx.new_page()

            def on_resp(r):
                try:
                    ct = (r.headers or {}).get("content-type", "")
                    if "json" not in ct.lower():
                        return
                    j = r.json()
                    if jobish(j):
                        hits.append((r.request.method, r.url, json.dumps(j, ensure_ascii=False)[:160]))
                except Exception:
                    pass
            page.on("response", on_resp)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(7000)
            except Exception as e:
                print(f"\n### {name}: goto err {type(e).__name__}")
                ctx.close(); continue
            print(f"\n### {name} ({url}) — {len(hits)} job-ish JSON 接口")
            seen = set()
            for meth, u, sample in hits:
                base = u.split("?")[0]
                if base in seen:
                    continue
                seen.add(base)
                print(f"  [{meth}] {u[:110]}")
                print(f"        {sample}")
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
