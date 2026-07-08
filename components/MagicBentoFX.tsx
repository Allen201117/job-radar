"use client";

import { useEffect, useState } from "react";
import { gsap } from "gsap";

// React Bits「MagicBento」悬浮光效，抽成全局 FX 挂到任意 .bento-glow 卡片上（不替换卡片内容）。
// 颜色统一为「雷达绿」。指针跟随光晕 + 卡片描边发光（按距离）+ 星点粒子 + 磁吸 + 点击波纹。
// 仅桌面生效；尊重 prefers-reduced-motion；用 rAF 节流近邻计算，避免大量卡片时卡顿。

const MOBILE_BREAKPOINT = 768;
const RADAR_GREEN = "0, 230, 118"; // #00E676

const createParticleElement = (x: number, y: number, color: string): HTMLDivElement => {
  const el = document.createElement("div");
  el.className = "bento-particle";
  el.style.cssText = `position:absolute;width:4px;height:4px;border-radius:50%;background:rgba(${color},1);box-shadow:0 0 6px rgba(${color},0.6);pointer-events:none;z-index:100;left:${x}px;top:${y}px;`;
  return el;
};

const updateCardGlow = (
  card: HTMLElement,
  mouseX: number,
  mouseY: number,
  glow: number,
  radius: number,
) => {
  const rect = card.getBoundingClientRect();
  const relativeX = ((mouseX - rect.left) / rect.width) * 100;
  const relativeY = ((mouseY - rect.top) / rect.height) * 100;
  card.style.setProperty("--glow-x", `${relativeX}%`);
  card.style.setProperty("--glow-y", `${relativeY}%`);
  card.style.setProperty("--glow-intensity", glow.toString());
  card.style.setProperty("--glow-radius", `${radius}px`);
};

interface MagicBentoFXProps {
  targetSelector?: string;
  glowColor?: string;
  spotlightRadius?: number;
  particleCount?: number;
  enableStars?: boolean;
  enableSpotlight?: boolean;
  enableBorderGlow?: boolean;
  enableMagnetism?: boolean;
  enableTilt?: boolean;
  clickEffect?: boolean;
  disableAnimations?: boolean;
}

