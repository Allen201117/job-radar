// 北极星指标清单：「必投清单健康覆盖率」的口径来源（admin 运营看板 · 北极星卡）。
// 选取目标用户（想去头部公司的求职者）最常投的 30 家互联网/科技/消费头部公司；
// pattern 是 jobs.company 的 ILIKE 匹配模式——库里公司名有全称/简称/中英文变体，用子串兜住。
// ⚠️ 改这份清单 = 改北极星口径，指标会跳变；调整请在 commit message 里写明原因。
import mustApplyList from "./must-apply-list.json";

export interface MustApplyCompany {
  name: string; // 展示名
  pattern: string; // jobs.company ILIKE 模式（含 %）
}

export const MUST_APPLY_LIST: MustApplyCompany[] = mustApplyList;
