#!/usr/bin/env python3
"""
确定性逐帧渲染器：把 scene.html 渲染成 PNG/JPEG 帧序列。

为什么不用录屏：录屏帧率取决于机器当时的负载，会掉帧、会抖。
这里反过来做——scene.html 的画面是时间 t 的纯函数，我们按帧把 t 喂进去，
每一帧都等页面画完再截图。机器再慢也只是渲染慢，成片是数学上严格等间隔的。
这就是参考视频里那种"丝滑"的来源。

用法：
  python3 render.py --stills                    # 只出几张关键帧，用来快速看效果
  python3 render.py                             # 出全片帧序列（默认 9:16 / 60fps）
  python3 render.py --shutter 2                 # 每帧多采样一次 → 后期合成运动模糊
"""
import argparse
import os
import pathlib
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="帧输出目录（默认 <scratch>/frames）")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--dur", type=float, default=None, help="覆盖场景自带时长")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--scale", type=float, default=1.0, help="deviceScaleFactor")
    ap.add_argument("--shutter", type=int, default=1,
                    help=">1 时每输出帧内多采样几次，用于后期做真运动模糊")
    ap.add_argument("--quality", type=int, default=95)
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--stills", action="store_true", help="只出 12 张等距关键帧供审阅")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 playwright：python3 -m pip install playwright", file=sys.stderr)
        return 2

    scene = HERE / "scene.html"
    if not scene.exists():
        print(f"找不到 {scene}", file=sys.stderr)
        return 2

    out = pathlib.Path(args.out) if args.out else HERE / ("stills" if args.stills else "frames")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    ext = "png" if (args.png or args.stills) else "jpg"
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[
            "--force-color-profile=srgb",
            "--disable-lcd-text",              # 关掉次像素抗锯齿，避免帧间彩边闪烁
            "--font-render-hinting=none",
            "--hide-scrollbars",
            "--disable-frame-rate-limit",
        ])
        page = browser.new_page(
            viewport={"width": args.w, "height": args.h},
            device_scale_factor=args.scale,
        )
        page.goto(scene.as_uri(), wait_until="load")
        page.evaluate(f"window.__setSize({args.w},{args.h})")
        # 等字体真的就位：中文字标一旦落在 fallback 字体上，整片气质就没了
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)

        dur = args.dur if args.dur is not None else page.evaluate("window.__DUR")
        end = args.end if args.end is not None else dur

        if args.stills:
            times = [args.start + (end - args.start) * i / 11 for i in range(12)]
            for i, t in enumerate(times):
                page.evaluate(f"window.__render({t})")
                page.screenshot(path=str(out / f"still_{i:02d}_t{t:05.2f}.png"))
                print(f"  still {i:02d}  t={t:6.2f}s")
            browser.close()
            print(f"\n关键帧已出：{out}  （{time.time()-t0:.1f}s）")
            return 0

        n = int(round((end - args.start) * args.fps))
        sub = max(1, args.shutter)
        # 快门角 ~50%：只在输出帧的前半段采样，运动模糊拖影更自然
        step = 1.0 / args.fps / sub * 0.5 if sub > 1 else 0.0
        total = n * sub
        print(f"渲染 {n} 帧 @ {args.fps}fps  {args.w}x{args.h}"
              f"{f'  ×{sub} 采样' if sub > 1 else ''}  → {out}")

        k = 0
        for f in range(n):
            base = args.start + f / args.fps
            for s in range(sub):
                t = base + s * step
                page.evaluate(f"window.__render({t})")
                p = out / f"f_{k:06d}.{ext}"
                if ext == "png":
                    page.screenshot(path=str(p))
                else:
                    page.screenshot(path=str(p), type="jpeg", quality=args.quality)
                k += 1
            if f % 60 == 0 or f == n - 1:
                el = time.time() - t0
                done = (f + 1) / n
                eta = el / done - el if done > 0 else 0
                print(f"  {f+1:5d}/{n}  {done*100:5.1f}%  已用 {el:5.1f}s  预计还要 {eta:5.1f}s",
                      flush=True)
        browser.close()

    print(f"\n完成：{k} 张 → {out}  （{time.time()-t0:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