const MagicBentoFX = ({
  targetSelector = ".bento-glow",
  glowColor = RADAR_GREEN,
  spotlightRadius = 300,
  particleCount = 12,
  enableStars = true,
  enableSpotlight = true,
  enableBorderGlow = true,
  enableMagnetism = true,
  enableTilt = false,
  clickEffect = true,
  disableAnimations = false,
}: MagicBentoFXProps) => {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth <= MOBILE_BREAKPOINT);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const prefersReducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const disabled = disableAnimations || isMobile || prefersReducedMotion;

  useEffect(() => {
    if (!mounted || disabled) return;

    // —— 指针跟随的全局光晕：视觉由 .bento-spotlight 按主题定义 ——
    let spotlight: HTMLDivElement | null = null;
    if (enableSpotlight) {
      spotlight = document.createElement("div");
      spotlight.className = "bento-spotlight";
      spotlight.style.cssText = `position:fixed;width:${spotlightRadius * 2.4}px;height:${spotlightRadius * 2.4}px;border-radius:50%;opacity:0;transform:translate(-50%,-50%);`;
      document.body.appendChild(spotlight);
    }

    let activeCard: HTMLElement | null = null;
    const particles: HTMLElement[] = [];
    const timeouts: ReturnType<typeof setTimeout>[] = [];

    const spawnParticles = (card: HTMLElement) => {
      if (!enableStars) return;
      const { width, height } = card.getBoundingClientRect();
      for (let i = 0; i < particleCount; i++) {
        const t = setTimeout(() => {
          if (activeCard !== card) return;
          const p = createParticleElement(Math.random() * width, Math.random() * height, glowColor);
          card.appendChild(p);
          particles.push(p);
          gsap.fromTo(p, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: "back.out(1.7)" });
          gsap.to(p, {
            x: (Math.random() - 0.5) * 100,
            y: (Math.random() - 0.5) * 100,
            rotation: Math.random() * 360,
            duration: 2 + Math.random() * 2,
            ease: "none",
            repeat: -1,
            yoyo: true,
          });
          gsap.to(p, { opacity: 0.3, duration: 1.5, ease: "power2.inOut", repeat: -1, yoyo: true });
        }, i * 100);
        timeouts.push(t);
      }
    };

    const clearParticles = () => {
      timeouts.forEach(clearTimeout);
      timeouts.length = 0;
      particles.forEach((p) =>
        gsap.to(p, {
          scale: 0,
          opacity: 0,
          duration: 0.3,
          ease: "back.in(1.7)",
          onComplete: () => p.parentNode?.removeChild(p),
        }),
      );
      particles.length = 0;
    };

    const enterCard = (card: HTMLElement) => {
      activeCard = card;
      spawnParticles(card);
    };

    const leaveCard = (card: HTMLElement) => {
      clearParticles();
      gsap.to(card, { rotateX: 0, rotateY: 0, x: 0, y: 0, duration: 0.3, ease: "power2.out" });
      card.style.setProperty("--glow-intensity", "0");
    };

    // —— rAF 节流：mousemove 只存坐标，每帧最多算一次近邻 ——
    let mouseX = 0;
    let mouseY = 0;
    let pending = false;

    const tick = () => {
      pending = false;

      // 当前指针下的卡片（rAF 里用 elementFromPoint 单次命中，O(1)，不再遍历全部卡片）
      const under = document.elementFromPoint(mouseX, mouseY) as Element | null;
      const cardUnder = (under?.closest(targetSelector) as HTMLElement | null) ?? null;
      if (cardUnder !== activeCard) {
        if (activeCard) leaveCard(activeCard);
        if (cardUnder) enterCard(cardUnder);
        activeCard = cardUnder;
      }

      // 描边发光只点亮指针正下方那张卡片 —— 与页面卡片总数无关。
      // （旧实现每帧遍历所有 .bento-glow：N 次 getBoundingClientRect 强制回流 + N 次写 CSS
      //  变量触发径向渐变重绘，几百张卡片时直接掉帧/卡顿，这里收敛为 O(1)；邻卡的氛围光交给
      //  下面这一个全局光晕渲染。）
      if (enableBorderGlow && activeCard) {
        updateCardGlow(activeCard, mouseX, mouseY, 1, spotlightRadius);
      }

      // 全局指针光晕（单个固定元素）：始终跟随指针，悬停到卡片上时提亮。
      if (spotlight) {
        gsap.to(spotlight, { left: mouseX, top: mouseY, duration: 0.1, ease: "power2.out" });
        gsap.to(spotlight, {
          opacity: cardUnder ? 0.8 : 0.18,
          duration: 0.25,
          ease: "power2.out",
        });
      }

      // 磁吸 / 倾斜：仅对指针下的卡片
      if (activeCard && (enableMagnetism || enableTilt)) {
        const r = activeCard.getBoundingClientRect();
        const x = mouseX - r.left;
        const y = mouseY - r.top;
        const cx = r.width / 2;
        const cy = r.height / 2;
        if (enableTilt) {
          gsap.to(activeCard, {
            rotateX: ((y - cy) / cy) * -8,
            rotateY: ((x - cx) / cx) * 8,
            duration: 0.2,
            ease: "power2.out",
            transformPerspective: 1000,
          });
        }
        if (enableMagnetism) {
          gsap.to(activeCard, {
            x: (x - cx) * 0.04,
            y: (y - cy) * 0.04,
            duration: 0.3,
            ease: "power2.out",
          });
        }
      }
    };

    const onMove = (e: MouseEvent) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
      if (!pending) {
        pending = true;
        requestAnimationFrame(tick);
      }
    };

    const onLeaveWindow = () => {
      if (activeCard) {
        leaveCard(activeCard);
        activeCard = null;
      }
      document.querySelectorAll<HTMLElement>(targetSelector).forEach((c) =>
        c.style.setProperty("--glow-intensity", "0"),
      );
      if (spotlight) gsap.to(spotlight, { opacity: 0, duration: 0.3, ease: "power2.out" });
    };

    const onClick = (e: MouseEvent) => {
      if (!clickEffect) return;
      const card = (e.target as Element | null)?.closest(targetSelector) as HTMLElement | null;
      if (!card) return;
      const r = card.getBoundingClientRect();
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      const maxDistance = Math.max(
        Math.hypot(x, y),
        Math.hypot(x - r.width, y),
        Math.hypot(x, y - r.height),
        Math.hypot(x - r.width, y - r.height),
      );
      const ripple = document.createElement("div");
      ripple.style.cssText = `position:absolute;width:${maxDistance * 2}px;height:${maxDistance * 2}px;border-radius:50%;background:radial-gradient(circle,rgba(${glowColor},0.4) 0%,rgba(${glowColor},0.2) 30%,transparent 70%);left:${x - maxDistance}px;top:${y - maxDistance}px;pointer-events:none;z-index:1000;`;
      card.appendChild(ripple);
      gsap.fromTo(
        ripple,
        { scale: 0, opacity: 1 },
        { scale: 1, opacity: 0, duration: 0.8, ease: "power2.out", onComplete: () => ripple.remove() },
      );
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseleave", onLeaveWindow);
    document.addEventListener("click", onClick);

    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseleave", onLeaveWindow);
      document.removeEventListener("click", onClick);
      timeouts.forEach(clearTimeout);
      particles.forEach((p) => p.parentNode?.removeChild(p));
      if (activeCard) {
        gsap.set(activeCard, { rotateX: 0, rotateY: 0, x: 0, y: 0 });
        activeCard.style.setProperty("--glow-intensity", "0");
      }
      spotlight?.parentNode?.removeChild(spotlight);
    };
  }, [
    mounted,
    disabled,
    targetSelector,
    glowColor,
    spotlightRadius,
    particleCount,
    enableStars,
    enableSpotlight,
    enableBorderGlow,
    enableMagnetism,
    enableTilt,
    clickEffect,
  ]);

  return null;
};

export default MagicBentoFX;
