// 独立版外壳:原平台的提示条是同事写的,不在本仓。我的页面只用 push(文字, 类型),这里给一个最小实现,
// 由 src/standalone/shared/ToastHost.vue 显示。
import { defineStore } from 'pinia';
import { ref } from 'vue';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export const useToastStore = defineStore('toast', () => {
  const list = ref<{ id: number; type: ToastType; text: string }[]>([]);
  let next = 1;
  function push(text: string, type: ToastType = 'success', ttl = 3200) {
    const id = next++;
    list.value.push({ id, type, text });
    if (ttl > 0) setTimeout(() => { list.value = list.value.filter((t) => t.id !== id); }, ttl);
  }
  return { list, push };
});
