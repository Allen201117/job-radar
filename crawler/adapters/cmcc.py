"""中国移动招聘网站（job.10086.cn）适配器（纯 httpx，零浏览器、零登录）。

⚠️ 接口带**签名门**：POST /job-app/job/*.do 的 header 必须带 `digest`，否则接口返回
**HTTP 200 + {"code":"9999","message":"无效的签名"}** —— 状态码不会告诉你被拒了，
所以本 adapter 一律按 `code` 判成败（见 `_post`）。签名算法照抄站点自己的 job-center.js：

    secret = 随机 10 位字母数字
    digest = base64(md5(timestamp + secret)) + ";" + RSA_PKCS1v15(secret, 站点公钥)

公钥就是页面 JS 里 `JSEncrypt.prototype.pbkey` 的那串（2048 位，e=65537）。
RSA 这一步刻意**用标准库手写**而不是引 cryptography/pycryptodome：
只是「用公钥加密 10 个字节」，纯 int 幂运算 10 行就够，不值得给爬虫加一个二进制依赖。

正文（description 岗位描述 + dutyCondition 任职条件）**列表接口就直接给全**，所以不逐岗抓详情。
详情页是 JS 渲染的（curl 拿到的 HTML 是空壳，浏览器里才填内容）——2026-09-05 已在真实浏览器
里渲染核实岗位标题/正文/公司都在。判某个岗还活着要用 viewJob.do（不存在的 id 返 code=2000）。
"""
import base64
import hashlib
import json
import random
import string
import time
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all

# 站点 JS（/js/job-center.js 内联的 jsencrypt）里的 JSEncrypt.prototype.pbkey，原样照抄。
_PUBLIC_KEY_SPKI = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAhbieIVi00W3W1i9hYVs1EY6iYLF936QV71fmFNtsATK3"
    "m7iEbgDNo222M2uRJ1fVFyt00OkwyJ/EzvLL7M2iWK7d3fs8OAwsJd0/tBGhFvJU9YUzGibvko3KfOiUr+CMLwrG"
    "Y4cXyPUs/DHiwqVb+/JhvffKTzzpZxnmOZDY5G7q6FfLFmGueQI7h9NyqyTst1jrfJRq2QG2uDDuMNlYEjWNSHI7"
    "fg9F91xLhyNNKIO1a3dcpLi8HZEtm4mgs1+i2xH49EzVjLyFjep91nqNUrauXVr22DMGfuggeAzuRxlqo1bVNg9p"
    "C1EtcTg4GkWURf4FWngXo4ntHpGcd+hecwIDAQAB"
)


def _der_read(buf: bytes, offset: int):
    """读一个 DER TLV，返回 (tag, value, 下一个 TLV 的偏移)。只够解析 SPKI，不是通用 ASN.1。"""
    tag = buf[offset]
    length = buf[offset + 1]
    offset += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(buf[offset:offset + size], "big")
        offset += size
    return tag, buf[offset:offset + length], offset + length


def _rsa_public_numbers(spki_b64: str):
    """SubjectPublicKeyInfo(base64) → (n, e)。结构：SEQ{ SEQ{OID,NULL}, BITSTRING{ SEQ{n,e} } }。"""
    der = base64.b64decode(spki_b64)
    _, outer, _ = _der_read(der, 0)
    _, _algorithm, next_offset = _der_read(outer, 0)
    _, bitstring, _ = _der_read(outer, next_offset)
    _, rsa_seq, _ = _der_read(bitstring[1:], 0)   # bitstring[0] 是 unused-bits 计数
    _, modulus, next_offset = _der_read(rsa_seq, 0)
    _, exponent, _ = _der_read(rsa_seq, next_offset)
    return int.from_bytes(modulus, "big"), int.from_bytes(exponent, "big")


_N, _E = _rsa_public_numbers(_PUBLIC_KEY_SPKI)


