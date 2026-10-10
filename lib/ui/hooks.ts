"use client";

/**
 * 组件库的行为层：把全站被反复手写的交互逻辑收成 hook。
 *
 * 收编依据是实测重复次数，不是「感觉可以抽一下」：
 *   锁滚动 + ESC 关闭  在 6 个组件里各写了一份（CompanyInsightDrawer / SavedCompare /
 *                      RegisterModal / FeedbackButton / NavbarClient / JobFilters）
 *   焦点陷阱            0 个组件有 —— 5 个弹层全部缺，键盘用户能 Tab 穿到背后的页面
 *   弹层锚定重算        只有 JobFilters 写对了一份（scroll capture + resize），其余靠 absolute
 *
 * 放 lib/ui/*.ts（不是 .tsx）同样是为了能被 tests/_load-ts.js 加载做单测。
 */
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 打开期间锁住 body 滚动，关闭时**还原成打开前的值**（不是无脑设 ""）。
 * 还原成原值这一点很重要：两个弹层叠着开时，内层关闭不该把外层的锁一起解掉。
 */
export function useBodyScrollLock(active: boolean) {
  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [active]);
}

/**
 * ESC 关闭。`active` 为假时不挂监听。
 * 用 ref 存 handler：调用方通常传内联箭头函数，直接进依赖数组会导致每次渲染都重挂监听。
 */
export function useEscapeKey(handler: () => void, active = true) {
  const saved = useRef(handler);
  saved.current = handler;

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") saved.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);
}

/** 可聚焦元素选择器：排除 disabled 与 tabindex="-1"，否则焦点会停在不可操作的元素上。 */
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * 焦点陷阱：Tab / Shift+Tab 在容器内循环，关闭后把焦点还给打开它的那个元素。
 *
 * 改造前全站 5 个弹层一个都没有 —— 键盘用户 Tab 出去之后，焦点会落在被 overflow:hidden
 * 盖住的背景内容上，看不见光标在哪，等于卡死。这是系统性缺口，所以做进原语里由 Modal 默认启用。
 *
 * ⚠️ 只改焦点行为，不改任何视觉。
 */
export function useFocusTrap(
  containerRef: React.RefObject<HTMLElement | null>,
  active: boolean,
) {
  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const container = containerRef.current;
    if (!container) return;

    const restoreTo = document.activeElement as HTMLElement | null;

    // 进场把焦点移进容器：优先第一个可聚焦元素，一个都没有就聚焦容器本身
    // （容器需要 tabIndex={-1}，Modal 已经带上了）。
    const initial = container.querySelectorAll<HTMLElement>(FOCUSABLE);
    (initial.length > 0 ? initial[0] : container).focus?.();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      // 每次按键都重新查询：弹层内容可能是异步加载出来的，进场时快照会过期。
      const items = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement as HTMLElement | null;

      if (e.shiftKey && (current === first || !container.contains(current))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (current === last || !container.contains(current))) {
        e.preventDefault();
        first.focus();
      }
    };

    container.addEventListener("keydown", onKeyDown);
    return () => {
      container.removeEventListener("keydown", onKeyDown);
      // 焦点还给触发者，否则关闭后焦点掉到 body，键盘用户得从头 Tab。
      restoreTo?.focus?.();
    };
  }, [containerRef, active]);
}

/** 点容器外部时回调。`ignore` 里的元素（通常是触发按钮）不算外部。 */
export function useClickOutside(
  containerRef: React.RefObject<HTMLElement | null>,
  handler: () => void,
  active = true,
  ignore?: React.RefObject<HTMLElement | null>,
) {
  const saved = useRef(handler);
  saved.current = handler;

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (containerRef.current?.contains(target)) return;
      // 触发按钮必须豁免：它本来就不在弹层里，不豁免的话「点它关闭」会先被判成点了外面而关闭、
      // 紧接着的 click 又把它开回来，净效果是这颗按钮永远关不掉（CLAUDE.md 记过这个坑）。
      if (ignore?.current?.contains(target)) return;
      saved.current();
    };
    // 捕获阶段监听：筛选条上的按钮会在冒泡阶段 stopPropagation（为了自己的「点触发按钮能关」），
    // 冒泡阶段的监听收不到这些点击 —— 卡片的「更多」菜单开着时去点筛选条，菜单会留在那儿。
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => window.removeEventListener("pointerdown", onPointerDown, true);
  }, [containerRef, ignore, active]);
}

export type AnchorAlign = "start" | "end" | "center";

/**
 * 把浮层锚定到触发元素下方，并在滚动 / 改窗口尺寸时重新对位。
 *
 * ⚠️ 必须配合 portal 到 body 使用，不能 absolute 定位在触发元素的容器里：
 * 筛选条内层是 overflow-x-auto，而**滚动容器两个轴都裁剪** —— 400 多 px 高的弹层会被裁进
 * 42px 高的条里，DOM 里明明有、屏幕上什么都不出现（线上实测过，CLAUDE.md 有记录）。
 *
 * scroll 必须用 capture：祖先容器的滚动不冒泡到 window，不捕获就跟不上。
 */
