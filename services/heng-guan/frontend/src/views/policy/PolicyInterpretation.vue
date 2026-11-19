<!--
  政策解读页(问答界面)。这个文件原来是同事建的(公共事务平台的「政策解读」页),我在原项目 PR 646 把它改写成问答界面,
  之后 PR 694、983、1043 继续改;到 PR 1043 合并时全文 409 行里 371 行是我写的。本仓只收我写的部分,其余是独立版的最小外壳:
  - 同事原来那 38 行里,4 条样式规则(.page-head h1、.page-head .sub、.btn-primary、.btn-outline)换成了独立版自己写的;
  - 另外 34 行是单文件组件必需的结构(<script>/<template>/<style> 标签、页头容器、收尾的 </div> 和空行),没有别的写法,照原样保留。
  页面用到的样式变量(--ink、--orange、--line 等)和 .page、.btn 的基础样式原来在平台公共样式里,独立版由演示入口的 theme.css 提供。
  内容停在我最后一次改它的时候(原项目 PR 1043,2026-09-01);同事之后在这个文件上的改动不收。
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import {
  fetchQaBusinessContext,
  streamQaChat,
  TOOL_LABELS,
  type QaBusinessContext,
  type QaCitation,
  type QaMessage,
  type QaPlan,
  type QaToolEvent,
  type QaVerify,
} from '@/api/policy-qa';

interface UiMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
  tools?: Array<{ seq: number; label: string; detail: string; done: boolean }>;
  plan?: QaPlan;
  /** 只在核验发现问题时才有值 */
  verify?: QaVerify;
  citations?: QaCitation[];
  error?: string;
}

/** 检索计划 → 一句人话。业务同事关心的是"它打算怎么查",不是字段名。 */
function planSummary(p: QaPlan): string {
  const parts: string[] = [];
  const themes = (p.theme_labels?.length ? p.theme_labels : p.themes) ?? [];
  if (themes.length) parts.push(`主题「${themes.join('、')}」`);
  if (p.business_lines?.length) parts.push(`${p.business_lines.join('、')}业务`);
  if (p.keywords?.length) parts.push(`关键词「${p.keywords.join('、')}」`);
  if (p.issuers?.length) parts.push(`另按${p.issuers.join('、')}单独查一遍`);
  if (!parts.length) return p.kind === 'single_policy' ? '定位这份政策的原文' : '按时间范围通查';
  return parts.join('，');
}

const SUGGESTIONS = [
  '最近对充电业务影响大的政策有哪些？',
  '最近电力市场方面有什么新政策？',
  '解读一下最新的储能相关政策',
  '上海市今年出台了哪些充电相关的文件？',
];

const messages = ref<UiMessage[]>([]);
const input = ref('');
const busy = ref(false);
const scroller = ref<HTMLElement | null>(null);
let seq = 0;
let controller: AbortController | null = null;

const isEmpty = computed(() => messages.value.length === 0);

// 业务框定开关。服务端没配战略画像时 bizCtx.available=false,勾选置灰——
// 让用户勾一个其实不生效的框,比不给这个框更糟:他会以为答案里带了业务判断。
const bizCtx = ref<QaBusinessContext | null>(null);
const useBiz = ref(false);
const bizReady = computed(() => bizCtx.value?.available === true);
const bizHint = computed(() =>
  bizReady.value
    ? `按公司业务战略画像判断相关性（${bizCtx.value?.profile_id}，生效 ${bizCtx.value?.effective_from}）`
    : '服务端未配置业务战略画像，本项不可用',
);

onMounted(async () => {
  const ctx = await fetchQaBusinessContext();
  bizCtx.value = ctx;
  // 读不到就保持关闭:宁可少一层框定,也不要让开关显示的状态和实际发生的事不一致。
  useBiz.value = ctx?.available === true && ctx.default_on;
});

onBeforeUnmount(() => controller?.abort());

