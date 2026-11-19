// 独立版外壳:原来的接口客户端是照公共事务前端的 client.ts 改的(同事写的原件),本仓没有。
// 约定与原平台一致:接口挂在 /heng/api/v1 下(总览按这个前缀读),返回 { code: 0, data } 时只把 data 交给页面,
// code 不为 0 或请求失败按出错处理(页面里拿到的 e.message 就是提示语);研判后端回的是原始 JSON,原样交给页面。
// 离线演示页面不连后端,由演示入口(src/standalone/)给 http 装上替身适配器。
import axios from 'axios';

export const apiBase = '/heng/api/v1';

export const http = axios.create({ baseURL: apiBase, timeout: 60_000, withCredentials: true });

http.interceptors.response.use(
  (resp) => {
    const body = resp.data;
    if (body && typeof body === 'object' && 'code' in body) {
      return body.code === 0 ? body.data : Promise.reject(new Error(body.msg || '请求失败'));
    }
    return body;
  },
  (err) => Promise.reject(new Error(err?.response?.data?.msg || err?.response?.data?.message || err?.message || '网络异常')),
);
