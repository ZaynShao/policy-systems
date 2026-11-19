// 独立版外壳:原来的提示条是同事写的,本仓没有。页面只用 push(文字, 类型),这里给最小实现,
// 由 components/ui/ToastStack.vue 显示,点一下或过几秒消失。
import { defineStore } from 'pinia';
import { ref } from 'vue';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export const useToastStore = defineStore('toast', () => {
  const list = ref<{ id: number; type: ToastType; text: string }[]>([]);
  let next = 1;
  function dismiss(id: number) {
    list.value = list.value.filter((t) => t.id !== id);
  }
  function push(text: string, type: ToastType = 'success', ttl = 3200) {
    const id = next++;
    list.value.push({ id, type, text });
    if (ttl > 0) setTimeout(() => dismiss(id), ttl);
  }
  return { list, push, dismiss };
});
