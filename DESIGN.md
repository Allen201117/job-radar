---
version: beta
name: warm-editorial-design-system
description: >
  Job Radar's implemented brand language is a warm-paper editorial system, not an
  Apple-blue tool. A calm parchment canvas (#f4efe6) with soft pastel wash and faint
  grain; one ink-black action color (#1a1714) as the single "click me" signal; a
  pure system sans stack (no webfonts, deliberately — see Typography); warm-white
  translucent surfaces with hairline borders and soft shadows; pastels used only as
  small status/dimension accents. Decoration (gradient wash, grain, polaroid fragments,
  float) is concentrated on the marketing / login pages; in-product surfaces stay calm
  so official-source data can be trusted at a glance.
source_of_truth: app/globals.css  # this doc describes what globals.css implements; if they disagree, the CSS wins
supersedes: the prior "Apple-design-analysis / Action Blue #0066cc / photography-first" spec (never implemented)
---

# Job Radar — Design System (warm editorial)

> This file documents the **implemented** brand language. The authoritative tokens live in
> `app/globals.css` (component classes `.btn-ink`, `.surface`, `.chip`, `.field-soft`, `.bg-editorial`…)
> and `tailwind.config`. Treat the CSS as source of truth; this doc explains intent and usage.

## Brand in one line

Calm, precise, trustworthy — a focused instrument for official-job discovery. Warm paper, ink action,
quiet pastels. It should feel premium and editorial, never like a flashy third-party job board or a
purple-blue AI-SaaS landing page.

## Colors

The action color is **ink, not blue.** A single high-contrast ink pill is the only primary CTA signal;
everything else recedes. Pastels appear only as small chips and the background wash.

```
canvas / paper        #f4efe6   editorial background (.bg-editorial base), chips, navbar
ink (action + text)   #1a1714   primary buttons (.btn-ink), headings, active nav pill
ink-hover             #2b2520
on-ink (text on ink)  #f7f1e6
text-secondary        #3f3a33
text-muted            #5f594e / #6b655a
text-faint            #8a8275 / #9a9184
surface               rgba(255,255,255,0.70)  warm-white translucent card (.surface)
surface-soft          rgba(255,255,255,0.55)
hairline border       rgba(0,0,0,0.06–0.08)
```

Pastel accent families (status / dimension chips — used sparingly, never as fills for large areas):

```
sky    bg #dceafa  text #2f6299  border #b7d2ee   社招 · 派生「岗位聚合」· timing
green  bg #e6f2d6  text #4f6f2a  border #bcdcae   校招 · fact · fresh
amber  bg #fbeecb  text #8a6312  border #e7c98a   实习 · experience · aging
lilac  bg #efe9f8  text #6a4fa0  border #cfc0e6   职业洞察 · path
teal   bg #dcf0f2  text #2f7d8a                   hiring
rose   bg #f8e6ea  text #a84f63                   culture
```

Background wash (`.bg-editorial`): paper + three soft radial pastels (sky / lemon-green / warm-orange),
plus an optional ~4% grain (`.grain`). This is a **marketing/login** flourish; keep product pages calmer.

`:root` keeps a residual blue token (`--primary: 210 100% 40%`) used **only** for the focus-visible ring
and `::selection` — it is an accessibility/system accent, not the brand action color.

## Typography

One unified **system sans** stack for the whole product — no webfonts. This is deliberate:
webfonts (e.g. Google Fonts) are unreliable behind the GFW and would break offline builds. On Mac this
resolves to SF Pro Display/Text + PingFang SC for Chinese; on Windows to Segoe UI + Microsoft YaHei.

```
--font-display: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
  "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif
```

`.display-tight` headings: same stack, letter-spacing -0.02em, antialiased. Body copy is Chinese-first,
plain and scannable. Use tabular figures for counts / match scores / diagnostics.

## Shape, surface, motion

- **Radius:** pills (`rounded-full`) for actions and chips; ~1.4rem cards (`.surface`), 1.25rem soft
  cards, 1.15rem polaroid. Global `--radius: 0.75rem`.
- **Surfaces:** warm-white translucent + hairline border + soft long shadow. `.surface-hover` lifts
  -4px on hover (reduced-motion safe).
- **Motion:** `.rise` entrance, `.float-soft` 8s drift, hover lifts — all gated by
  `prefers-reduced-motion`. Keep motion subtle and purposeful.
- **Texture flourishes (marketing/login only):** `.polaroid` product fragments, grain, the pastel wash.

## Buttons

```
.btn-ink / .btn-ink-sm   ink-black solid pill — the single primary action
.btn-ghost               outlined ghost pill — secondary
.btn-soft                warm-white soft pill — in-card / inline secondary
```

One primary ink action per view. Don't introduce competing accent-colored buttons.

## Design principles

1. **Official-source loop, legible layers.** "查已有岗位 / 更新关注公司 / 扩大官方搜索范围" read as
   distinct, understandable steps (progressive disclosure), not opaque engineering modes.
2. **Task-first product surface.** Scan jobs, compare match signals, act — without decorative friction.
   Pastels and texture stay as accents; product pages favor calm warm-white surfaces + ink.
3. **Ink restraint.** One ink action color, strong hierarchy, generous whitespace, precise type, careful
   motion. (This replaces the old "one blue action color" — blue is only the focus ring.)
4. **Trust through copy and state.** Failures, empty results, cached results, pending parsers, and
   insight availability are explained near the action that caused them, in plain Chinese — never raw
   error codes. This is the core "official / trustworthy" signal.
5. **Let data breathe.** Counts, match scores, source diagnostics use tabular figures and compact
   structure, not noisy cards.

## Official-trust signals (what makes it feel verified, not casual)

- The ink-only CTA + warm-white surfaces read as an instrument, not an ad.
- Source quality is explicit: official-source framing, fact / experience / derived chips are color-coded
  and labeled; insight cards carry attribution and a single "聚合·去标识" disclaimer.
- No third-party-jobboard flash, no purple-blue gradient AI-SaaS marketing, no decorative dashboard clutter.

## Accessibility

WCAG AA contrast, visible focus ring (the `--primary` blue at `:focus-visible`), keyboard-reachable
controls, `prefers-reduced-motion`-safe transitions, responsive mobile layouts. Chinese-first copy;
lightweight i18n scaffolding (`lib/i18n.ts`) is retained but the language switch is hidden until key
pages are translated (avoid a half-translated illusion).
