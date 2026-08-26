"""同步上游已验证 ATS 租户快照；默认只校验和预览，不写文件。"""
import argparse
import csv
import io
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import ats_tenant_seed


DATA_DIR = Path(__file__).resolve().parent / "data" / "ats_tenants"
TENANT_FILES = {
    "moka.csv": "moka",
    "beisen.csv": "beisen",
    "beisen_legacy.csv": "beisen",
}
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/"
    "ats-companies/{name}.csv"
)


class SyncValidationError(RuntimeError):
    """上游快照不满足安全覆盖条件。"""


def _csv_rows(csv_text):
    """返回同时具备 name、url 的有效 CSV 行；格式错误返回 None。"""
    try:
        reader = csv.DictReader(io.StringIO(str(csv_text or "")))
        fields = {str(field or "").strip() for field in (reader.fieldnames or [])}
        if not {"name", "url"}.issubset(fields):
            return None
        return [
            row for row in reader
            if str((row or {}).get("name") or "").strip()
            and str((row or {}).get("url") or "").strip()
        ]
    except (csv.Error, TypeError, ValueError):
        return None


def _read_snapshot(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SyncValidationError("找不到现有快照：%s" % path.name) from exc
    rows = _csv_rows(text)
    if rows is None:
        raise SyncValidationError("现有快照 CSV 格式异常：%s" % path.name)
    return text, rows


def download_tenant_csv(name, *, timeout=30):
    """下载一份上游快照，返回 HTTP 状态码与 UTF-8 文本。"""
    request = Request(
        UPSTREAM_URL.format(name=name),
        headers={"User-Agent": "job-radar-ats-tenant-sync/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()))
            return status, response.read().decode("utf-8-sig")
    except (OSError, URLError, UnicodeDecodeError) as exc:
        raise SyncValidationError("下载 %s 失败：%s" % (name, exc)) from exc


def sync_tenant_snapshots(*, apply=False, data_dir=DATA_DIR, fetcher=download_tenant_csv):
    """下载、校验全部快照后再整体落盘，避免半轮覆盖。"""
    pending = []
    for filename, platform in TENANT_FILES.items():
        path = Path(data_dir) / filename
        _old_text, old_rows = _read_snapshot(path)
        name = filename[:-4]
        try:
            status, new_text = fetcher(name)
        except SyncValidationError:
            raise
        except Exception as exc:
            raise SyncValidationError("下载 %s 失败：%s" % (filename, exc)) from exc
        if int(status) != 200:
            raise SyncValidationError("%s 返回 HTTP %s，保留旧文件" % (filename, status))
        if not str(new_text or "").strip():
            raise SyncValidationError("%s 内容为空，保留旧文件" % filename)
        new_rows = _csv_rows(new_text)
        if new_rows is None:
            raise SyncValidationError("%s 缺少 name/url 列或 CSV 无法解析，保留旧文件" % filename)
        if len(new_rows) * 10 < len(old_rows) * 7:
            raise SyncValidationError(
                "%s 行数从 %d 降到 %d（低于 70%%），保留旧文件"
                % (filename, len(old_rows), len(new_rows))
            )
        old_urls = [str(row.get("url") or "") for row in old_rows]
        new_tenants = ats_tenant_seed.filter_new_tenants(
            ats_tenant_seed.parse_tenant_rows(new_text, platform), old_urls
        )
        pending.append({
            "filename": filename,
            "text": new_text,
            "old_rows": len(old_rows),
            "new_rows": len(new_rows),
            "new_tenants": len(new_tenants),
            "applied": bool(apply),
        })
    if apply:
        for row in pending:
            (Path(data_dir) / row["filename"]).write_text(row["text"], encoding="utf-8")
    return pending


def main(argv=None):
    parser = argparse.ArgumentParser(description="同步上游 ATS 租户 CSV 快照")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="仅下载、校验和打印摘要（默认）")
    mode.add_argument("--apply", action="store_true", help="校验通过后覆盖本地快照")
    args = parser.parse_args(argv)
    try:
        rows = sync_tenant_snapshots(apply=args.apply)
    except SyncValidationError as exc:
        print("[ats_tenant_sync] %s" % exc, file=sys.stderr)
        return 1
    for row in rows:
        verb = "已同步" if row["applied"] else "dry-run"
        print(
            "[ats_tenant_sync] %s：%d → %d，新增租户 %d（%s）"
            % (row["filename"], row["old_rows"], row["new_rows"], row["new_tenants"], verb)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
