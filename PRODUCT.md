# Product

## Register

product

## Users

Chinese job seekers who want official, current, and relevant openings without repeatedly checking many company career sites. They may be comparing local Chinese companies, foreign companies in China, global China roles, and research or laboratory institutions.

## Product Purpose

Job Radar helps users find verified official job openings, review matches against their preferences and resume profile, and track saved, ignored, and applied jobs per user. Success means users can trust the source, understand why a job is shown, and move from discovery to the official application page quickly.

## Brand Personality

Calm, precise, trustworthy. The product should feel like a focused instrument for opportunity discovery: quiet enough for daily use, polished enough to feel premium, and explicit about source quality.

## Anti-references

Avoid generic AI SaaS pages, purple-blue gradient marketing, three equal feature-card rows, decorative dashboard clutter, third-party job-board visual language, and anything that makes official-source verification feel casual or vague.

## Design Principles

1. Show the official-source loop clearly: local jobs, verified source refresh, and controlled source discovery should feel like distinct, understandable layers.
2. Keep the product surface task-first: users should scan jobs, compare match signals, and act without decorative friction.
3. Use warm-editorial restraint: a warm-paper canvas, strong hierarchy, generous whitespace, precise system type, **one ink-black action color** as the single CTA signal, quiet pastel accents, and careful motion. (See `DESIGN.md`; `app/globals.css` is the source of truth. Blue is only the focus ring, not the action color.)
4. Preserve trust through copy and states: failures, empty results, cached results, and pending parsers should be explained near the action that caused them.
5. Let data breathe: counts, match scores, and source diagnostics should use tabular figures and compact structure, not noisy cards.

## Accessibility & Inclusion

Target WCAG AA contrast, visible focus states, keyboard-reachable controls, reduced-motion-safe transitions, responsive layouts for mobile job scanning, and clear Chinese-first copy. Lightweight i18n scaffolding (`lib/i18n.ts`) is retained but the language switch is hidden until key pages are translated, to avoid a half-translated illusion.
