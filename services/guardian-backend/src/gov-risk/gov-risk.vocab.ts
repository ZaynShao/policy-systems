/**
 * 工单系统性原因研判 —— 现象、机理、鉴别线索的固定词表,以及没有模型时的规则兜底。
 *
 * 归并以"现象"为主线:设备计量老化和流水号重复串单,用户感受到的都是"电量/金额偏高",
 * 文本里分不出来;所以机理只作待鉴别的假设,靠鉴别线索和核查动作区分。
 * 模型只能从这里的编码里选,超出词表的输出一律丢弃。
 */

export const SYMPTOMS: Record<string, string> = {
  S_ENERGY_HIGH: '电量/度数偏高',
  S_AMOUNT_HIGH: '金额高于实际或预期',
  S_OTHERS_DATA: '出现他人数据或非本人订单',
  S_PRICE_MISMATCH: '价格标示与实收不一致',
  S_CHARGE_FAIL: '无法启动或中途断电',
  S_UNPLUG: '无法拔枪或无法结束',
  S_VEHICLE_DAMAGE: '车辆受损或安全隐患',
  S_OCCUPANCY_PARKING: '占位费或停车费争议',
  S_INVOICE: '发票问题',
  S_PROMO: '优惠、会员或活动未兑现',
  S_REFUND: '退款、余额或预付款问题',
  S_ACCOUNT: '账号异常或个人信息',
  S_STATION_MGMT: '场站秩序或设施管理',
  S_SERVICE: '客服推诿或处置不力',
  S_OTHER: '其他',
};

export const MECHANISMS: Record<string, string> = {
  M_METER_FAULT: '设备计量异常(硬件老化、校准、电表故障)',
  M_DATA_CROSSTALK: '数据串单(流水号重复、订单与设备会话错配)',
  M_BILLING_CONFIG: '计费规则或价格配置错误',
  M_PRICE_SYNC: '平台展示与场站价格不同步',
  M_DEVICE_FAULT: '设备故障(启停、枪锁、通信)',
  M_PAYMENT_SYSTEM: '支付、退款或余额系统问题',
  M_PROMO_RULE: '营销规则或告知不清',
  M_THIRD_PARTY_OPS: '第三方场站运营管理问题',
  M_SERVICE_HANDLING: '客服处置不当或未闭环',
  M_ACCOUNT_SECURITY: '账号安全或盗用',
  M_USER_MISUNDERSTANDING: '用户误解或操作问题',
  M_UNKNOWN: '无法判断',
};

/** 鉴别线索:能帮助区分机理的事实。正则只用于规则兜底,模型研判时由模型判断。 */
export const CLUES: Record<string, { label: string; rx: RegExp }> = {
  C_EXCEEDS_BATTERY: {
    label: '充电量超过车辆电池容量',
    rx: /超(过|出)?(了)?(车辆|电池)?(的)?(电池)?容量|电池容量[^。；;]{0,8}(只有|才|仅)/i,
  },
  C_MISMATCH_VEHICLE: {
    label: '与车辆仪表或车机显示不符',
    rx: /(车辆|仪表|车机|车上|车子|汽车|电池)[^。；;]{0,10}(显示|只充|才充|实际)/i,
  },
  C_NOT_MY_SESSION: {
    label: '用户称记录不是本人这次的',
    rx: /不是(我|本人|自己)(的|这次)|(别人|他人|其他人|陌生人)[^。；;]{0,12}(订单|记录|数据)/i,
  },
  C_TIME_MISMATCH: {
    label: '订单时间或时长与实际不符',
    rx: /(时间|时长|时段)[^。；;]{0,8}(不对|不符|对不上|不一致)|(没有|并未|未)[^。；;]{0,6}(在|去)[^。；;]{0,6}充电/i,
  },
  C_SAME_PILE_REPEAT: {
    label: '同一桩或场站多次出现',
    rx: /(同一|这个|该)(个)?(桩|充电桩|枪|场站|站)[^。；;]{0,12}(多次|又|再次|反复|经常|每次)|(多次|又|再次|反复)[^。；;]{0,8}(这个|该|同一)(桩|场站|站)/i,
  },
  C_AMOUNT_ONLY: {
    label: '度数正常但金额偏高',
    rx: /(度数|电量)[^。；;]{0,8}(正常|没问题|一样)[^。；;]{0,15}(金额|费用|扣)/i,
  },
};

/** 线索指向的机理,用于卡片上的"鉴别提示" */
export const CLUE_HINTS: Record<string, string[]> = {
  C_EXCEEDS_BATTERY: ['M_DATA_CROSSTALK', 'M_METER_FAULT'],
  C_MISMATCH_VEHICLE: ['M_METER_FAULT', 'M_DATA_CROSSTALK'],
  C_NOT_MY_SESSION: ['M_DATA_CROSSTALK'],
  C_TIME_MISMATCH: ['M_DATA_CROSSTALK'],
  C_SAME_PILE_REPEAT: ['M_METER_FAULT', 'M_DEVICE_FAULT'],
  C_AMOUNT_ONLY: ['M_BILLING_CONFIG', 'M_PRICE_SYNC'],
};

