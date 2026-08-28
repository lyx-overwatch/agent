// Heyu Agent U2 mock 流式传输层。
// 按时间轴 emit StreamEvent，模拟 POST /py/api/chat/stream 的 SSE 序列。
// U3 阶段由真实 SSE 解析器替换 startMockStream 的实现，调用方（chatReducer 侧）接口不变。

import type { StreamEvent } from '../types';

export interface ChatStreamOptions {
  text: string;
  thinkingEnabled: boolean;
  modelName?: string;
}

export interface ChatStreamHandle {
  /** 模拟停止生成：取消后续事件并下发 run_end(cancelled) */
  stop: () => void;
}

interface ScenarioStep {
  /** 距上一步的毫秒 */
  delay: number;
  event: StreamEvent;
}

interface Scenario {
  match: (text: string) => boolean;
  steps: ScenarioStep[];
}

/** 按 2 字切分文本，模拟打字机增量 */
function tokenSteps(text: string, delay = 45): ScenarioStep[] {
  const out: ScenarioStep[] = [];
  for (let i = 0; i < text.length; i += 2) {
    out.push({ delay, event: { type: 'token', content: text.slice(i, i + 2) } });
  }
  return out;
}

/** 按 3 字切分，模拟深度思考增量 */
function reasoningSteps(text: string, delay = 200): ScenarioStep[] {
  const out: ScenarioStep[] = [];
  for (let i = 0; i < text.length; i += 3) {
    out.push({ delay, event: { type: 'reasoning', content: text.slice(i, i + 3) } });
  }
  return out;
}

/** 去掉祈使前缀/句末标点，得到更接近真实标题的 AI 标题 */
function polishTitle(t: string): string {
  let s = t.trim().replace(/[。！？!?…]+$/, '');
  s = s.replace(/^(请|麻烦|麻烦你|帮我|请帮我|我想|我想要|我要)/, '');
  if (!s) s = t.trim();
  return s.length > 20 ? `${s.slice(0, 20)}…` : s;
}

// ── 场景 1：正常完成（思考 → 文本 → 工具 → 文本 → 完成）──────────────────────
const NORMAL: Scenario = {
  match: () => true,
  steps: [
    { delay: 120, event: { type: 'run_start' } },
    { delay: 180, event: { type: 'thinking_start' } },
    ...reasoningSteps('我先梳理你的需求，规划执行步骤，再调用工具读取数据、聚合并生成结果。'),
    { delay: 200, event: { type: 'thinking_end' } },
    ...tokenSteps('好的，我先读取文件看一下数据结构。\n\n'),
    {
      delay: 200,
      event: {
        type: 'tool_start',
        tool: 'read_file',
        name: '读取文件',
        icon: 'file-text',
        input: '{"path": "/mnt/user-data/uploads/data.csv", "start_line": 1, "end_line": 20}',
        run_id: 'r1',
      },
    },
    {
      delay: 800,
      event: {
        type: 'tool_end',
        tool: 'read_file',
        output: '日期,区域,销售额,订单数\n2026-01-01,华东,120000,340\n…共 3200 行',
        run_id: 'r1',
      },
    },
    ...tokenSteps('数据共 3200 行，我用 bash 做季度聚合。\n\n'),
    {
      delay: 200,
      event: {
        type: 'tool_start',
        tool: 'bash',
        name: '执行 Bash',
        icon: 'terminal',
        input: '{"command": "python /mnt/user-data/workspace/aggregate.py"}',
        run_id: 'r2',
      },
    },
    { delay: 300, event: { type: 'progress', phase: 'tool', run_id: 'r2' } },
    {
      delay: 900,
      event: {
        type: 'tool_end',
        tool: 'bash',
        output: '季度聚合完成，已生成 quarterly_summary.csv。',
        run_id: 'r2',
      },
    },
    ...tokenSteps('聚合完成，季度销售趋势报告已生成，你可以在右侧文件树中查看和下载。'),
    { delay: 120, event: { type: 'run_end', finish_reason: 'stop' } },
    { delay: 40, event: { type: '[DONE]' } },
  ],
};

