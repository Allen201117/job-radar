"""几家国有大行门户的连接兼容层：强制 IPv4 + 允许 TLS 传统重协商。

⚠️ **这两条毛病在本机测不出来，只在 CI 上炸** —— 2026-09-05 实测：本机（macOS + LibreSSL 2.8.3）
六家全部抓通，同一份代码上了 GitHub runner（Ubuntu + OpenSSL 3）之后，
建行 / 交行 / 中国移动 全部 `[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED]`，
工行 `[Errno 101] Network is unreachable`，四个源 status=failed、一个岗都没入。

两条成因（都已 live 定位，不是猜的）：

1. **IPv4**：这几家的域名 A 与 AAAA 记录**都有**（`dig +short AAAA job.icbc.com.cn` 自己看），
   而 GitHub runner 没有可用的 IPv6 出口 —— Python 先试 AAAA 就直接
   `Network is unreachable`。绑本地 `0.0.0.0` 把连接钉在 IPv4 上。

2. **TLS 传统重协商**：OpenSSL 3 默认拒绝不支持 RFC 5746 安全重协商的服务端；
   LibreSSL 不管这事，所以本机一路绿灯。打开 `OP_LEGACY_SERVER_CONNECT`（0x4）放行。
   ⚠️ 这个常量 Python 3.12 才进 `ssl` 模块，CI 上是 3.11/3.9 → 用字面量 0x4 兜底。
   ⚠️ 只放宽「重协商」这一条，**证书校验一律保持开启**（不用 verify=False）。

3. **OpenSSL ≥3.5 的抗量子混合密钥交换**（2026-10-03 Windows 本机实测）：3.5 默认先报
   X25519MLKEM768，湖南人社厅（rst.hunan.gov.cn）服务端握手直接 `[SSL: BAD_ECPOINT]`，
   curl（Windows Schannel）同一 URL 200。钉成 P-256 后 200。CI 的 OpenSSL 3.0 没有这个默认，
   所以只在 ≥3.5 时才收窄曲线 —— CI 上行为不变。

只给这几个自建门户用，不动全局默认 —— 别的源没有这个毛病，也不该跟着放宽。
"""
import ssl

import httpx

# ssl.OP_LEGACY_SERVER_CONNECT（Python 3.12+）。低版本没有这个属性，值就是 0x4。
_OP_LEGACY_SERVER_CONNECT = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
# OpenSSL 3.5 起默认带抗量子混合密钥交换，部分国内门户握手失败（见上文第 3 条）。
_OPENSSL_PQ_DEFAULT = (3, 5)


def make_ssl_context() -> ssl.SSLContext:
    """默认安全上下文 + 允许传统重协商。证书校验保持开启。"""
    context = ssl.create_default_context()
    context.options |= _OP_LEGACY_SERVER_CONNECT
    if ssl.OPENSSL_VERSION_INFO >= _OPENSSL_PQ_DEFAULT:
        context.set_ecdh_curve("prime256v1")
    return context


def make_transport(retries: int = 2) -> httpx.HTTPTransport:
    """强制 IPv4（local_address="0.0.0.0"）+ 上面那个 SSL 上下文。

    ⚠️ httpx 里 transport 一旦自带 TLS 配置，Client(verify=...) 就不再生效 ——
    所以上下文必须喂给 transport，不能喂给 Client。
    """
    return httpx.HTTPTransport(verify=make_ssl_context(), local_address="0.0.0.0",
                               retries=retries)
