"use client";

import * as React from "react";

const STYLES = `
.an-root {
  --an-spring: linear(
    0, 0.028 2.5%, 0.0995 5%, 0.198 7.5%, 0.3106 10%, 0.4272 12.5%, 0.5405 15%,
    0.6454 17.5%, 0.7387 20%, 0.819 22.5%, 0.8856 25%, 0.9391 27.5%, 0.9803 30%,
    1.0107 32.5%, 1.0317 35%, 1.045 37.5%, 1.052 40%, 1.0543 42.5%, 1.053 45%,
    1.0493 47.5%, 1.044 50%, 1.0379 52.5%, 1.0316 55%, 1.0254 57.5%, 1.0197 60%,
    1.0146 62.5%, 1.0102 65%, 1.0065 67.5%, 1.0035 70%, 1.0012 72.5%, 0.9995 75%,
    0.9984 77.5%, 0.9976 80%, 0.9972 82.5%, 0.9971 85%, 0.9971 87.5%, 0.9973 90%,
    0.9976 92.5%, 0.9979 95%, 0.9983 97.5%, 1
  );
  --an-dist: 0.55em;
  display: inline-flex;
  align-items: baseline;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.an-slot { position: relative; display: inline-block; }
.an-layer { display: inline-block; will-change: transform, opacity, filter; }
.an-out { position: absolute; inset: 0; }
.an-in {
  animation:
    an-slide-in var(--an-dur, 450ms) var(--an-spring) both,
    an-resolve var(--an-dur, 450ms) cubic-bezier(0.22, 1, 0.36, 1) both;
}
.an-out {
  animation:
    an-slide-out var(--an-dur, 450ms) cubic-bezier(0.4, 0, 1, 1) both,
    an-dissolve var(--an-dur, 450ms) cubic-bezier(0.4, 0, 1, 1) both;
}
@keyframes an-slide-in {
  from { transform: translateY(calc(var(--an-dir, 1) * var(--an-dist))); }
  to { transform: translateY(0); }
}
@keyframes an-slide-out {
  from { transform: translateY(0); }
  to { transform: translateY(calc(var(--an-dir, 1) * var(--an-dist) * -1)); }
}
@keyframes an-resolve {
  from { opacity: 0; filter: blur(var(--an-blur, 21px)); }
  to { opacity: 1; filter: blur(0); }
}
@keyframes an-dissolve {
  from { opacity: 1; filter: blur(0); }
  to { opacity: 0; filter: blur(var(--an-blur, 21px)); }
}
@media (prefers-reduced-motion: reduce) {
  .an-in { animation: none; }
  .an-out { animation: none; display: none; }
}
.an-sr {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
`;

let stylesInjected = false;

function ensureStyles() {
  if (stylesInjected || typeof document === "undefined") return;
  stylesInjected = true;
  if (document.getElementById("animate-number-styles")) return;
  const el = document.createElement("style");
  el.id = "animate-number-styles";
  el.textContent = STYLES;
  document.head.prepend(el);
}

function joinClasses(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

const ZWSP = "\u200b";

export type AnimateNumberProps = {
  value: number;
  format?: Intl.NumberFormatOptions;
  locale?: string;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
  duration?: number;
  blur?: number;
  className?: string;
} & Omit<React.HTMLAttributes<HTMLSpanElement>, "prefix" | "children">;

function formatValue(value: number, locale: string, opts?: Intl.NumberFormatOptions) {
  try {
    return new Intl.NumberFormat(locale, opts).format(value);
  } catch {
    return String(value);
  }
}

type CharSlotProps = {
  char: string;
  direction: number;
  durationMs: number;
  blur: number;
};

function CharSlot({ char, direction, durationMs, blur }: CharSlotProps) {
  const prev = React.useRef(char);
  const genRef = React.useRef(0);
  const [state, setState] = React.useState(() => ({
    cur: char,
    out: null as string | null,
    gen: 0,
  }));

  React.useEffect(() => {
    if (char === prev.current) return;
    genRef.current += 1;
    setState({ cur: char, out: prev.current, gen: genRef.current });
    prev.current = char;
  }, [char]);

  const animating = state.out !== null;
  const style = {
    "--an-dur": `${durationMs}ms`,
    "--an-blur": `${blur}px`,
    "--an-dir": direction,
  } as React.CSSProperties;

  return (
    <span className="an-slot" style={style} aria-hidden>
      <span
        key={`in-${state.gen}`}
        className={joinClasses("an-layer", animating && "an-in")}
        onAnimationEnd={animating ? () => setState((s) => ({ ...s, out: null })) : undefined}
      >
        {state.cur === "" ? ZWSP : state.cur}
      </span>
      {animating ? (
        <span key={`out-${state.gen}`} className="an-layer an-out">
          {state.out === "" ? ZWSP : state.out}
        </span>
      ) : null}
    </span>
  );
}

export function AnimateNumber({
  value,
  format,
  locale = "zh-CN",
  prefix,
  suffix,
  duration = 450,
  blur = 18,
  className,
  ...rest
}: AnimateNumberProps) {
  ensureStyles();

  const formatted = formatValue(value, locale, format);
  const [prev, setPrev] = React.useState(value);
  const [direction, setDirection] = React.useState(1);

  if (prev !== value) {
    setDirection(value < prev ? -1 : 1);
    setPrev(value);
  }

  const chars = formatted.split("");
  const len = chars.length;
  const label = [
    typeof prefix === "string" ? prefix : "",
    formatted,
    typeof suffix === "string" ? suffix : "",
  ].join("");

  return (
    <span {...rest} className={joinClasses("an-root", className)}>
      <span className="an-sr">{label}</span>
      {prefix != null ? <span aria-hidden>{prefix}</span> : null}
      {chars.map((ch, i) => (
        <CharSlot
          key={len - 1 - i}
          char={ch}
          direction={direction}
          durationMs={duration}
          blur={blur}
        />
      ))}
      {suffix != null ? <span aria-hidden>{suffix}</span> : null}
    </span>
  );
}

export default AnimateNumber;
