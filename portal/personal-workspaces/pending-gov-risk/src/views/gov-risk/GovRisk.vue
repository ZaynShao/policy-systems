<script setup lang="ts">
// 政诉预判:页面逻辑仍是原来的原生脚本(gov-risk-app.mjs),这里只负责给它一块 DOM、进出时挂载和卸载。
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { mountGovRisk } from './gov-risk-app.mjs';
import './gov-risk.css';

const root = ref<HTMLElement | null>(null);
let dispose: (() => void) | null = null;

onMounted(() => { if (root.value) dispose = mountGovRisk(root.value); });
onBeforeUnmount(() => { dispose?.(); dispose = null; });
</script>

<template>
  <div ref="root" class="gr-wrap">
    <div class="gr-heading">
      <div>
        <p class="gr-eyebrow">政诉工作</p>
        <h1>政诉预判</h1>
        <p class="gr-sub" id="meta-line"></p>
      </div>
      <div class="gr-save" id="save-status" role="status" aria-live="polite"></div>
    </div>

    <!-- 平台上的数据与研判进度;本机上传后平台自动研判,也可以手动重跑 -->
    <section class="gr-runbar" id="run-bar" aria-label="研判状态" hidden>
      <div>
        <p class="gr-run-data" id="run-data"></p>
        <p class="gr-run-state" id="run-state" role="status" aria-live="polite"></p>
        <p class="gr-run-msg" id="run-msg" aria-live="polite"></p>
      </div>
      <div class="gr-run-actions">
        <button type="button" class="gr-btn gr-btn-primary" id="run-apply" hidden>载入新结果</button>
        <button type="button" class="gr-btn" id="run-start">重新研判</button>
      </div>
    </section>

    <!-- 先读平台数据,成功后才显示内容 -->
    <section class="gr-card gr-state" id="load-state" aria-live="polite">
      <p id="load-message">正在读取平台数据…</p>
      <button type="button" class="gr-btn" id="load-retry" hidden>重新加载</button>
    </section>

    <section class="gr-banner" id="conflict-banner" role="alert" hidden>
      <div>
        <strong>跟进记录已在其他页面更新</strong>
        <p>为避免互相覆盖,本页已暂停保存,你刚改的内容还没保存。请重新加载最新数据后再改。</p>
      </div>
      <button type="button" class="gr-btn gr-btn-primary" id="conflict-reload">重新加载最新数据</button>
    </section>

    <div id="workspace" hidden>
      <section class="gr-stats" id="kpi" aria-label="本期概览"></section>

      <section class="gr-card" aria-labelledby="cand-title">
        <div class="gr-section-head">
          <div>
            <span class="gr-label">系统性原因候选</span>
            <h2 id="cand-title">按"该提前处理的程度"排序</h2>
          </div>
          <div class="gr-filters">
            <label>优先级
              <select id="f-band">
                <option value="">全部</option><option value="高">高</option><option value="中">中</option><option value="低">低</option>
              </select>
            </label>
            <label>状态
              <select id="f-status"><option value="">全部</option></select>
            </label>
            <label>层级
              <select id="f-level">
                <option value="">全部</option><option value="symptom">现象</option><option value="object">同一对象</option>
              </select>
            </label>
          </div>
        </div>
        <p class="gr-hint">"已解决"不等于问题消失:关单后同类仍在出现会单独标出;标成"已修复"后同类再出现,卡片会标"修复后复发"。</p>
        <div id="cand-list"></div>
        <p class="gr-empty" id="cand-empty" hidden>没有符合筛选条件的候选。</p>
      </section>

      <section class="gr-card" aria-labelledby="ref-title">
        <span class="gr-label">对标案例库</span>
        <h2 id="ref-title">已升级或已确认根因的案例</h2>
        <div id="ref-list"></div>
      </section>

      <section class="gr-card" aria-labelledby="ov-title">
        <span class="gr-label">投诉概览</span>
        <h2 id="ov-title">现象 × 来源部门</h2>
        <div class="gr-table-wrap" id="matrix"></div>
        <h3 class="gr-h3">按月投诉量</h3>
        <div class="gr-trend" id="trend"></div>
      </section>

      <section class="gr-card" aria-labelledby="method-title">
        <span class="gr-label">方法说明</span>
        <h2 id="method-title">这份结论怎么来的</h2>
        <div id="method"></div>
      </section>
    </div>
  </div>
</template>
