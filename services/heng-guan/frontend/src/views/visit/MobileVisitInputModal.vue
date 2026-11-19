<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { visitApi, type Assignee, type OrgWithContacts, type ParsedVisitFields } from '@/api/visit';
import { useToastStore } from '@/stores/toast';
import { useUserStore } from '@/stores/user';
import RegionPicker from './RegionPicker.vue';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', id: string): void }>();

const toast = useToastStore();
const userStore = useUserStore();
const orgs = ref<OrgWithContacts[]>([]);
const assignees = ref<Assignee[]>([]);
const transcript = ref('');
const interimText = ref('');
const recording = ref(false);
const parsing = ref(false);
const submitting = ref(false);
let recognition: any = null;

const form = reactive({
  region: '',
  orgId: '',
  orgName: '',
  contactName: '',
  contactDepart: '',
  contactPhone: '',
  topic: '',
  goal: '',
  plannedAt: '',
  mainAssigneeId: '',
});

const speechSupported = computed(() => {
  if (typeof window === 'undefined') return false;
  return !!((window as any).webkitSpeechRecognition || (window as any).SpeechRecognition);
});
const displayTranscript = computed(() => [transcript.value, interimText.value].filter(Boolean).join(''));
const orgContacts = computed(() => orgs.value.find((o) => o.id === form.orgId)?.contacts ?? []);
const assigneeOptions = computed(() => {
  const list = assignees.value.slice();
  const me = userStore.current as any;
  if (me?.id && !list.some((a) => a.id === me.id)) {
    list.unshift({ id: me.id, name: me.name, role: me.role || '', region: me.region });
  }
  return list;
});
const myId = computed(() => userStore.current?.id || '');

watch(
  () => form.orgName,
  (name) => {
    const m = orgs.value.find((o) => o.name === (name || '').trim());
    form.orgId = m ? m.id : '';
  },
);

watch(
  () => props.open,
  (open) => {
    if (!open) {
      stopRecord();
      return;
    }
    resetForm();
  },
);

onMounted(async () => {
  if (!userStore.current) await userStore.load();
  try {
    [orgs.value, assignees.value] = await Promise.all([visitApi.orgs(), visitApi.assignees()]);
  } catch (e: any) {
    toast.push(e?.message ?? '加载基础数据失败', 'error');
  }
});

onUnmounted(() => stopRecord());

function resetForm() {
  transcript.value = '';
  interimText.value = '';
  form.region = '';
  form.orgId = '';
  form.orgName = '';
  form.contactName = '';
  form.contactDepart = '';
  form.contactPhone = '';
  form.topic = '';
  form.goal = '';
  const d = new Date();
  d.setDate(d.getDate() + 7);
  form.plannedAt = toLocalDatetime(d);
  form.mainAssigneeId = userStore.current?.id || '';
}

function startRecord() {
  if (recording.value) return;
  const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
  if (!SR) {
    toast.push('当前浏览器不支持语音识别，可手动填写表单', 'info');
    return;
  }
  recognition = new SR();
  recognition.lang = 'zh-CN';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onresult = (event: any) => {
    let finalText = '';
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += text;
      else interim += text;
    }
    if (finalText) transcript.value += finalText;
    interimText.value = interim;
  };
  recognition.onerror = () => {
    stopRecord();
    toast.push('语音识别中断，可重试或手动输入', 'error');
  };
  recognition.onend = () => {
    if (recording.value) {
      try { recognition.start(); } catch {}
    }
  };
  recognition.start();
  recording.value = true;
}

function stopRecord() {
  recording.value = false;
  interimText.value = '';
  if (recognition) {
    try { recognition.stop(); } catch {}
    recognition = null;
  }
}

async function finishRecordAndParse() {
  const text = displayTranscript.value.trim();
  stopRecord();
  await parseTranscript(text);
}

async function parseTranscript(sourceText?: string) {
  const text = (sourceText ?? displayTranscript.value).trim();
  if (text.length < 2) {
    toast.push('请先说一段或输入拜访内容', 'info');
    return;
  }
  parsing.value = true;
  try {
    const resp = await visitApi.parseVoiceVisit({
      transcript: text,
      context: {
        today: todayLocal(),
        currentRegion: form.region || null,
        currentOrgName: form.orgName || null,
      },
    });
    applyParsed(resp.parsed);
    toast.push('已根据语音填入表单，请确认后创建', 'success');
  } catch (e: any) {
    toast.push(e?.message || '语音解析失败，可手动补充', 'error');
  } finally {
    parsing.value = false;
  }
}

