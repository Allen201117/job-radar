#!/usr/bin/env bash
# 从确定性 HTML 场景生成方向 A 修订版竖屏宣传片。
# 运行：./build.sh（默认 2160×3840）或 ./build.sh 1080 1920。
# 可按需命名：OUT_NAME=jobradar-promo-a.mp4 ./build.sh 2160 3840
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FRAMES="$HERE/.work/frames"
WIDTH="${1:-${WIDTH:-2160}}"
HEIGHT="${2:-${HEIGHT:-3840}}"
OUT_NAME="${OUT_NAME:-jobradar-promo-a-revision-${WIDTH}x${HEIGHT}.mp4}"
OUT="$HERE/out/$OUT_NAME"

mkdir -p "$(dirname -- "$FRAMES")" "$(dirname -- "$OUT")"

python3 "$HERE/render.py" --fps 60 --w "$WIDTH" --h "$HEIGHT" --quality 96 --out "$FRAMES"

"${FFMPEG_BIN:-ffmpeg}" -y \
  -framerate 60 -start_number 0 -i "$FRAMES/f_%06d.jpg" \
  -vf "scale=in_range=full:out_range=tv,format=yuv420p" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -color_range tv -movflags +faststart \
  -r 60 "$OUT"

echo "成片：$OUT"
