/**
 * 省级行政区划真值表(GB/T 2260)+ 解析。政策大盘按 L1 adcode 对齐 region(spec C2)。
 * 取数:adcode 前 2 位 = 省级;'00' 前缀 / level=国家 = 全国(不归任何单省)。
 * region.name 会被发文机构污染(如"江苏省市场监督管理局"),故以 adcode 为准、name 仅兜底。
 */

export interface ProvinceMeta {
  adcode2: string; // 前两位
  adcode: string; // 省级 6 位(XX0000)
  name: string; // 全名(与 geojson 对齐)
  short: string; // 简称
}

// adcode 前两位 → 省级
export const PROVINCE_BY_PREFIX: Record<string, { name: string; short: string }> = {
  '11': { name: '北京市', short: '北京' },
  '12': { name: '天津市', short: '天津' },
  '13': { name: '河北省', short: '河北' },
  '14': { name: '山西省', short: '山西' },
  '15': { name: '内蒙古自治区', short: '内蒙古' },
  '21': { name: '辽宁省', short: '辽宁' },
  '22': { name: '吉林省', short: '吉林' },
  '23': { name: '黑龙江省', short: '黑龙江' },
  '31': { name: '上海市', short: '上海' },
  '32': { name: '江苏省', short: '江苏' },
  '33': { name: '浙江省', short: '浙江' },
  '34': { name: '安徽省', short: '安徽' },
  '35': { name: '福建省', short: '福建' },
  '36': { name: '江西省', short: '江西' },
  '37': { name: '山东省', short: '山东' },
  '41': { name: '河南省', short: '河南' },
  '42': { name: '湖北省', short: '湖北' },
  '43': { name: '湖南省', short: '湖南' },
  '44': { name: '广东省', short: '广东' },
  '45': { name: '广西壮族自治区', short: '广西' },
  '46': { name: '海南省', short: '海南' },
  '50': { name: '重庆市', short: '重庆' },
  '51': { name: '四川省', short: '四川' },
  '52': { name: '贵州省', short: '贵州' },
  '53': { name: '云南省', short: '云南' },
  '54': { name: '西藏自治区', short: '西藏' },
  '61': { name: '陕西省', short: '陕西' },
  '62': { name: '甘肃省', short: '甘肃' },
  '63': { name: '青海省', short: '青海' },
  '64': { name: '宁夏回族自治区', short: '宁夏' },
  '65': { name: '新疆维吾尔自治区', short: '新疆' },
  '71': { name: '台湾省', short: '台湾' },
  '81': { name: '香港特别行政区', short: '香港' },
  '82': { name: '澳门特别行政区', short: '澳门' },
};

// 全名 → 前两位(用于无 adcode 时按 name 最长前缀兜底)
const PREFIX_BY_FULLNAME: Array<{ name: string; prefix: string }> = Object.entries(PROVINCE_BY_PREFIX)
  .map(([prefix, m]) => ({ name: m.name, prefix }))
  .sort((a, b) => b.name.length - a.name.length); // 先长后短

export const NATIONAL_KEY = '全国';

/** adcode 前缀 '00'(如 000000/100000)= 国家级 */
export function isNationalAdcode(adcode?: string | null): boolean {
  return !!adcode && adcode.slice(0, 2) === '00';
}

/** 综合判定:全国(adcode 00 前缀 / level=国家 / name 全国性) */
export function isNational(adcode?: string | null, level?: string | null, region?: string | null): boolean {
  if (isNationalAdcode(adcode)) return true;
  if (level && (level === '国家' || level === 'country')) return true;
  if (!adcode && region && (region === '全国' || region === '全国性' || region === '中国')) return true;
  return false;
}

/** adcode → 省级 meta(前两位查表);全国/无效返回 null */
export function provinceFromAdcode(adcode?: string | null): ProvinceMeta | null {
  if (!adcode || isNationalAdcode(adcode)) return null;
  const p2 = adcode.slice(0, 2);
  const m = PROVINCE_BY_PREFIX[p2];
  return m ? { adcode2: p2, adcode: `${p2}0000`, name: m.name, short: m.short } : null;
}

/** 无 adcode 时:按 region.name 最长前缀兜底匹配省级 */
export function provinceFromName(region?: string | null): ProvinceMeta | null {
  if (!region) return null;
  for (const { name, prefix } of PREFIX_BY_FULLNAME) {
    if (region.startsWith(name)) {
      const m = PROVINCE_BY_PREFIX[prefix];
      return { adcode2: prefix, adcode: `${prefix}0000`, name: m.name, short: m.short };
    }
  }
  return null;
}

/** 解析一条 entry 到省级 key(全名);全国 → null(由调用方归全国桶) */
export function resolveProvince(adcode?: string | null, region?: string | null): ProvinceMeta | null {
  return provinceFromAdcode(adcode) ?? provinceFromName(region);
}