function applyParsed(parsed: ParsedVisitFields) {
  if (parsed.region) form.region = parsed.region;
  if (parsed.orgName) form.orgName = parsed.orgName;
  if (parsed.contactName) form.contactName = parsed.contactName;
  if (parsed.contactDepart) form.contactDepart = parsed.contactDepart;
  if (parsed.contactPhone) form.contactPhone = parsed.contactPhone;
  if (parsed.topic) form.topic = parsed.topic;
  if (parsed.goal) form.goal = parsed.goal;
  if (parsed.plannedAt) form.plannedAt = toLocalDatetime(new Date(parsed.plannedAt));
}

async function submit() {
  if (!form.region.trim() || !form.topic.trim() || !form.goal.trim() || !form.plannedAt || !form.mainAssigneeId) {
    toast.push('地区 / 拜访主题 / 拜访目标 / 计划时间 / 主拜访人 必填', 'error');
    return;
  }
  if (form.contactPhone.trim() && !/^\d{11}$/.test(form.contactPhone.trim())) {
    toast.push('联系电话需为 11 位数字', 'error');
    return;
  }
  submitting.value = true;
  try {
    const v = await visitApi.create({
      region: form.region.trim(),
      orgId: form.orgId || undefined,
      orgName: form.orgName.trim() || undefined,
      contactName: form.contactName.trim() || undefined,
      contactDepart: form.contactDepart.trim() || undefined,
      contactPhone: form.contactPhone.trim() || undefined,
      topic: form.topic.trim(),
      goal: form.goal.trim(),
      plannedAt: new Date(form.plannedAt).toISOString(),
      mainAssigneeId: form.mainAssigneeId,
    });
    toast.push(`已创建：${v.code}`, 'success');
    emit('created', v.id);
    emit('close');
  } catch (e: any) {
    toast.push(`创建失败：${e?.message}`, 'error');
  } finally {
    submitting.value = false;
  }
}