export function useAnchoredPosition(
  anchorRef: React.RefObject<HTMLElement | null>,
  active: boolean,
  options: { align?: AnchorAlign; gap?: number; viewportPadding?: number } = {},
) {
  const { align = "start", gap = 8, viewportPadding = 12 } = options;
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(
    null,
  );

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor || typeof window === "undefined") return;
    const rect = anchor.getBoundingClientRect();
    let left = rect.left;
    if (align === "end") left = rect.right;
    else if (align === "center") left = rect.left + rect.width / 2;
    // 夹回视窗内，避免贴边的触发器把弹层顶出屏幕。
    left = Math.max(viewportPadding, Math.min(left, window.innerWidth - viewportPadding));
    setPosition({ top: rect.bottom + gap, left, width: rect.width });
  }, [anchorRef, align, gap, viewportPadding]);

  useEffect(() => {
    if (!active || typeof window === "undefined") {
      setPosition(null);
      return;
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [active, place]);

  return position;
}

/**
 * 复制到剪贴板。返回 copied 供按钮显示「已复制」。
 * 保留 execCommand 兜底：非 HTTPS / 老浏览器下 navigator.clipboard 不存在，
 * 没有兜底就是点了没反应（静默失败，CLAUDE.md 明令禁止）。
 */
export function useClipboard(resetAfterMs = 1600) {
  const [copied, setCopied] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const copy = useCallback(
    async (text: string) => {
      let ok = false;
      try {
        if (navigator?.clipboard?.writeText) {
          await navigator.clipboard.writeText(text);
          ok = true;
        }
      } catch {
        ok = false;
      }
      if (!ok && typeof document !== "undefined") {
        try {
          const ta = document.createElement("textarea");
          ta.value = text;
          ta.setAttribute("readonly", "");
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          ok = document.execCommand("copy");
          document.body.removeChild(ta);
        } catch {
          ok = false;
        }
      }
      if (ok && mounted.current) {
        setCopied(true);
        window.setTimeout(() => {
          if (mounted.current) setCopied(false);
        }, resetAfterMs);
      }
      return ok;
    },
    [resetAfterMs],
  );

  return { copied, copy };
}

export type AsyncStatus = "idle" | "pending" | "success" | "error";

/**
 * 异步提交的三态（等待 / 成功 / 失败）+ 同步去重。
 *
 * 存在的理由是 CLAUDE.md 的「点击反馈分档」：凡是点一下要等服务端的操作，用户必须看见
 * 「它在跑」和「它成没成」。改造前这段逻辑散在各处，且好几处**失败是静默的**
 * （源开关切换失败什么都不做、取消收藏失败只是把卡片悄悄放回去）。
 *
 * 去重用 ref 不用 state：state 更新是异步的，连点两下时第二下读到的还是旧值，挡不住。
 */
export function useAsyncAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
) {
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<Error | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | undefined> => {
      if (running.current) return undefined;
      running.current = true;
      setStatus("pending");
      setError(null);
      try {
        const result = await action(...args);
        if (mounted.current) setStatus("success");
        return result;
      } catch (e) {
        // 不吞错：状态置 error 并把 Error 交出去，调用方才有话可说。
        if (mounted.current) {
          setStatus("error");
          setError(e instanceof Error ? e : new Error(String(e)));
        }
        return undefined;
      } finally {
        running.current = false;
      }
    },
    [action],
  );

  const reset = useCallback(() => {
    setStatus("idle");
    setError(null);
  }, []);

  return { run, status, error, reset, pending: status === "pending" };
}

/**
 * 「边打字边生效」的输入框（改一个字就触发搜索 / 筛选）专用：中文输入法组词期间不往上报值。
 *
 * 不处理的话，用拼音打「腾讯」时 React 的 onChange 会把 t / te / ten / teng… 逐个报上去，
 * 停顿超过防抖时间就拿「teng」去搜 —— 列表闪成骨架屏或「没有匹配」，再被真正的词盖回来；
 * 搜索埋点里还会多出一批必然 0 结果的拼音查询。
 *
 * 用法：把返回值展开到 input 上（value / onChange / onCompositionStart / onCompositionEnd）。
 * 组词期间输入框显示的是本地草稿，compositionend 时才把定稿的词交给 commit。
 */
export function useImeValue(value: string, commit: (next: string) => void) {
  const [draft, setDraft] = useState(value);
  const composing = useRef(false);
  const saved = useRef(commit);
  saved.current = commit;
  const latest = useRef(value);
  latest.current = value;
  // 同值不重复上报：Safari 在 compositionend 之后还会补一次非组词的 input，值相同；
  // 上层每次上报都会生成新的筛选对象并重搜一遍，这里拦掉。
  const push = (next: string) => {
    if (next !== latest.current) saved.current(next);
  };

  // 外部改了值（清空筛选、点 chip 删除…）→ 跟上；组词期间不跟，否则会打断输入法。
  useEffect(() => {
    if (!composing.current) setDraft(value);
  }, [value]);

  return {
    value: draft,
    onChange: (event: { target: { value: string } }) => {
      setDraft(event.target.value);
      if (!composing.current) push(event.target.value);
    },
    onCompositionStart: () => {
      composing.current = true;
    },
    onCompositionEnd: (event: { currentTarget: { value: string } }) => {
      composing.current = false;
      push(event.currentTarget.value);
    },
    // 失焦兜底：有的输入法（安卓 Gboard 打英文、部分输入法在失焦时）不发 compositionend，
    // 标志会卡在「组词中」，之后既不上报也不再跟随外部值。失焦时一律视为定稿。
    onBlur: (event: { currentTarget: { value: string } }) => {
      composing.current = false;
      push(event.currentTarget.value);
    },
  };
}
