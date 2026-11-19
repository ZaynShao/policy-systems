// 独立版外壳:原平台的"当前登录人"是同事写的(从平台登录信息取账号、角色),不在本仓。
// 我的消息铃铛和拜访录入弹窗只用到 current(账号 id、名字、角色、地区)和 load() 这两样,
// 这里给一个最小实现:load() 向 /workbench/whoami 要当前账号(独立版的演示入口给它装了替身)。
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { http } from '@/api/client';

export interface CurrentUser {
  id: string;
  name: string;
  role: 'OPERATOR' | 'HQ_GA' | 'FIELD_GA' | 'MANAGER' | string;
  region?: string;
}

export const useUserStore = defineStore('user', () => {
  const current = ref<CurrentUser | null>(null);
  let pending: Promise<void> | null = null;

  function load() {
    pending ??= http.get<any, CurrentUser>('/workbench/whoami')
      .then((me) => { current.value = me?.id ? me : null; })
      .catch(() => { current.value = null; })
      .finally(() => { pending = null; });
    return pending;
  }

  return { current, load };
});
