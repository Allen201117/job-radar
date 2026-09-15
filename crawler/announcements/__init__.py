"""公告制招聘：官方招聘公告抓取管道（事业单位/体制内）。

设计文档：docs/superpowers/specs/2026-09-15-announcement-recruitment-supply-design.md
- portals：官方源白名单（归属门）+ 列表页解析
- classify：可报名公告过滤 + 应届/社会 + 用人单位类型
- deadline：报名截止日 / 发布日抽取（纯函数）
- harvest：主流程（抓列表 → 抽详情 → upsert announcement_postings + ops 台账）
- expire：过期治理（截止日过期 / TTL 兜底）
"""
