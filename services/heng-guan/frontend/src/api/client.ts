// 独立版外壳:原平台的接口客户端是同事写的,不在本仓。这里是我的页面要用到的最小替身——
// 约定与原平台一致:接口统一挂在 /heng/api/v1 下,返回 { code: 0, data } 时只把 data 交给页面,
// 其余情况按出错处理(页面里 catch 到的 e.message 就是提示语)。
// 离线演示页面不连后端,由各页面的演示入口(src/standalone/<页面>/)给 http 装上替身适配器。
import axios from 'axios';

export const apiBase = '/heng/api/v1';

export const http = axios.create({ baseURL: apiBase, timeout: 120_000 });

http.interceptors.response.use(
  (resp) => {
    const body = resp.data;
    if (body && typeof body === 'object' && 'code' in body) {
      return body.code === 0 ? body.data : Promise.reject(new Error(body.msg || '请求失败'));
    }
    return body;
  },
  (err) => Promise.reject(new Error(err?.response?.data?.msg || err?.message || '网络异常')),
);