// ── 场景 2：中途报错（工具出错 + error 事件 + run_end(error)）─────────────────
const ERROR: Scenario = {
  match: (t) => /报错|失败|错误|error|异常/i.test(t),
  steps: [
    { delay: 120, event: { type: 'run_start' } },
    ...tokenSteps('我来尝试处理这个任务。\n\n'),
    {
      delay: 200,
      event: {
        type: 'tool_start',
        tool: 'bash',
        name: '执行 Bash',
        icon: 'terminal',
        input: '{"command": "python heavy.py"}',
        run_id: 'r1',
      },
    },
    {
      delay: 800,
      event: {
        type: 'tool_end',
        tool: 'bash',
        output: '',
        error: '内存不足，进程被终止。',
        run_id: 'r1',
      },
    },
    { delay: 120, event: { type: 'error', message: '服务端内部错误，请重试。' } },
    { delay: 80, event: { type: 'run_end', finish_reason: 'error' } },
    { delay: 40, event: { type: '[DONE]' } },
  ],
};

// ── 场景 3：子代理委派（task 变体 + subagent_progress 耗时）───────────────────
const SUBAGENT: Scenario = {
  match: (t) => /子代理|委派|任务|task|清洗|聚合/i.test(t),
  steps: [
    { delay: 120, event: { type: 'run_start' } },
    ...tokenSteps('这个任务步骤较多，我委派一个子代理来处理。\n\n'),
    {
      delay: 200,
      event: {
        type: 'tool_start',
        tool: 'task',
        name: '委派子代理：数据清洗与季度聚合',
        icon: 'bot',
        input: '{"description": "数据清洗与季度聚合", "subagent_type": "data-engineering"}',
        run_id: 'r1',
        is_subagent: true,
        description: '数据清洗与季度聚合',
      },
    },
    { delay: 500, event: { type: 'subagent_progress', run_id: 'r1', elapsed_seconds: 12 } },
    { delay: 600, event: { type: 'subagent_progress', run_id: 'r1', elapsed_seconds: 45 } },
    { delay: 700, event: { type: 'subagent_progress', run_id: 'r1', elapsed_seconds: 98 } },
    {
      delay: 600,
      event: {
        type: 'tool_end',
        tool: 'task',
        output: '已按季度聚合完成，共 4 个季度分组，无缺失值。',
        run_id: 'r1',
        is_subagent: true,
        elapsed_seconds: 130,
      },
    },
    ...tokenSteps('子代理已完成清洗与季度聚合，结果如下。'),
    { delay: 120, event: { type: 'run_end', finish_reason: 'stop' } },
    { delay: 40, event: { type: '[DONE]' } },
  ],
};

// 匹配顺序：特定场景在前，默认场景兜底
const SCENARIOS: Scenario[] = [ERROR, SUBAGENT, NORMAL];

function pickScenario(text: string): Scenario {
  return SCENARIOS.find((s) => s.match(text)) ?? NORMAL;
}

export function startMockStream(
  opts: ChatStreamOptions,
  onEvent: (e: StreamEvent) => void,
): ChatStreamHandle {
  const scenario = pickScenario(opts.text);
  const timers: ReturnType<typeof setTimeout>[] = [];
  let stopped = false;
  let done = false;

  let acc = 0;
  for (const step of scenario.steps) {
    acc += step.delay;
    timers.push(
      setTimeout(() => {
        if (!stopped && !done) onEvent(step.event);
      }, acc),
    );
  }

  // 标题替换（best-effort，首个回复后、回合结束前下发）
  timers.push(
    setTimeout(() => {
      if (!stopped && !done) onEvent({ type: 'title_update', title: polishTitle(opts.text) });
    }, Math.min(1500, acc)),
  );

  // 完成标记：自然结束后 stop() 不再生效
  timers.push(
    setTimeout(() => {
      done = true;
    }, acc + 20),
  );

  return {
    stop() {
      if (stopped || done) return;
      stopped = true;
      timers.forEach(clearTimeout);
      onEvent({ type: 'run_end', finish_reason: 'cancelled' });
    },
  };
}
