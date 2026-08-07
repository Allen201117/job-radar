#!/usr/bin/env bash
# 公开仓库敏感信息扫描器。
#
# 本仓库是 PUBLIC 的：提交历史、文件内容、提交者邮箱全世界可见且无法真正撤回
# （即使事后删除，别人 clone/fork 的副本仍在）。所以拦在提交之前，而不是事后补救。
#
# 用法：
#   scripts/scan-sensitive.sh --staged   # 只扫本次暂存的文件（.githooks/pre-commit 用）
#   scripts/scan-sensitive.sh --all      # 扫全部已跟踪文件（定期体检用：npm run scan:sensitive）
#
# 误报处理：优先改写内容（用占位符替代真值）。确认是误报再在下方 *_ALLOW 里加豁免，
# 不要养成 `git commit --no-verify` 的习惯——那等于把门拆了。

set -uo pipefail

mode="${1:---staged}"
root="$(git rev-parse --show-toplevel)" || exit 1
cd "$root" || exit 1

# 扫描器自身与锁文件不扫（它们必然包含规则字面量 / 大量无意义数字）
skip_file() {
  case "$1" in
    .githooks/*|scripts/scan-sensitive.sh|package-lock.json) return 0 ;;
    *) return 1 ;;
  esac
}

# 允许出现的 IPv4：私网 / 环回 / 广播 / 组播 / RFC 5737 文档示例段（测试里用的就是这些）；
# 外加浏览器 UA 里的版本号（Chrome/120.0.0.0 长得和 IP 一样）
IP_ALLOW='(^|[^0-9.])(10|127|0|255|169\.254|192\.168|172\.(1[6-9]|2[0-9]|3[01])|203\.0\.113|198\.51\.100|192\.0\.2|22[4-9]|23[0-9])\.|(Chrome|Firefox|Safari|Edge?|AppleWebKit|Version|OPR|Mobile|Gecko)/[0-9]+\.'
# 明显是占位符的连接串不算泄露
DSN_ALLOW='(your-|xxx+|placeholder|changeme|replace-me|example\.(com|invalid)|\.invalid|<[^>]*>|\$\{|:(password|pass|secret)@)'
# 测试夹具里的假邮箱
EMAIL_ALLOW='(zhangsan|lisi|wangwu|zhaoliu|test|demo|foo|bar|example|sample|dummy|user|someone|noreply)@'

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

found=0
report() { # <规则名> <文件> <grep 输出行>
  printf '  ⚠️  [%s] %s:%s\n' "$1" "$2" "$3"
  found=1
}

scan_one() { # <文件路径（用于报告）>
  local f="$1" line

  while IFS= read -r line; do report "本机绝对路径（暴露电脑用户名）" "$f" "$line"
  done < <(grep -n -I -E '/(Users|home)/[A-Za-z0-9._-]+/' "$tmp" 2>/dev/null)

  while IFS= read -r line; do report "私人邮箱" "$f" "$line"
  done < <(grep -n -I -E '[A-Za-z0-9._%+-]+@(gmail|qq|163|126|foxmail|hotmail|outlook|icloud|sina|yeah)\.(com|cn|net)' "$tmp" 2>/dev/null | grep -v -E "$EMAIL_ALLOW")

  while IFS= read -r line; do report "公网 IP（服务器地址）" "$f" "$line"
  done < <(grep -n -I -E '(^|[^0-9.])([0-9]{1,3}\.){3}[0-9]{1,3}([^0-9.]|$)' "$tmp" 2>/dev/null | grep -v -E "$IP_ALLOW")

  while IFS= read -r line; do report "疑似密钥/令牌" "$f" "$line"
  done < <(grep -n -I -E 'eyJhbGciOi|(^|[^A-Za-z0-9])sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----' "$tmp" 2>/dev/null)

  while IFS= read -r line; do report "带账号密码的连接串" "$f" "$line"
  done < <(grep -n -I -E '(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqp)://[^:/@[:space:]]+:[^@[:space:]]{8,}@' "$tmp" 2>/dev/null | grep -v -E "$DSN_ALLOW")
}

if [ "$mode" = "--all" ]; then
  while IFS= read -r -d '' f; do
    skip_file "$f" && continue
    [ -f "$f" ] || continue
    cat "$f" > "$tmp" 2>/dev/null || continue
    scan_one "$f"
  done < <(git ls-files -z)
else
  while IFS= read -r -d '' f; do
    skip_file "$f" && continue
    git show ":$f" > "$tmp" 2>/dev/null || continue
    scan_one "$f"
  done < <(git diff --cached --name-only --diff-filter=ACM -z)
fi

if [ "$found" -ne 0 ]; then
  echo ""
  echo "✋ 检测到敏感信息，已拦下。仓库是公开的，推上去就撤不回来了。"
  echo "   处理：把真值换成占位符（绝对路径 → <项目根>；IP/密码 → 只放 secret，文档里写「见 xxx secret」）。"
  echo "   确属误报：在 scripts/scan-sensitive.sh 的 *_ALLOW 里加豁免，别用 --no-verify 绕过。"
  exit 1
fi

[ "$mode" = "--all" ] && echo "✅ 全库扫描通过：没有本机路径 / 私人邮箱 / 公网 IP / 密钥。"
exit 0
