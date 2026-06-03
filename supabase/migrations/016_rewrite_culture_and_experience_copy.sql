-- ============================================================
-- 016 文案合规改版：culture 去「避坑」+ 9 条 experience 正文改通俗（去重复媒体罗列）
-- ============================================================
-- B3：culture 标题与 payload.tone 的「（避坑提示）」→「温馨提示」。
-- B4：9 条 experience 正文改通俗，去掉每条重复的「据界面新闻、脉脉等…聚合（去标识化）」
--     媒体罗列（该声明改为只在抽屉顶部统一出现一次）；正文保留一句轻量归因
--     （据公开讨论 / 据公开报道）以通过 lib/insight-verification.ts 的 passesAssertionLint。
-- 不改 insight_sources（来源 chip 仍由 015 的真实链接展示）；不放宽校验门。
-- 幂等：按 id UPDATE（id 取自已应用的 015）。
-- ============================================================

-- 字节跳动 · comp
update insight_items set content=$$据公开讨论，字节给薪在大厂里偏高，对应的工作强度也偏大；不同部门差别明显，建议结合具体岗位了解，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='d537d889-5034-43f2-8ca7-ff786513a349';

-- 京东 · comp
update insight_items set content=$$据公开讨论，京东校招薪资近年有上调，部分岗位对实习和专业背景要求相对宽松，整体薪资中等；岗位之间差别较大，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='a76a915c-c7e8-4972-90ea-074026600989';

-- 腾讯 · comp
update insight_items set content=$$据公开讨论，腾讯薪资稳健、福利较好，整体强度在大厂里相对温和；不同事业群有差异，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='1208b3b4-c60f-4741-90ff-a4b2a0a0ac89';

-- 阿里巴巴 · comp
update insight_items set content=$$据公开讨论，阿里薪资有竞争力、职级体系清晰，强度因业务而异，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='32c6f2d3-282e-4162-b36a-aa18e2869bdb';

-- 拼多多 · comp
update insight_items set content=$$据公开讨论，拼多多给薪在行业里偏高，但工时和强度普遍偏大；建议结合自己的承受度判断，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='544ab7ca-0abc-4401-98ce-b0ab090b4f20';

-- 字节跳动 · path
update insight_items set content=$$据公开报道，字节与快手、小红书等内容公司之间人才流动频繁、互相吸纳；这是行业流动观察，不是进入保证，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='cf110d3c-8b3c-4b43-8198-81bc2f584523';

-- 小红书 · path
update insight_items set content=$$据公开报道，小红书近年从字节、阿里等大厂吸纳了不少人，与内容类公司人才互通较多；属行业流动观察，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='1fc53ad7-c120-40ed-8459-ee997d067387';

-- 字节跳动 · culture
update insight_items set content=$$据公开讨论，字节节奏快、目标导向强、OKR 压力较大。这是群体性反馈、不是对公司的定性，不同部门差别明显，建议结合面试沟通判断，仅供参考。$$, title=$$工作节奏：快节奏 / 高目标$$, payload = payload || '{"tone":"温馨提示"}'::jsonb, last_verified_at=now(), updated_at=now() where id='f739add4-c75d-4628-9a92-6735a35c2980';

-- 拼多多 · culture
update insight_items set content=$$据公开讨论，拼多多的工时和强度常被认为偏高。这是群体性反馈、不是对公司的定性，个人体验差别很大，建议结合面试沟通判断，仅供参考。$$, title=$$工作节奏：强度与时长偏高$$, payload = payload || '{"tone":"温馨提示"}'::jsonb, last_verified_at=now(), updated_at=now() where id='dc82816d-a7d5-464f-a94f-6c0c483d67e0';