function todayLocal() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function toLocalDatetime(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day}T${hh}:${mm}`;
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="mi-mask" @click.self="emit('close')">
      <section class="mi-panel">
        <header class="mi-head">
          <div>
            <div class="mi-title">+ 新建拜访</div>
            <div class="mi-sub">可手填，也可语音录入</div>
          </div>
          <button class="mi-close" @click="emit('close')">×</button>
        </header>

        <div class="mi-body">
          <div class="mi-voice">
            <textarea
              v-model="transcript"
              class="mi-transcript"
              rows="4"
              placeholder="例如：明天下午去四川省能源局找张处长，沟通储能新政落地口径，想确认申报时间表和白名单要求"
            ></textarea>
            <div v-if="interimText" class="mi-interim">{{ interimText }}</div>
            <div class="mi-actions">
              <button v-if="!recording" class="mi-record" :disabled="!speechSupported || parsing" @click="startRecord">
                {{ parsing ? '识别中...' : '开始说话' }}
              </button>
              <button v-else class="mi-record mi-recording" @click="finishRecordAndParse"><span class="mi-dot"></span>停止并识别</button>
            </div>
            <div v-if="!speechSupported" class="mi-hint">当前浏览器不支持语音识别，可直接手动填写表单。</div>
          </div>

          <div class="mi-form">
            <label class="mi-field">
              <span>地区 *</span>
              <RegionPicker v-model="form.region" placeholder="搜索省 / 市" />
            </label>
            <label class="mi-field">
              <span>目标机构</span>
              <input v-model="form.orgName" list="miOrgOptions" placeholder="如：四川省能源局" />
              <datalist id="miOrgOptions">
                <option v-for="o in orgs" :key="o.id" :value="o.name">{{ o.region }}</option>
              </datalist>
            </label>
            <label class="mi-field">
              <span>对接人</span>
              <select v-if="orgContacts.length" v-model="form.contactName">
                <option value="">手动填写...</option>
                <option v-for="c in orgContacts" :key="c.id" :value="c.name">{{ c.name }}（{{ c.title }}）</option>
              </select>
              <input v-else v-model="form.contactName" placeholder="如：张处长" />
            </label>
            <div class="mi-grid">
              <label class="mi-field">
                <span>部门</span>
                <input v-model="form.contactDepart" placeholder="如：新能源处" />
              </label>
              <label class="mi-field">
                <span>联系电话</span>
                <input v-model="form.contactPhone" maxlength="11" inputmode="numeric" placeholder="11 位手机号" />
              </label>
            </div>
            <label class="mi-field">
              <span>拜访主题 *</span>
              <input v-model="form.topic" placeholder="本次要沟通的主题" />
            </label>
            <label class="mi-field">
              <span>拜访目标 / 期望产出 *</span>
              <textarea v-model="form.goal" rows="3" placeholder="希望确认什么、争取什么结果"></textarea>
            </label>
            <div class="mi-grid">
              <label class="mi-field">
                <span>计划时间 *</span>
                <input v-model="form.plannedAt" type="datetime-local" />
              </label>
              <label class="mi-field">
                <span>主拜访人 *</span>
                <select v-model="form.mainAssigneeId">
                  <option value="">请选择</option>
                  <option v-for="a in assigneeOptions" :key="a.id" :value="a.id">
                    {{ a.name }}{{ a.id === myId ? '（我）' : '' }}
                  </option>
                </select>
              </label>
            </div>
          </div>
        </div>

        <footer class="mi-foot">
          <button class="mi-secondary" :disabled="submitting" @click="emit('close')">取消</button>
          <button class="mi-submit" :disabled="submitting" @click="submit">{{ submitting ? '创建中...' : '确认创建' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.mi-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(15, 23, 42, 0.42);
  display: flex;
  align-items: flex-end;
}
.mi-panel {
  width: 100%;
  max-height: 94vh;
  background: var(--bg);
  border-radius: 18px 18px 0 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 -14px 40px rgba(15, 23, 42, 0.22);
}
.mi-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: var(--white);
  border-bottom: 1px solid var(--line);
}
.mi-title { font-size: 18px; font-weight: 700; color: var(--ink); }
.mi-sub { margin-top: 3px; font-size: 12px; color: var(--ink-3); }
.mi-close {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 17px;
  background: var(--bg);
  color: var(--ink-2);
  font-size: 20px;
}
.mi-body {
  overflow: auto;
  padding: 14px;
}
.mi-voice,
.mi-form {
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px;
}
.mi-form { margin-top: 12px; }
.mi-transcript,
.mi-field input,
.mi-field select,
.mi-field textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg);
  color: var(--ink);
  font: inherit;
  font-size: 14px;
  padding: 10px 12px;
  box-sizing: border-box;
}
.mi-transcript:focus,
.mi-field input:focus,
.mi-field select:focus,
.mi-field textarea:focus {
  outline: 0;
  border-color: var(--orange);
  background: var(--white);
  box-shadow: 0 0 0 3px var(--orange-soft);
}
.mi-interim {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 9px;
  background: var(--orange-soft);
  color: var(--orange-2);
  font-size: 12px;
}
.mi-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 10px;
}
.mi-record,
.mi-submit,
.mi-secondary {
  height: 42px;
  border-radius: 10px;
  font: inherit;
  font-weight: 700;
  border: 1px solid transparent;
}
.mi-record {
  background: var(--orange);
  color: white;
}
.mi-record:disabled {
  background: #CBD5E1;
}
.mi-recording {
  background: var(--orange-2);
}
.mi-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  background: white;
  animation: mi-pulse 1s infinite;
}
.mi-submit {
  background: var(--orange);
  color: white;
}
.mi-hint {
  margin-top: 8px;
  color: var(--ink-3);
  font-size: 12px;
}
.mi-field {
  display: block;
  margin-bottom: 12px;
}
.mi-field span {
  display: block;
  margin-bottom: 6px;
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 700;
}
.mi-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.mi-foot {
  display: grid;
  grid-template-columns: 0.8fr 1.2fr;
  gap: 10px;
  padding: 12px 14px 16px;
  background: var(--white);
  border-top: 1px solid var(--line);
}
.mi-secondary {
  background: var(--bg);
  color: var(--ink-2);
  border-color: var(--line);
}
@keyframes mi-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
@media (max-width: 380px) {
  .mi-grid,
  .mi-actions {
    grid-template-columns: 1fr;
  }
}
</style>
