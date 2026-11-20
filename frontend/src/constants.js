export const ROLES={admin:'印刷主管',pressman:'机长',viewer:'只读观察员'};
// 旧单标签三类
export const DEFECTS=['合格','乳化','偏色'];
// 多标签判读：两类缺陷可同时出现；旧参考漏标的另一类按“未知”处理
export const DEFECT_TYPES=['乳化','偏色'];
export const UNKNOWN='未知';
export const CONFIDENCE_THRESHOLD=0.9;
export const STATES={hold:'量产停机',setup:'待开机',adjusting:'调机复验中',production:'已签印量产',issued:'待执行',executed:'已执行待复验',signed:'复验闭合',unmeasured:'未判读',classifying:'判读中',classified:'已判读',failed:'判读失败'};
