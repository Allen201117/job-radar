-- 207 — 管理员看板「用户行为」模块的数据层。
--
-- 背景：73 个注册用户，但看板此前只能答「有几个人、收藏投递了几次」，
-- 答不出「人卡在哪一步 / 还回不回来 / 在找什么 / 我们推的准不准」这四个真问题。
-- 这里补两样东西：
--   1) events 按人查的复合索引（留存 / 漏斗 / 单用户轨迹全部按 user_id + 时间取数）
--   2) 一个统计函数 admin_user_analytics()，一次返回四块 + 单用户名单
--
-- 口径三条硬规矩（改这个函数务必保住）：
--   · **默认排除管理员与测试号**。线上前两名用户各有 ~450 条事件，不排掉会把所有
--     比率拉得虚高（比如把创始人自己的日常使用算成「用户很活跃」）。
--   · **样本不足不出结论**。回访率的分母只算「已经过了观察期」的用户：
--     注册不满 7 天的人不进 7 日回访分母，否则新用户越多回访率看着越低，是假信号。
--   · **漏斗按「到达过」算，不强行单调**。有人没设偏好也点了官网，这是真实行为，
--     强行做成逐级递减的漏斗会把这种信号抹掉。

-- ── 索引：留存/漏斗/轨迹都是「按人 + 按时间」取数 ───────────────────────────
-- 现有 idx_events_created_at 只支持「近 N 天全量扫」，按人取轨迹要全表过滤。
create index if not exists idx_events_user_created
  on public.events (user_id, created_at desc);

