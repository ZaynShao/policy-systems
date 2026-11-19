<!--
  这个组件原来是同事建的顶栏(TopBar.vue)里的一块,本仓只收我写的部分,其余是独立版的最小外壳。
  我写的:原项目 PR 16「站内消息通知」在顶栏里加的消息铃铛——未读数红点、下拉列表、点一条标为已读、
  只对管理层显示。这里把那几段原样拆成单独的组件;同事写的顶栏其余部分(品牌、全局搜索、切换身份)一行不带,
  我当时顺手加在身份切换上的一行"点别处收起"也不带。
  标「外壳」的是独立版补的:当前登录人的导入与取用、点页面别处的监听挂钩(原来是顶栏里同事写的)。
-->
<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue';
import { useUserStore } from '@/stores/user'; // 外壳
import { notificationApi, type NotificationItem } from '@/api/notification';

const userStore = useUserStore(); // 外壳
const notificationOpen = ref(false);
const notifications = ref<NotificationItem[]>([]);
const unreadCount = ref(0);
const notificationEl = ref<HTMLElement | null>(null);

const isManager = computed(() => userStore.current?.role === 'MANAGER');

function onDocClick(e: MouseEvent) { // 外壳
  const target = e.target as Node;
  if (notificationEl.value && !notificationEl.value.contains(target)) notificationOpen.value = false;
} // 外壳

async function loadNotifications(unreadOnly = false) {
  if (!isManager.value) return;
  const data = await notificationApi.list(unreadOnly);
  notifications.value = data.items;
  unreadCount.value = data.unreadCount;
}

async function loadUnreadCount() {
  if (!isManager.value) return;
  const data = await notificationApi.list(true);
  unreadCount.value = data.unreadCount;
}

async function toggleNotifications() {
  notificationOpen.value = !notificationOpen.value;
  if (notificationOpen.value) await loadNotifications(false);
}

async function markNotificationRead(item: NotificationItem) {
  if (item.readAt) return;
  const updated = await notificationApi.markRead(item.id);
  item.readAt = updated.readAt ?? new Date().toISOString();
  unreadCount.value = Math.max(0, unreadCount.value - 1);
}

function fmtNotificationTime(s: string) {
  return new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function levelText(level: NotificationItem['level']) {
  if (level === 'ERROR') return '错误';
  if (level === 'WARN') return '警告';
  return '提示';
}

onMounted(async () => {
  document.addEventListener('click', onDocClick); // 外壳
  await userStore.load();
  await loadUnreadCount();
}); // 外壳
onBeforeUnmount(() => { // 外壳
  document.removeEventListener('click', onDocClick); // 外壳
}); // 外壳

watch(isManager, (ok) => {
  if (ok) loadUnreadCount();
  else {
    notificationOpen.value = false;
    notifications.value = [];
    unreadCount.value = 0;
  }
});
</script>

<template>
    <div v-if="isManager" ref="notificationEl" class="notification-wrap">
      <button class="notification-btn" title="消息" @click="toggleNotifications">
        <span class="notification-icon">🔔</span>
        <span v-if="unreadCount > 0" class="notification-dot">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
      </button>

      <div v-if="notificationOpen" class="notification-dropdown" @click.stop>
        <div class="notification-head">
          <span>消息</span>
          <span v-if="unreadCount > 0" class="notification-count">{{ unreadCount }} 未读</span>
        </div>
        <div v-if="!notifications.length" class="notification-empty">暂无消息</div>
        <div v-for="n in notifications" :key="n.id"
             class="notification-item"
             :class="{ unread: !n.readAt }"
             @click="markNotificationRead(n)">
          <div class="notification-item-top">
            <span class="notification-level" :class="`level-${n.level.toLowerCase()}`">{{ levelText(n.level) }}</span>
            <span class="notification-time">{{ fmtNotificationTime(n.createdAt) }}</span>
          </div>
          <div class="notification-title">{{ n.title }}</div>
          <div v-if="n.body" class="notification-body">{{ n.body }}</div>
        </div>
      </div>
    </div>
</template>

<style scoped>
.notification-wrap {
  position: relative;
  margin-right: 8px;
}
.notification-btn {
  width: 34px; height: 34px;
  border: 1px solid var(--line);
  background: var(--white);
  color: var(--ink-2);
  border-radius: 50%;
  cursor: pointer;
  position: relative;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s, border-color 0.15s;
}
.notification-btn:hover { background: var(--bg-2); border-color: var(--orange-soft-2); }
.notification-icon { font-size: 15px; line-height: 1; }
.notification-dot {
  position: absolute; top: -4px; right: -5px;
  min-width: 17px; height: 17px; padding: 0 4px;
  border-radius: 9px;
  background: var(--red);
  color: #fff;
  font-size: 10px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid var(--white);
}
.notification-dropdown {
  position: absolute;
  top: 100%; right: 0;
  margin-top: 8px;
  width: 340px;
  max-height: 420px;
  overflow: auto;
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: 10px;
  box-shadow: var(--shadow-lg);
  z-index: 120;
}
.notification-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  font-size: 13px; font-weight: 600; color: var(--ink);
}
.notification-count {
  font-size: 11px; color: var(--orange-2);
  background: var(--orange-soft);
  border-radius: 10px;
  padding: 2px 7px;
}
.notification-empty {
  padding: 22px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--ink-3);
}
.notification-item {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-2);
  cursor: pointer;
}
.notification-item:hover { background: var(--bg); }
.notification-item.unread { background: #fffaf5; }
.notification-item-top {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px;
  margin-bottom: 5px;
}
.notification-level {
  font-size: 10px; font-weight: 700;
  padding: 2px 6px;
  border-radius: 8px;
}
.level-info { color: var(--orange-2); background: var(--orange-soft); }
.level-warn { color: var(--amber); background: #FFFBEB; }
.level-error { color: var(--red); background: var(--red-soft); }
.notification-time { font-size: 11px; color: var(--ink-4); }
.notification-title {
  font-size: 13px; font-weight: 600; color: var(--ink);
  line-height: 1.4;
}
.notification-body {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ink-3);
  line-height: 1.45;
  white-space: pre-wrap;
}
</style>
