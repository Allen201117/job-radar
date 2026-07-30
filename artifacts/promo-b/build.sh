#!/usr/bin/env bash
# 方向 B 成片构建。用法：./build.sh [宽 高]
set -euo pipefail
cd "$(dirname "$0")"

W="${1:-1080}"; H="${2:-1920}"; FPS=60
WORK=".work/${W}x${H}"
OUT="out/jobradar-promo-b-${W}x${H}.mp4"

mkdir -p out
rm -rf "$WORK"; mkdir -p "$WORK"

echo "▸ 逐帧渲染 ${W}x${H} @${FPS}fps"
python3 render.py --out "$WORK" --fps "$FPS" --w "$W" --h "$H"

echo "▸ 编码"
# yuv420p + faststart：微信/抖音/小红书都能直接吃
ffmpeg -y -v error -stats -framerate "$FPS" -i "$WORK/f_%06d.jpg" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p \
  -movflags +faststart "$OUT"

echo "▸ 审阅用关键帧"
rm -rf "out/review-b"; mkdir -p "out/review-b"
python3 render.py --stills --out "out/review-b" --w "$W" --h "$H" >/dev/null
ffmpeg -y -v error -pattern_type glob -i "out/review-b/still_*.png" \
  -vf "scale=300:-1,tile=6x2:padding=6:color=0x333333" -frames:v 1 \
  "out/review-b-contact-sheet.png"

ls -la "$OUT"
echo "✓ $OUT"