/** 每种机理的核查动作(规则版;模型复核会给更具体的) */
export const VERIFY_STEPS: Record<string, string> = {
  M_METER_FAULT: '核对涉事桩的计量检定记录、厂家型号和投运年限,抽查同批设备',
  M_DATA_CROSSTALK: '核对涉事订单的设备流水号是否重复,检查订单与设备会话的关联逻辑',
  M_BILLING_CONFIG: '核对涉事时段的价格与服务费配置',
  M_PRICE_SYNC: '比对平台展示价与场站现场标价的同步记录',
  M_DEVICE_FAULT: '调取设备故障日志,确认同型号设备是否批量出现',
  M_PAYMENT_SYSTEM: '核对支付、退款流水与余额变动记录',
  M_PROMO_RULE: '核对活动规则文案与实际核销逻辑是否一致',
  M_THIRD_PARTY_OPS: '约谈对应运营商,核对场站管理与现场处置记录',
  M_SERVICE_HANDLING: '抽查同类工单的客服处置记录与补偿口径',
  M_ACCOUNT_SECURITY: '核对登录与支付风控记录',
  M_USER_MISUNDERSTANDING: '统一解释口径,在下单或结算页补充说明',
  M_UNKNOWN: '补充调取订单与设备数据后再判断',
};

/** 监管敏感度:计量、他人数据(个人信息)、安全最敏感;价格次之 */
export const SENSITIVITY: Record<string, number> = {
  S_ENERGY_HIGH: 1.0, S_OTHERS_DATA: 1.0, S_VEHICLE_DAMAGE: 1.0,
  S_AMOUNT_HIGH: 0.8, S_PRICE_MISMATCH: 0.8, S_ACCOUNT: 0.8,
  S_INVOICE: 0.6, S_REFUND: 0.6, S_PROMO: 0.6, S_OCCUPANCY_PARKING: 0.5,
  S_CHARGE_FAIL: 0.5, S_UNPLUG: 0.5, S_STATION_MGMT: 0.4, S_SERVICE: 0.4, S_OTHER: 0.2,
};

export const DEMANDS = ['退款', '赔偿', '欺诈主张', '要求查处', '诉讼', '曝光'] as const;

export const STATUS_LABELS: Record<string, string> = {
  new: '新发现', investigating: '核查中', confirmed: '根因确认', fixing: '整改中',
  fixed: '已修复', observing: '观察期', dismissed: '误报', closed: '关闭',
};

// ---------- 规则兜底 ----------

/** 文本里的具体现象,优先级最高 */
const RULES: Array<[string, RegExp]> = [
  ['S_OTHERS_DATA',
    /(别人|他人|其他人|陌生人|前(一|面)(个|位)?(用户|车主|人)|上一(个|位)(用户|车主)?|之前的?(用户|车主)|不是(本人|我|自己)的?)[^。；;]{0,15}(订单|记录|数据|充电|账单|金额|信息)|串单|串号|流水号|订单(串|错乱|混乱|不是我)/i],
  ['S_ENERGY_HIGH',
    /(度数|电量|充电量|电度|度电|kwh|千瓦时|充入|充了)[^。；;，,]{0,12}(高|多|虚|不符|不一致|不对|异常|超出|超过|偏大|对不上|远超|离谱)|多计|虚高|计量(异常|不准|有误|问题)|电表(异常|不准|有问题)|超(过)?(电池)?容量|跳度|度数异常/i],
  ['S_VEHICLE_DAMAGE', /车损|损坏|刮(伤|蹭|花)|撞|划(伤|痕)|起火|着火|冒烟|触电|漏电|烧(坏|毁)/i],
  ['S_AMOUNT_HIGH', /(金额|扣费|扣款|费用|收费)[^。；;]{0,10}(高|多|不符|不对|异常|对不上|离谱)|多扣|多收|重复扣|重复收/i],
  ['S_PRICE_MISMATCH', /价格[^。；;]{0,6}(不一致|不符|有差异)|标价|明码标价|线上线下|与[^。；;]{0,6}(显示|标注|公示)[^。；;]{0,4}不|单价未享受/i],
  ['S_UNPLUG', /拔不(出|下)|无法拔|拔枪/i],
  ['S_CHARGE_FAIL', /无法启动|启动不了|充不上|没充上|中途(停|断)|自动(停|断)|无法充电|不能充电/i],
];

