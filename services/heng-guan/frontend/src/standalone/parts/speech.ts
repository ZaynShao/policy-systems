// 独立版演示用的"语音识别"替身:离线页面不录音、不连浏览器的在线语音服务。
// 我的拜访录入弹窗(MobileVisitInputModal.vue)只在浏览器有语音识别时才让点「开始说话」,
// 解析也只走「开始说话 → 停止并识别」这一条路。这里换上一个假的识别器:
// - 框里已经手打了文字:什么也不"听",点「停止并识别」就把手打的文字交给解析接口;
// - 框是空的:把选中的样例口述(后端测试里那两段)当作识别结果,一小段一小段地打出来。
import { ref } from 'vue';

export const demoScript = ref<string>('');

type ResultEvent = { resultIndex: number; results: Array<{ 0: { transcript: string }; isFinal: boolean }> };

class DemoSpeechRecognition {
  lang = 'zh-CN';
  continuous = false;
  interimResults = false;
  onresult: ((e: ResultEvent) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  private timers: ReturnType<typeof setTimeout>[] = [];

  start() {
    const typed = (document.querySelector('.mi-transcript') as HTMLTextAreaElement | null)?.value.trim();
    const text = typed ? '' : demoScript.value;
    if (!text) return;
    const step = Math.max(2, Math.ceil(text.length / 8));
    let said = 0;
    const tick = () => {
      said = Math.min(text.length, said + step);
      const isFinal = said >= text.length;
      this.onresult?.({ resultIndex: 0, results: [{ 0: { transcript: text.slice(0, said) }, isFinal }] });
      if (!isFinal) this.timers.push(setTimeout(tick, 120));
    };
    this.timers.push(setTimeout(tick, 250));
  }

  stop() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
    this.onend?.();
  }

  abort() {
    this.stop();
  }
}

export function installDemoSpeech() {
  for (const name of ['webkitSpeechRecognition', 'SpeechRecognition']) {
    Object.defineProperty(window, name, { value: DemoSpeechRecognition, configurable: true, writable: true });
  }
}
