-- ============================================================
-- 015 经验维度来源核验：把 014 的占位来源替换为联网核验到的真实公开链接
-- ============================================================
-- 核验日期 2026-06-03，web 检索真实公开来源（界面新闻/网易/证券时报/比特网/知乎/脉脉/掘金/博客园等）。
-- path 维度按实证诚实弱化为「内容社区公司间人才流动频繁/互相吸纳」（原定向说法无可信实证）。
-- 幂等：按 id UPDATE。
-- ============================================================

-- 字节跳动 · comp
update insight_items set content=$$据界面新闻、知乎等公开报道与讨论聚合（去标识化），字节在互联网公司中给薪相对偏高，对应工作强度也偏大；不同 BU 差异明显，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='d537d889-5034-43f2-8ca7-ff786513a349';
update insight_sources set url='https://www.jiemian.com/article/7151344.html', publisher='界面新闻', source_kind='public_aggregate', excerpt=$$公开报道：字节薪酬偏高、工作强度大$$, collected_at=now() where id='219b1383-ebb5-4b8c-bac2-ab542a00d4cb';
update insight_sources set url='https://zhuanlan.zhihu.com/p/649423048', publisher='知乎', source_kind='community_deidentified', excerpt=$$公开讨论：字节各岗位薪酬对比$$, collected_at=now() where id='9bfe10a4-e825-45f9-afe7-f6ae8c002870';

-- 拼多多 · comp
update insight_items set content=$$据网易、知乎等公开报道与讨论聚合（去标识化），拼多多给薪在行业中偏高，但工作时长与强度常被认为偏大；请结合自身承受度判断，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='544ab7ca-0abc-4401-98ce-b0ab090b4f20';
update insight_sources set url='https://www.163.com/dy/article/ISC6T20C05566ZVT.html', publisher='网易', source_kind='public_aggregate', excerpt=$$公开报道：拼多多薪资与年终奖$$, collected_at=now() where id='a8fbc53c-e8c1-4e8d-b94d-cc25d145a968';
update insight_sources set url='https://zhuanlan.zhihu.com/p/429683236', publisher='知乎', source_kind='community_deidentified', excerpt=$$公开讨论：拼多多工时与强度$$, collected_at=now() where id='f99a5649-a202-4b1a-ba61-6dcaa5c755fe';

-- 京东 · comp
update insight_items set content=$$据知乎、证券时报等公开报道与讨论聚合（去标识化），京东校招薪资近年上调、部分岗位对实习/专业背景要求相对宽松，整体薪资中等；岗位间差异较大，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='a76a915c-c7e8-4972-90ea-074026600989';
update insight_sources set url='https://www.zhihu.com/question/497340244', publisher='知乎', source_kind='community_deidentified', excerpt=$$公开讨论：京东校招薪资与是否值得去$$, collected_at=now() where id='92839bd8-060f-43ba-a80e-bdd6c1b582df';
update insight_sources set url='https://stcn.com/article/detail/1306163.html', publisher='证券时报', source_kind='public_aggregate', excerpt=$$公开报道：京东上调校招薪资$$, collected_at=now() where id='e8ddc4ab-9211-43a4-b59c-190481a9ea63';

-- 腾讯 · comp
update insight_items set content=$$据知乎、博客园等公开讨论聚合（去标识化），腾讯薪资稳健、福利较好，整体强度因业务而异（部分 ToB 线相对缓和、内容/互娱线偏紧）；仅供参考。$$, last_verified_at=now(), updated_at=now() where id='1208b3b4-c60f-4741-90ff-a4b2a0a0ac89';
update insight_sources set url='https://zhuanlan.zhihu.com/p/456354142', publisher='知乎', source_kind='community_deidentified', excerpt=$$公开讨论：腾讯职级薪资体系$$, collected_at=now() where id='633c647f-cc50-48b0-8813-3675961e168d';
update insight_sources set url='https://www.cnblogs.com/wangzhongyang/p/18305908', publisher='博客园', source_kind='community_deidentified', excerpt=$$公开讨论：腾讯调薪与薪资结构$$, collected_at=now() where id='67ea98fc-a06d-47e2-8fc3-63ff44411828';