function scrollToBottom() {
  nextTick(() => {
    const el = scroller.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

/**
 * 极简 markdown → html。
 *
 * **先转义再渲染**:回答里会逐字引用政策原文,而原文是从政府网站抓来的,
 * 带着页面里的各种标记(实测见过 <img> 和整段导航)。不转义就等于把抓来的
 * HTML 在平台登录态里执行。
 */
function renderMd(src: string): string {
  const esc = src
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  return esc
    .replace(/^#### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/\n{2,}/g, '<br><br>')
    .replace(/\n(?!<)/g, '<br>');
}

function reset() {
  controller?.abort();
  controller = null;
  messages.value = [];
  input.value = '';
  busy.value = false;
}

function ask(text: string) {
  input.value = text;
  send();
}

async function send() {
  const q = input.value.trim();
  if (!q || busy.value) return;

  busy.value = true;
  input.value = '';
  messages.value.push({ id: ++seq, role: 'user', content: q });
  // **必须 reactive**:messages 是 ref 数组,push 进去的对象被原样(raw)存进数组,
  // 模板读取时才现包一层 proxy。裸对象的话,下面 onDelta 里 `reply.content += text`
  // 改的是 raw、绕过 proxy 的 setter,一次重渲染都不触发 —— SSE 明明在一块块地流,
  // 界面却一直卡在「正在检索政策库…」,直到 send() 末尾 busy.value = false(真 ref)
  // 才触发唯一一次重渲,把答复/工具进度/计划/引用一次性抖出来。流式就白做了。
  const reply: UiMessage = reactive({
    id: ++seq,
    role: 'assistant',
    content: '',
    streaming: true,
    tools: [],
    citations: [],
  });
  messages.value.push(reply);
  scrollToBottom();

  // 服务端不存会话,历史每次全量带上(不含 system —— 答题纪律在服务端)
  const history: QaMessage[] = messages.value
    .filter((m) => !m.streaming && !m.error)
    .map((m) => ({ role: m.role, content: m.content }));

  controller = new AbortController();
  await streamQaChat(
    history,
    {
      onPlan(p: QaPlan) {
        reply.plan = p;
        scrollToBottom();
      },
      onVerify(v: QaVerify) {
        // 核验只报告不改写答案,所以这条必须显示出来——不显示等于这层没做
        reply.verify = v;
        scrollToBottom();
      },
      onTool(t: QaToolEvent) {
        const label = TOOL_LABELS[t.name] ?? t.name;
        const existing = reply.tools!.find((x) => x.seq === t.seq);
        if (t.status === 'start') {
          if (!existing) {
            reply.tools!.push({ seq: t.seq, label, detail: t.args_preview ?? '', done: false });
          }
        } else if (existing) {
          existing.done = true;
        }
        scrollToBottom();
      },
      onDelta(text) {
        reply.content += text;
        scrollToBottom();
      },
      onDeltaReset() {
        // 刚显示的那段是模型的规划自语(它接着还要调工具),丢掉
        reply.content = '';
      },
      onDone(d) {
        reply.citations = d.citations ?? [];
        reply.streaming = false;
        scrollToBottom();
      },
      onError(msg) {
        reply.streaming = false;
        reply.error = msg;
        scrollToBottom();
      },
    },
    controller.signal,
    // 只在可用时才发这个字段;不可用时不发,让服务端走它自己的默认。
    bizReady.value ? { useBusinessContext: useBiz.value } : undefined,
  );

  reply.streaming = false;
  busy.value = false;
  controller = null;
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>政策解读<span class="beta">beta</span></h1>
        <div class="sub">基于公司政策库的问答 · 回答只锚政策原文，结论请点开引用核对</div>
      </div>
      <button v-if="!isEmpty" class="btn btn-outline" @click="reset">新对话</button>
    </div>

    <div class="chat">
      <div ref="scroller" class="stream">
        <!-- 空态：给几个能直接点的问题，降低"不知道能问什么"的门槛 -->
        <div v-if="isEmpty" class="empty">
          <div class="empty-title">问我关于能源政策的问题</div>
          <div class="empty-sub">
            覆盖国家部委、省、市三级的政策原文，每日更新。可以问某份政策讲了什么，
            也可以问最近哪些政策会影响加油、充电、电力业务。
          </div>
          <div class="chips-title">你可以这样问</div>
          <div class="chips">
            <button v-for="s in SUGGESTIONS" :key="s" class="chip" @click="ask(s)">{{ s }}</button>
          </div>

          <!-- 免责：放在提问之前，不能只挂在底部让人问完才看见 -->
          <div class="notice">
            和其他 AI 一样，它会出错。文号、日期、金额、适用范围这类关键信息，
            请点开引用回原文核对后再用，尤其是要写进对外材料的时候。
          </div>
        </div>

        <div v-for="m in messages" :key="m.id" class="row" :class="m.role">
          <div v-if="m.role === 'user'" class="bubble me">{{ m.content }}</div>

          <div v-else class="bot">
            <!-- 检索计划：先说清楚打算怎么查，再让用户看它实际查了什么 -->
            <div v-if="m.plan" class="plan">
              <span class="plan-tag">检索思路</span>
              <span class="plan-text">{{ planSummary(m.plan) }}</span>
            </div>

            <!-- 检索过程：让用户看得见它查了什么，而不是干等 -->
            <div v-if="m.tools && m.tools.length" class="tools">
              <div v-for="t in m.tools" :key="t.seq" class="tool" :class="{ done: t.done }">
                <span class="dot"></span>
                <span class="tool-label">{{ t.label }}</span>
                <span v-if="t.detail" class="tool-detail">{{ t.detail }}</span>
              </div>
            </div>

            <div v-if="m.content" class="answer" v-html="renderMd(m.content)"></div>
            <div v-else-if="m.streaming" class="thinking">正在检索政策库…</div>

            <div v-if="m.error" class="err">{{ m.error }}</div>

            <!--
              事实核验：服务端把答案里的文号和引文拿回检索到的材料逐字比对，
              对不上的列在这里。它不改写答案，所以这块必须显示——不显示就等于没核验。
            -->
            <div v-if="m.verify && m.verify.unsupported.length" class="verify">
              <div class="verify-title">这些地方请务必点开引用核对</div>
              <div v-for="(u, i) in m.verify.unsupported" :key="i" class="verify-item">
                <span class="verify-kind">{{ u.kind === 'doc_number' ? '文号' : '引文' }}</span>
                <span class="verify-text">{{ u.text }}</span>
                <div class="verify-hint">{{ u.hint }}</div>
              </div>
            </div>

            <!-- 引用：事实核对的入口，必须能点回原文 -->
            <div v-if="m.citations && m.citations.length" class="cites">
              <div class="cites-title">引用政策（{{ m.citations.length }}）</div>
              <div v-for="c in m.citations" :key="c.pid" class="cite">
                <a v-if="c.source_url" :href="c.source_url" target="_blank" rel="noopener noreferrer">
                  {{ c.title }}
                </a>
                <span v-else>{{ c.title }}</span>
                <span v-if="c.doc_number" class="cite-num">{{ c.doc_number }}</span>
                <div v-if="c.caveat" class="cite-caveat">{{ c.caveat }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="composer-opts">
        <label class="opt" :class="{ disabled: !bizReady }" :title="bizHint">
          <input type="checkbox" v-model="useBiz" :disabled="!bizReady || busy" />
          <span>结合公司业务分析</span>
        </label>
        <span v-if="!bizReady" class="opt-note">未配置业务战略画像</span>
      </div>

      <div class="composer">
        <textarea
          v-model="input"
          class="input"
          rows="1"
          placeholder="问一个政策问题，Enter 发送，Shift+Enter 换行"
          :disabled="busy"
          @keydown="onKeydown"
        ></textarea>
        <button class="btn btn-primary" :disabled="busy || !input.trim()" @click="send">
          {{ busy ? '回答中…' : '发送' }}
        </button>
      </div>
      <div class="foot-hint">
        AI 生成的回答可能出错或有疏漏，关键信息请点开引用核对原文。
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 24px 28px 32px; display: flex; flex-direction: column; height: 100%; box-sizing: border-box; }
.page-head { margin-bottom: 14px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.page-head h1 { margin: 0; font-size: 20px; font-weight: 700; color: var(--ink); }
.page-head .sub { margin-top: 4px; font-size: 13px; color: var(--ink-3); }
.beta { margin-left: 8px; padding: 2px 7px; border: 1px solid var(--orange-2); border-radius: 999px; background: var(--orange-soft); color: var(--orange-2); font-size: 11px; font-weight: 700; letter-spacing: 0.5px; vertical-align: middle; }

.chat { background: white; border: 1px solid var(--line); border-radius: 12px; display: flex; flex-direction: column; flex: 1; min-height: 420px; max-height: calc(100vh - 170px); overflow: hidden; }
.stream { flex: 1; overflow-y: auto; padding: 20px 22px; }

.empty { max-width: 560px; margin: 32px auto; text-align: center; }
.empty-title { font-size: 17px; font-weight: 700; color: var(--ink); }
.empty-sub { font-size: 13px; color: var(--ink-3); line-height: 1.7; margin-top: 8px; }
.chips-title { margin-top: 22px; font-size: 12px; font-weight: 700; color: var(--ink-3); letter-spacing: 0.2px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 10px; }
.chip { padding: 7px 12px; border: 1px solid var(--line); border-radius: 16px; background: white; font-size: 12.5px; color: var(--ink-2); cursor: pointer; font-family: inherit; }
.chip:hover { background: var(--orange-soft); border-color: var(--orange-2); color: var(--orange-2); }

.notice { margin-top: 22px; padding: 9px 12px; border: 1px solid #FDE68A; border-radius: 8px; background: #FFFBEB; color: #B45309; font-size: 12px; line-height: 1.65; text-align: left; }

.row { margin-bottom: 18px; display: flex; }
.row.user { justify-content: flex-end; }
.bubble.me { max-width: 78%; background: linear-gradient(135deg, var(--orange), var(--orange-2)); color: white; padding: 9px 13px; border-radius: 12px 12px 2px 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.bot { max-width: 100%; width: 100%; }

.plan { margin-bottom: 10px; display: flex; align-items: baseline; gap: 8px; font-size: 12px; line-height: 1.6; color: var(--ink-3); }
.plan-tag { flex: none; padding: 1px 7px; border-radius: 4px; background: var(--orange-soft); color: var(--orange-2); font-weight: 700; font-size: 11px; }
.plan-text { word-break: break-word; }

.tools { margin-bottom: 10px; display: flex; flex-direction: column; gap: 4px; }
.tool { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--ink-4); }
.tool .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--orange-2); flex: none; opacity: 0.5; }
.tool.done .dot { opacity: 1; }
.tool-label { font-weight: 600; color: var(--ink-3); }
.tool-detail { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.answer { font-size: 14px; line-height: 1.75; color: var(--ink-2); word-break: break-word; }
.answer :deep(h3) { font-size: 15px; font-weight: 700; color: var(--ink); margin: 16px 0 8px; }
.answer :deep(h4) { font-size: 14px; font-weight: 700; color: var(--ink); margin: 14px 0 6px; }
.answer :deep(h5) { font-size: 13.5px; font-weight: 600; color: var(--ink); margin: 12px 0 6px; }
.answer :deep(strong) { color: var(--ink); font-weight: 700; }
.answer :deep(ul) { padding-left: 20px; margin: 6px 0; }
.answer :deep(li) { margin: 3px 0; }

.thinking { font-size: 13px; color: var(--ink-4); }
.err { margin-top: 8px; font-size: 13px; color: #DC2626; background: #FEF2F2; border: 1px solid #FECACA; padding: 8px 10px; border-radius: 7px; }

/* 核验提醒用琥珀色而不是红色:这不是"服务出错",是"这句话我没核实上,你去看看" */
.verify { margin-top: 12px; border: 1px solid #FDE68A; background: #FFFBEB; border-radius: 8px; padding: 9px 11px; }
.verify-title { font-size: 12.5px; font-weight: 700; color: #B45309; margin-bottom: 6px; }
.verify-item { font-size: 12px; line-height: 1.6; margin-top: 5px; color: #92400E; }
.verify-kind { display: inline-block; padding: 0 5px; margin-right: 6px; border-radius: 3px; background: #FDE68A; font-size: 11px; font-weight: 700; }
.verify-text { font-weight: 600; word-break: break-all; }
.verify-hint { color: #B45309; opacity: 0.85; margin-top: 1px; }

.cites { margin-top: 14px; border-top: 1px dashed var(--line); padding-top: 10px; }
.cites-title { font-size: 12px; font-weight: 700; color: var(--ink-3); margin-bottom: 6px; }
.cite { font-size: 12.5px; line-height: 1.6; margin-bottom: 6px; }
.cite a { color: var(--orange-2); text-decoration: none; }
.cite a:hover { text-decoration: underline; }
.cite-num { color: var(--ink-4); margin-left: 6px; }
.cite-caveat { color: #B45309; background: #FFFBEB; border-radius: 5px; padding: 5px 8px; margin-top: 3px; font-size: 11.5px; line-height: 1.5; }

.composer-opts { border-top: 1px solid var(--line); padding: 8px 14px 0; display: flex; gap: 10px; align-items: center; }
.opt { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); cursor: pointer; }
.opt.disabled { cursor: not-allowed; opacity: 0.55; }
.opt input { cursor: inherit; }
.opt-note { font-size: 12px; color: var(--muted); opacity: 0.75; }
.composer { padding: 10px 14px 12px; display: flex; gap: 10px; align-items: flex-end; }
.input { flex: 1; resize: none; border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; font-size: 14px; font-family: inherit; line-height: 1.5; outline: none; max-height: 120px; color: var(--ink); }
.input:focus { border-color: var(--orange-2); }
.btn { padding: 9px 18px; border: none; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; }
.btn:disabled { opacity: 0.5; cursor: default; }
.btn-primary { background: var(--orange-2); color: #fff; }
.btn-outline { background: #fff; border: 1px solid var(--line); color: var(--ink-2); }
.foot-hint { font-size: 11.5px; color: var(--ink-4); padding: 0 14px 10px; }

@media (max-width: 767px) {
  .page { padding: 14px 12px 16px; }
  .page-head h1 { font-size: 19px; }
  .chat { max-height: calc(100vh - 132px); border-radius: 10px; }
  .stream { padding: 14px 12px; }
  .bubble.me { max-width: 88%; }
  .chips { justify-content: stretch; flex-direction: column; }
  .chip { text-align: left; }
}
</style>