-- ── 统计函数 ────────────────────────────────────────────────────────────────
-- p_days        : 每日活跃序列与搜索/推荐统计的回看天数
-- p_include_staff: true = 把管理员与测试号也算进来（默认 false）
create or replace function public.admin_user_analytics(
  p_days int default 30,
  p_include_staff boolean default false
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $function$
with params as (
  select
    greatest(1, least(coalesce(p_days, 30), 180)) as days,
    coalesce(p_include_staff, false) as include_staff,
    (now() at time zone 'Asia/Shanghai')::date as today
),
-- 被排除的账号：管理员 + 测试域邮箱。判定放这里而不是调用方，
-- 保证任何调用点拿到的都是同一套口径。
staff as (
  select p.id
  from profiles p
  left join auth.users u on u.id = p.id
  where p.role = 'admin'
     or coalesce(u.email, '') like '%@jobradar.local'
),
cohort as (
  select
    p.id,
    (p.created_at at time zone 'Asia/Shanghai')::date as signup_date
  from profiles p, params
  where params.include_staff or p.id not in (select id from staff)
),
-- 只保留计入统计的用户的事件，后面所有块共用这一份。
ev as (
  select
    e.user_id,
    e.event,
    e.payload,
    e.created_at,
    (e.created_at at time zone 'Asia/Shanghai')::date as day
  from events e
  join cohort c on c.id = e.user_id
),
ev_window as (
  select ev.* from ev, params
  where ev.day > params.today - params.days
),
-- 每人的活跃天集合：留存、活跃天数分布、单用户名单都从这里派生。
user_days as (
  select user_id, count(distinct day) as active_days, max(day) as last_day, count(*) as events
  from ev
  group by user_id
),
-- 回访 = 在**注册日之外的另一天**还来过。按人算出「第一次回访距注册几天」。
return_gap as (
  select
    c.id,
    c.signup_date,
    min(ev.day - c.signup_date) filter (where ev.day > c.signup_date) as first_return_gap
  from cohort c
  left join ev on ev.user_id = c.id
  group by c.id, c.signup_date
),
retention as (
  select
    -- 分母只算已经过了观察期的用户，避免「新用户多 → 回访率假跌」
    count(*) filter (where params.today - signup_date >= 7)                                as d7_cohort,
    count(*) filter (where params.today - signup_date >= 7  and first_return_gap <= 7)     as d7_returned,
    count(*) filter (where params.today - signup_date >= 30)                               as d30_cohort,
    count(*) filter (where params.today - signup_date >= 30 and first_return_gap <= 30)    as d30_returned,
    count(*) filter (where params.today - signup_date >= 1)                                as ever_cohort,
    count(*) filter (where params.today - signup_date >= 1  and first_return_gap is not null) as ever_returned
  from return_gap, params
),
-- ── 漏斗六步：每步取「到达过的去重人数」 ──────────────────────────────────
-- 偏好/简历两步同时认「事件」和「数据表里有行」：preferences_saved 是新埋点，
-- 老用户不会有这条事件，只认事件会把存量用户全判成没设过偏好。
step_resume as (
  select distinct user_id from ev
  where event in ('resume_parse_started', 'resume_parse_succeeded', 'resume_profile_saved')
  union
  select id from cohort where id in (select user_id from candidate_profiles)
),
step_prefs as (
  select distinct user_id from ev where event = 'preferences_saved'
  union
  select id from cohort where id in (select user_id from user_preferences)
),
-- 「看到过岗位」必须把 /jobs 页的行为也算进来：那条路径不触发 radar_open，
-- 只认 radar_* 会漏掉 10 个从岗位库直接点开岗位的人，把漏斗这一级凭空做低。
-- 凡是只有「看见过岗位卡」才可能发生的动作，一律算作到达本级。
step_browse as (
  select distinct user_id from ev
  where event in (
      'radar_open', 'radar_feed_opened', 'search', 'search_result',
      'job_click', 'opportunity_click', 'job_action', 'job_copy_link',
      'opportunity_feedback', 'insight_drawer_open', 'saved_compare_opened'
    )
     or (event = 'page_view' and payload->>'path' in ('/today', '/jobs', '/campus'))
),
-- 打开过产品 = 有任何一条事件。page_view 上线后这一级才真正准确
-- （在此之前，只登录看一眼、什么都没点的人在数据里不存在）。
step_opened as (
  select distinct user_id from ev
),
-- 旁支指标（不进主漏斗）：被「先去设置求职目标」拦下的人。
-- 它不是漏斗的一级——同一个人可能被拦下之后就去设置了——但它是「新用户第一屏遇到什么」
-- 的最强信号，必须单独点名。
step_onboarding_blocked as (
  select distinct user_id from ev where event = 'radar_onboarding_required'
),
step_official as (
  select distinct user_id from ev
  where event in ('opportunity_official_opened', 'job_click')
),
step_saved as (
  select distinct user_id from job_actions
  where action = 'saved' and user_id in (select id from cohort)
),
step_applied as (
  select distinct user_id from job_actions
  where action = 'applied' and user_id in (select id from cohort)
),
-- ── 搜索：用户在找什么 + 0 结果率 ─────────────────────────────────────────
searches as (
  select
    coalesce(nullif(payload->>'keyword', ''), '') as keyword,
    coalesce((payload->>'zero_result')::boolean, false) as zero_result,
    payload->'cities' as cities,
    payload->'functions' as functions
  from ev_window
  where event = 'search_result'
),
kw as (
  select keyword as value,
         count(*)::int as count,
         count(*) filter (where zero_result)::int as zero
  from searches where keyword <> ''
  group by keyword order by count(*) desc limit 12
),
city as (
  select value, count(*)::int as count
  from searches, lateral jsonb_array_elements_text(coalesce(cities, '[]'::jsonb)) as value
  group by value order by count(*) desc limit 12
),
func as (
  select value, count(*)::int as count
  from searches, lateral jsonb_array_elements_text(coalesce(functions, '[]'::jsonb)) as value
  group by value order by count(*) desc limit 12
),
-- ── 页面浏览分布 ─────────────────────────────────────────────────────────
pages as (
  select coalesce(payload->>'path', 'other') as path,
         count(*)::int as views,
         count(distinct user_id)::int as users
  from ev_window where event = 'page_view'
  group by 1 order by count(*) desc limit 15
),
-- ── 每日活跃 ─────────────────────────────────────────────────────────────
daily as (
  select d::date as date,
         coalesce(count(distinct ev_window.user_id), 0)::int as users,
         coalesce(count(ev_window.user_id), 0)::int as events
  from params,
       generate_series(params.today - params.days + 1, params.today, interval '1 day') as d
  left join ev_window on ev_window.day = d::date
  group by d::date order by d::date
),
-- ── 单用户名单（去标识：只给 user_id 前 4 位，不出邮箱） ────────────────
user_rows as (
  select
    left(c.id::text, 4) as uid,
    c.signup_date,
    coalesce(ud.active_days, 0)::int as active_days,
    ud.last_day,
    coalesce(ud.events, 0)::int as events,
    coalesce(up.target_industries, '{}') as industries,
    coalesce(up.experience_stage, '') as stage,
    (case when c.id in (select user_id from step_applied) then 6
          when c.id in (select user_id from step_official) then 5
          when c.id in (select user_id from step_browse)   then 4
          when c.id in (select user_id from step_prefs)    then 3
          when c.id in (select user_id from step_resume)   then 2
          else 1 end) as step
  from cohort c
  left join user_days ud on ud.user_id = c.id
  left join user_preferences up on up.user_id = c.id
  order by coalesce(ud.last_day, c.signup_date) desc, ud.events desc nulls last
  limit 200
)
select jsonb_build_object(
  'generated_at', now(),
  'window_days', (select days from params),
  'include_staff', (select include_staff from params),
  'excluded_users', (select count(*)::int from staff),
  'totals', jsonb_build_object(
    'registered', (select count(*)::int from cohort),
    'activated',  (select count(*)::int from user_days),
    'today_active', (select count(distinct user_id)::int from ev, params where ev.day = params.today),
    'week_active',  (select count(distinct user_id)::int from ev, params where ev.day > params.today - 7)
  ),
  -- 主漏斗五级，按产品里真实发生的先后排。传简历是可选动作（实测设目标的人比传简历的多），
  -- 放进主漏斗会做出一个「后面比前面多」的假漏斗 → 移到 side_metrics。
  'funnel', jsonb_build_array(
    jsonb_build_object('key','signup',   'label','注册',        'users',(select count(*)::int from cohort)),
    jsonb_build_object('key','opened',   'label','打开过产品',  'users',(select count(*)::int from step_opened)),
    jsonb_build_object('key','prefs',    'label','设了求职目标','users',(select count(*)::int from step_prefs)),
    jsonb_build_object('key','browse',   'label','看到岗位',    'users',(select count(*)::int from step_browse)),
    jsonb_build_object('key','official', 'label','点开官网',    'users',(select count(*)::int from step_official)),
    jsonb_build_object('key','applied',  'label','标记投递',    'users',(select count(*)::int from step_applied))
  ),
  'side_metrics', jsonb_build_object(
    'resume_uploaded',     (select count(*)::int from step_resume),
    'onboarding_blocked',  (select count(*)::int from step_onboarding_blocked),
    'saved',               (select count(*)::int from step_saved)
  ),
  'retention', (select jsonb_build_object(
      'd7_cohort', d7_cohort, 'd7_returned', d7_returned,
      'd30_cohort', d30_cohort, 'd30_returned', d30_returned,
      'ever_cohort', ever_cohort, 'ever_returned', ever_returned
    ) from retention),
  'active_days_hist', jsonb_build_object(
    'one',        (select count(*)::int from user_days where active_days = 1),
    'two_to_six', (select count(*)::int from user_days where active_days between 2 and 6),
    'seven_plus', (select count(*)::int from user_days where active_days >= 7)
  ),
  'daily_active', (select coalesce(jsonb_agg(jsonb_build_object(
      'date', to_char(date,'YYYY-MM-DD'), 'users', users, 'events', events) order by date), '[]'::jsonb) from daily),
  'search', jsonb_build_object(
    'searches', (select count(*)::int from searches),
    'zero_searches', (select count(*) filter (where zero_result)::int from searches),
    'top_keywords', (select coalesce(jsonb_agg(jsonb_build_object('value',value,'count',count,'zero',zero) order by count desc), '[]'::jsonb) from kw),
    'top_cities',   (select coalesce(jsonb_agg(jsonb_build_object('value',value,'count',count) order by count desc), '[]'::jsonb) from city),
    'top_functions',(select coalesce(jsonb_agg(jsonb_build_object('value',value,'count',count) order by count desc), '[]'::jsonb) from func)
  ),
  'recommendation', jsonb_build_object(
    'feed_opens',    (select count(*)::int from ev_window where event in ('radar_open','radar_feed_opened')),
    'card_clicks',   (select count(*)::int from ev_window where event in ('opportunity_click','job_click')),
    'official_opens',(select count(*)::int from ev_window where event in ('opportunity_official_opened','job_click')),
    'saves',         (select count(*)::int from job_actions ja, params
                       where ja.action='saved' and ja.user_id in (select id from cohort)
                         and (ja.created_at at time zone 'Asia/Shanghai')::date > params.today - params.days),
    'applies',       (select count(*)::int from job_actions ja, params
                       where ja.action='applied' and ja.user_id in (select id from cohort)
                         and (ja.created_at at time zone 'Asia/Shanghai')::date > params.today - params.days)
  ),
  'pages', (select coalesce(jsonb_agg(jsonb_build_object('path',path,'views',views,'users',users) order by views desc), '[]'::jsonb) from pages),
  'users', (select coalesce(jsonb_agg(jsonb_build_object(
      'uid', uid,
      'signup_date', to_char(signup_date,'YYYY-MM-DD'),
      'active_days', active_days,
      'last_active', to_char(last_day,'YYYY-MM-DD'),
      'events', events,
      'industries', to_jsonb(industries),
      'stage', stage,
      'step', step)), '[]'::jsonb) from user_rows)
);
$function$;

revoke all on function public.admin_user_analytics(int, boolean) from public, anon, authenticated;
grant execute on function public.admin_user_analytics(int, boolean) to service_role;
