"use client";

// 企业 logo 小图标：抓到真 favicon（后端 data URI）→ 显示真图；抓不到 → 首字母暖色块兜底，覆盖率 100%、不参差。
// 真图偶发坏（onError）也切首字母兜底，绝不露白。
// 后续接入点（本轮仅接 JobCard）：CompanyInsightDrawer 头部 / SavedCompare 对比卡 / CompanyWatchQueue 关注列表。

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { monogramText, monogramColor } from "@/lib/company-logo";
import {
  getCachedLogo,
  requestCompanyLogo,
  subscribeLogo,
  type CompanyLogoState,
} from "@/lib/logo-client";

interface Props {
  company: string;
  size?: number;
  className?: string;
}

export default function CompanyLogo({ company, size = 26, className }: Props) {
  const [state, setState] = useState<CompanyLogoState | null>(() => getCachedLogo(company));
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setState(getCachedLogo(company));
    setImgFailed(false);
    requestCompanyLogo(company);
    const unsub = subscribeLogo(() => setState(getCachedLogo(company)));
    return unsub;
  }, [company]);

  const box = {
    width: size,
    height: size,
    borderRadius: Math.round(size * 0.3),
  };

  const showImg = state?.status === "found" && !!state.data && !imgFailed;
  if (showImg) {
    return (
      <span
        className={cn(
          "inline-flex flex-none items-center justify-center overflow-hidden border border-black/[0.08] bg-white dark:border-white/[0.14] dark:bg-[#f3ecdf]",
          className,
        )}
        style={box}
      >
        {/* 项目 next.config images.unoptimized=true，用原生 img 直显 data URI */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={state!.data as string}
          alt={company}
          width={size}
          height={size}
          loading="lazy"
          onError={() => setImgFailed(true)}
          className="h-full w-full object-contain"
          style={{ padding: Math.max(2, Math.round(size * 0.1)) }}
        />
      </span>
    );
  }

  const { bg, fg } = monogramColor(company);
  return (
    <span
      aria-label={company}
      className={cn("inline-flex flex-none select-none items-center justify-center font-semibold", className)}
      style={{ ...box, background: bg, color: fg, fontSize: Math.round(size * 0.44) }}
    >
      {monogramText(company)}
    </span>
  );
}
