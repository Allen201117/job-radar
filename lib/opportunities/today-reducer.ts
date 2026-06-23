// 今日机会队列的纯状态机（§P1-1）。把「乐观移除 / API 失败回滚 / 撤销乐观恢复 / 撤销提交 / 撤销失败重移除」
// 抽成纯 reducer，不依赖 setState updater 的同步副作用（原 captureAndRemove 从 updater 返回局部变量不可靠）。
// 分区/顺序用原始 index 还原，不漂移；pending/undoing 按 jobId 隔离，多岗并发互不影响。
import type { Opportunity, FeedSections } from "./types";

export type PrimaryAction = "saved" | "ignored" | "applied";
export type SectionKey = "new" | "priority" | "explore" | "aging";
const KEYS: SectionKey[] = ["new", "priority", "explore", "aging"];

interface Pending {
  opp: Opportunity;
  key: SectionKey;
  index: number;
  action: PrimaryAction;
}
export interface TodayToast {
  jobId: string;
  action: PrimaryAction | null;
  undoFailed?: boolean;
}
export interface TodayState {
  sections: FeedSections;
  pending: Record<string, Pending>; // 已乐观移除、等待 commit(toast 过期) / rollback / undo
  undoing: Record<string, { opp: Opportunity; key: SectionKey; index: number }>; // 已乐观恢复、等待 undo commit / rollback
  toast: TodayToast | null;
}

export type TodayEvent =
  | { type: "removeOptimistic"; jobId: string; action: PrimaryAction }
  | { type: "removeRollback"; jobId: string } // 正向 API 失败 → 还原
  | { type: "finalizeRemove"; jobId: string } // toast 过期 → 移除落定
  | { type: "undoOptimistic"; jobId: string } // 点撤销 → 乐观恢复
  | { type: "undoCommit"; jobId: string } // 撤销 API 成功
  | { type: "undoRollback"; jobId: string } // 撤销 API 失败 → 重新移出
  | { type: "dismissToast" }; // 关闭 toast（撤销失败提示等自动消失）

function cloneSections(s: FeedSections): FeedSections {
  return { new: [...s.new], priority: [...s.priority], explore: [...s.explore], aging: [...s.aging] };
}

export function initTodayState(sections: FeedSections): TodayState {
  return { sections: cloneSections(sections), pending: {}, undoing: {}, toast: null };
}

function locate(sections: FeedSections, jobId: string): { key: SectionKey; index: number } | null {
  for (const key of KEYS) {
    const idx = sections[key].findIndex((o) => o.job.id === jobId);
    if (idx >= 0) return { key, index: idx };
  }
  return null;
}

function withRemoved(sections: FeedSections, key: SectionKey, jobId: string): FeedSections {
  return { ...sections, [key]: sections[key].filter((o) => o.job.id !== jobId) };
}

// 按原始 index 插回，保序；已存在则幂等不重复插
function withInserted(sections: FeedSections, key: SectionKey, opp: Opportunity, index: number): FeedSections {
  if (sections[key].some((o) => o.job.id === opp.job.id)) return sections;
  const arr = [...sections[key]];
  arr.splice(Math.min(index, arr.length), 0, opp);
  return { ...sections, [key]: arr };
}

function omit<T extends Record<string, unknown>>(obj: T, key: string): T {
  const { [key]: _drop, ...rest } = obj;
  return rest as T;
}

export function todayReducer(state: TodayState, ev: TodayEvent): TodayState {
  switch (ev.type) {
    case "removeOptimistic": {
      if (state.pending[ev.jobId]) return state; // 处理中，幂等
      const loc = locate(state.sections, ev.jobId);
      if (!loc) return state;
      const opp = state.sections[loc.key][loc.index];
      return {
        ...state,
        sections: withRemoved(state.sections, loc.key, ev.jobId),
        pending: { ...state.pending, [ev.jobId]: { opp, key: loc.key, index: loc.index, action: ev.action } },
        toast: { jobId: ev.jobId, action: ev.action },
      };
    }
    case "removeRollback": {
      const p = state.pending[ev.jobId];
      if (!p) return state;
      return {
        ...state,
        sections: withInserted(state.sections, p.key, p.opp, p.index),
        pending: omit(state.pending, ev.jobId),
        toast: state.toast?.jobId === ev.jobId ? null : state.toast,
      };
    }
    case "finalizeRemove": {
      return {
        ...state,
        pending: omit(state.pending, ev.jobId),
        toast: state.toast?.jobId === ev.jobId ? null : state.toast,
      };
    }
    case "undoOptimistic": {
      const p = state.pending[ev.jobId];
      if (!p) return state;
      return {
        ...state,
        sections: withInserted(state.sections, p.key, p.opp, p.index),
        pending: omit(state.pending, ev.jobId),
        undoing: { ...state.undoing, [ev.jobId]: { opp: p.opp, key: p.key, index: p.index } },
        toast: state.toast?.jobId === ev.jobId ? null : state.toast,
      };
    }
    case "undoCommit": {
      return { ...state, undoing: omit(state.undoing, ev.jobId) };
    }
    case "undoRollback": {
      const u = state.undoing[ev.jobId];
      if (!u) return state;
      return {
        ...state,
        sections: withRemoved(state.sections, u.key, ev.jobId),
        undoing: omit(state.undoing, ev.jobId),
        toast: { jobId: ev.jobId, action: null, undoFailed: true },
      };
    }
    case "dismissToast": {
      return state.toast ? { ...state, toast: null } : state;
    }
    default:
      return state;
  }
}