/** 泛化现象:优先级低于"具体现象"和平台问题类型,避免"要求退款"这类诉求盖过真正的现象 */
const GENERIC_RULES: Array<[string, RegExp]> = [
  ['S_OCCUPANCY_PARKING', /占位|停车费|超时费|减免/i],
  ['S_INVOICE', /发票|开票|税号|抬头/i],
  ['S_REFUND', /余额|预付|退款[^。；;]{0,6}(未|没|失败|一直|迟迟|不)|未到账|没到账|退不了|无法退|不给退/i],
  ['S_PROMO', /优惠|券|会员|活动|返现|权益/i],
  ['S_ACCOUNT', /账号|账户|被盗|盗刷|个人信息|隐私|骚扰|注销/i],
  ['S_STATION_MGMT', /油车占位|燃油车|车位|场站(管理|秩序|环境)|管理员/i],
  ['S_SERVICE', /客服|推诿|不处理|没人处理|无人处理|拖延/i],
];

/** 平台问题类型(最后一级)到现象的兜底映射,文本里没命中具体现象时用 */
const LEAF_TO_SYMPTOM: Record<string, string> = {
  电量异常: 'S_ENERGY_HIGH', 超电池容量充电: 'S_ENERGY_HIGH', 电费异常: 'S_AMOUNT_HIGH',
  没充上电: 'S_CHARGE_FAIL', 无法启动充电: 'S_CHARGE_FAIL', 无法停止充电: 'S_UNPLUG',
  充电速度慢: 'S_CHARGE_FAIL', 无法拔枪: 'S_UNPLUG', 设备异常: 'S_CHARGE_FAIL',
  电桩电枪故障: 'S_CHARGE_FAIL', 车辆损坏: 'S_VEHICLE_DAMAGE', 非充坏车损: 'S_VEHICLE_DAMAGE',
  充电设备充坏车辆: 'S_VEHICLE_DAMAGE', 场站设施不当导致车辆剐蹭: 'S_VEHICLE_DAMAGE',
  线上线下价格不符: 'S_PRICE_MISMATCH', 平台单价未享受: 'S_PRICE_MISMATCH', 价格有差异: 'S_PRICE_MISMATCH',
  费用价格: 'S_AMOUNT_HIGH', 上涨: 'S_PRICE_MISMATCH',
  占位费: 'S_OCCUPANCY_PARKING', 停车费: 'S_OCCUPANCY_PARKING', 不认可被收取占位费: 'S_OCCUPANCY_PARKING',
  不符合减免条件: 'S_OCCUPANCY_PARKING', 线上线下减免规则不一致: 'S_OCCUPANCY_PARKING', 电车占位: 'S_OCCUPANCY_PARKING',
  发票: 'S_INVOICE', 修改发票信息: 'S_INVOICE', 咨询如何线上开票: 'S_INVOICE', 收到无效发票: 'S_INVOICE',
  税务稽查进线: 'S_INVOICE',
  优惠券: 'S_PROMO', 会员问题: 'S_PROMO', 营销活动: 'S_PROMO', 活动券及优惠问题: 'S_PROMO',
  安心充: 'S_PROMO', 周末私家车活动: 'S_PROMO', 反馈加油金问题: 'S_PROMO',
  充电余额: 'S_REFUND', 预付款: 'S_REFUND', 充电余额退款异常: 'S_REFUND', 安心充退款: 'S_REFUND',
  补偿未到账: 'S_REFUND', 扣款: 'S_AMOUNT_HIGH',
  账号异常: 'S_ACCOUNT', 账号被盗产生非本人订单: 'S_ACCOUNT', 账户被盗: 'S_ACCOUNT',
  场站管理: 'S_STATION_MGMT',
};

const DEMAND_RULES: Array<[string, RegExp]> = [
  ['退款', /退款|退还|退回|退费/],
  ['赔偿', /赔偿|补偿|赔付/],
  ['欺诈主张', /欺诈|退一赔三|三倍/],
  ['要求查处', /查处|处罚|罚款|严惩|依法处理|立案|调查|举报/],
  ['诉讼', /起诉|律师|法院|仲裁/],
  ['曝光', /曝光|媒体|记者|微博|抖音|小红书|热搜|上新闻/],
];

/** 按优先级返回命中的现象:文本里的具体现象 > 平台问题类型 > 泛化现象。 */
export function ruleSymptoms(text: string, problemLeaf = ''): string[] {
  const t = text || '';
  const hits = RULES.filter(([, rx]) => rx.test(t)).map(([code]) => code);
  const leaf = LEAF_TO_SYMPTOM[problemLeaf || ''];
  if (leaf && !hits.includes(leaf)) hits.push(leaf);
  for (const [code, rx] of GENERIC_RULES) {
    if (rx.test(t) && !hits.includes(code)) hits.push(code);
  }
  return hits.length ? hits : ['S_OTHER'];
}

export function ruleClues(text: string): string[] {
  return Object.entries(CLUES).filter(([, c]) => c.rx.test(text || '')).map(([code]) => code);
}

export function ruleDemands(text: string): string[] {
  return DEMAND_RULES.filter(([, rx]) => rx.test(text || '')).map(([name]) => name);
}