-- 阿里巴巴 · comp
update insight_items set content=$$据知乎、脉脉等公开讨论聚合（去标识化），阿里薪资具竞争力、P 序列职级体系清晰，强度因业务而异；仅供参考。$$, last_verified_at=now(), updated_at=now() where id='32c6f2d3-282e-4162-b36a-aa18e2869bdb';
update insight_sources set url='https://zhuanlan.zhihu.com/p/143092556', publisher='知乎', source_kind='community_deidentified', excerpt=$$公开讨论：阿里职级与薪酬体系$$, collected_at=now() where id='c3b9594d-c045-4cc5-b1a7-162319b7eb47';
update insight_sources set url='https://maimai.cn/article/detail?fid=1851831518&efid=PEzBBWLJTeydvC_tBIv_SQ', publisher='脉脉', source_kind='community_deidentified', excerpt=$$公开讨论：阿里双序列职级体系$$, collected_at=now() where id='8f5e69fd-b300-44f0-98da-9aacbd4058f6';

-- 拼多多 · culture
update insight_items set content=$$据脉脉、掘金等公开报道与讨论聚合（去标识化），公开讨论中拼多多工作时长与强度常被认为偏高（有「工时极高」的说法）。此为去标识化的群体性反馈、非对公司的事实定性，个体差异很大，请结合面试沟通与自身情况判断，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='dc82816d-a7d5-464f-a94f-6c0c483d67e0';
update insight_sources set url='https://maimai.cn/article/detail?fid=1863981850&efid=lXLze8Q-17PN3FMxXO3HMw', publisher='脉脉', source_kind='community_deidentified', excerpt=$$公开讨论：拼多多加班时长$$, collected_at=now() where id='57fc1d23-326a-4f52-8431-056953036676';
update insight_sources set url='https://juejin.cn/post/7430005681917181962', publisher='掘金', source_kind='community_deidentified', excerpt=$$公开讨论：拼多多工时强度$$, collected_at=now() where id='4df783b4-15e8-468a-a68f-7da878936788';

-- 字节跳动 · culture
update insight_items set content=$$据界面新闻、脉脉等公开报道与讨论聚合（去标识化），公开讨论中常提到字节节奏快、目标导向强、OKR 压力较大。此为群体性反馈、非事实定性，不同 BU/团队差异明显，请结合面试沟通判断，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='f739add4-c75d-4628-9a92-6735a35c2980';
update insight_sources set url='https://www.jiemian.com/article/7151344.html', publisher='界面新闻', source_kind='public_aggregate', excerpt=$$公开报道：字节工作节奏与强度$$, collected_at=now() where id='0c2cf2eb-fb96-4360-b31e-63c6610ed446';
update insight_sources set url='https://maimai.cn/article/detail?fid=1677304876&efid=eZH9YiMjgUx8SINLDkFx5w', publisher='脉脉', source_kind='community_deidentified', excerpt=$$公开讨论：字节真实工作体验$$, collected_at=now() where id='f22700fe-7056-4e50-a0b4-67d579d3e974';

-- 字节跳动 · path
update insight_items set content=$$据比特网、证券时报等公开报道，字节与快手/小红书等内容社区公司之间人才流动频繁、互相吸纳（字节亦大量吸纳大厂背景人才）；此为行业流动观察、非进入保证，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='cf110d3c-8b3c-4b43-8198-81bc2f584523';
update insight_sources set url='https://www.bianews.com/news/details?id=192510', publisher='比特网', source_kind='public_aggregate', excerpt=$$公开报道：内容大厂人才流动（字节/阿里→小红书）$$, collected_at=now() where id='ebee394e-0090-4474-8a81-d36c3fafd909';
update insight_sources set url='https://www.stcn.com/article/detail/3344604.html', publisher='证券时报', source_kind='public_aggregate', excerpt=$$公开报道：大厂抢人，字节/小红书岗位多$$, collected_at=now() where id='d7ac8eac-da25-4b31-a74b-691706c7cfba';

-- 小红书 · path
update insight_items set content=$$据比特网、证券时报等公开报道，小红书近年从字节/阿里等大厂吸纳大量人才、与内容社区公司人才互通较多（亦有「人均在职时间较短」的讨论）；此为行业流动观察，仅供参考。$$, last_verified_at=now(), updated_at=now() where id='1fc53ad7-c120-40ed-8459-ee997d067387';
update insight_sources set url='https://www.bianews.com/news/details?id=192510', publisher='比特网', source_kind='public_aggregate', excerpt=$$公开报道：字节/阿里员工加入小红书$$, collected_at=now() where id='8fd1040d-4568-4cf6-9ba0-f8ce1eb688eb';
update insight_sources set url='https://www.stcn.com/article/detail/3344604.html', publisher='证券时报', source_kind='public_aggregate', excerpt=$$公开报道：大厂抢人，字节/小红书岗位多$$, collected_at=now() where id='2c180745-2aaf-4189-8848-35df1c4fcec4';
