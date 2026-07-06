// 北极星指标清单：「必投清单健康覆盖率」的口径来源（admin 运营看板 · 北极星卡）。
// 选取目标用户（想去头部公司的求职者）最常投的 30 家互联网/科技/消费头部公司；
// pattern 是 jobs.company 的 ILIKE 匹配模式——库里公司名有全称/简称/中英文变体，用子串兜住。
// ⚠️ 改这份清单 = 改北极星口径，指标会跳变；调整请在 commit message 里写明原因。
export interface MustApplyCompany {
  name: string; // 展示名
  pattern: string; // jobs.company ILIKE 模式（含 %）
}

export const MUST_APPLY_LIST: MustApplyCompany[] = [
  { name: "字节跳动", pattern: "%字节%" },
  { name: "腾讯", pattern: "%腾讯%" },
  { name: "阿里巴巴", pattern: "%阿里%" },
  { name: "美团", pattern: "%美团%" },
  { name: "拼多多", pattern: "%拼多多%" },
  { name: "小红书", pattern: "%小红书%" },
  { name: "快手", pattern: "%快手%" },
  { name: "哔哩哔哩", pattern: "%哔哩%" },
  { name: "京东", pattern: "%京东%" },
  { name: "滴滴", pattern: "%滴滴%" },
  { name: "网易", pattern: "%网易%" },
  { name: "百度", pattern: "%百度%" },
  { name: "华为", pattern: "%华为%" },
  { name: "小米", pattern: "%小米%" },
  { name: "OPPO", pattern: "%OPPO%" },
  { name: "vivo", pattern: "%vivo%" },
  { name: "荣耀", pattern: "%荣耀%" },
  { name: "大疆", pattern: "%大疆%" },
  { name: "米哈游", pattern: "%米哈游%" },
  { name: "蚂蚁集团", pattern: "%蚂蚁%" },
  { name: "携程", pattern: "%携程%" },
  { name: "贝壳", pattern: "%贝壳%" },
  { name: "得物", pattern: "%得物%" },
  { name: "蔚来", pattern: "%蔚来%" },
  { name: "理想汽车", pattern: "%理想%" },
  { name: "小鹏汽车", pattern: "%小鹏%" },
  { name: "宁德时代", pattern: "%宁德%" },
  { name: "微众银行", pattern: "%微众%" },
  { name: "腾讯音乐", pattern: "%腾讯音乐%" },
  { name: "SHEIN", pattern: "%SHEIN%" },
];
