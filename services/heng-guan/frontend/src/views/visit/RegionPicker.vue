<!--
  独立版外壳:原平台的地区选择器是同事写的(省 / 市两级联动搜索),不在本仓。
  我的拜访录入弹窗只用到它的 v-model(地区文字,如"四川""山东-济南")和 placeholder,
  这里给一个最小版本:输入框 + 省份候选,也可以直接手打"省-市"。
-->
<script setup lang="ts">
defineProps<{ modelValue: string; placeholder?: string }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();

const PROVINCES = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海', '江苏', '浙江', '安徽',
  '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州',
  '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆',
];
const listId = `region-picker-${Math.random().toString(36).slice(2, 8)}`;
</script>

<template>
  <div class="region-picker">
    <input
      :value="modelValue"
      :placeholder="placeholder"
      :list="listId"
      autocomplete="off"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <datalist :id="listId">
      <option v-for="p in PROVINCES" :key="p" :value="p" />
    </datalist>
  </div>
</template>

<style scoped>
.region-picker input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg);
  color: var(--ink);
  font: inherit;
  font-size: 14px;
  padding: 10px 12px;
}
.region-picker input:focus {
  outline: 0;
  border-color: var(--orange);
  background: var(--white);
  box-shadow: 0 0 0 3px var(--orange-soft);
}
</style>