def _rsa_encrypt_pkcs1v15(message: bytes) -> str:
    """RFC 8017 §7.2.1 公钥加密，返回 base64（与站点 JSEncrypt.encrypt 的输出同形）。"""
    key_size = (_N.bit_length() + 7) // 8
    padding = bytes(random.randrange(1, 256) for _ in range(key_size - 3 - len(message)))
    block = b"\x00\x02" + padding + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), _E, _N)
    return base64.b64encode(cipher.to_bytes(key_size, "big")).decode()


def _sign_header() -> dict:
    now_ms = int(time.time() * 1000)
    secret = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(10))
    md5_hex = hashlib.md5(f"{now_ms}{secret}".encode()).hexdigest()
    return {
        "version": "1.0",
        "timestamp": now_ms,
        "digest": base64.b64encode(md5_hex.encode()).decode() + ";" + _rsa_encrypt_pkcs1v15(secret.encode()),
        "conversationId": time.strftime("%Y%m%d%H%M%S", time.localtime(now_ms / 1000)) + f"{now_ms % 1000:03d}",
    }


def _clean(value) -> str:
    return str(value or "").strip()


class CmccAdapter(BaseAdapter):
    name = "cmcc"

    LIST_API = "https://job.10086.cn/job-app/job/searchJobs.do"
    LIST_REFERER = "https://job.10086.cn/personal/job/"
    DETAIL_URL = "https://job.10086.cn/personal/job/detail.html?id={job_id}"
    # 站点自己给校招岗（type=1）的链接会多带一个 typess 参数，照抄以保持与官网逐字一致。
    DETAIL_URL_CAMPUS = "https://job.10086.cn/personal/job/detail.html?id={job_id}&typess=1"
    PAGE_SIZE = 100
    MAX_PAGES = 200

    # type 取值来自列表页筛选器「招聘类型」：1=校园招聘 / 2=社会招聘 / 3=实习生招聘。
    _JOB_TYPES = {"1": "校招", "2": "社招", "3": "实习"}

    @classmethod
    def _detail_url(cls, row: dict) -> str:
        job_id = _clean(row.get("id"))
        template = cls.DETAIL_URL_CAMPUS if _clean(row.get("type")) == "1" else cls.DETAIL_URL
        return template.format(job_id=job_id)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        parts = []
        description = _clean(row.get("description"))
        duty = _clean(row.get("dutyCondition"))
        if description:
            parts.append(f"【岗位描述】\n{description}")
        if duty:
            parts.append(f"【任职条件】\n{duty}")
        return "\n".join(parts) or None

    @staticmethod
    def _location_of(row: dict) -> Optional[str]:
        province = _clean(row.get("province"))
        city = _clean(row.get("city"))
        if province and city and city not in province:
            return f"{province}{city}"
        return city or province or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
            "Referer": self.LIST_REFERER,
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, json={
                    "serviceName": "searchJobs",
                    "header": _sign_header(),
                    "data": {"pageNo": page, "pageSize": self.PAGE_SIZE},
                })
                response.raise_for_status()
                payload = response.json() or {}
                # 签名失败 / 服务异常都是 HTTP 200，只有 code 说了实话——不能安静返 0 条。
                if payload.get("code") != "0000":
                    raise RuntimeError(
                        f"cmcc: searchJobs code={payload.get('code')} msg={payload.get('message')}")
                data = payload.get("data") or {}
                rows = data.get("jobList")
                if not isinstance(rows, list):
                    raise RuntimeError("cmcc: searchJobs data.jobList is not a list")
                return PageResult(items=rows, total=_int_or_none(data.get("total")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="cmcc",
            )
        if not rows:
            raise RuntimeError("cmcc: searchJobs returned no jobs")
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = _clean(row.get("id"))
            title = _clean(row.get("name"))
            if not (job_id and title):
                continue
            jd_url = self._detail_url(row)
            jobs.append(RawJob(
                company="", title=title,
                location=self._location_of(row),
                job_type=self._JOB_TYPES.get(_clean(row.get("type"))),
                summary=self._summary_of(row),
                jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("startTime")) or None,
                deadline=_clean(row.get("endTime")) or None,
            ))
        return jobs


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
