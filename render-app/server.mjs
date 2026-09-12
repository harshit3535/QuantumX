import express from 'express';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import OpenAI from 'openai';
import { WebSocketServer, WebSocket } from 'ws';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 10000);
const HOST = '0.0.0.0';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || '';
const ASSEMBLYAI_API_KEY = process.env.ASSEMBLYAI_API_KEY || '';
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-2.5-flash';
const OPENROUTER_MODEL = process.env.OPENROUTER_MODEL || 'openai/gpt-4o-mini';
const MAX_STEPS = Math.max(1, Math.min(20, Number(process.env.MAX_AGENT_STEPS || 8)));

const gemini = GEMINI_API_KEY ? new OpenAI({
  apiKey: GEMINI_API_KEY,
  baseURL: 'https://generativelanguage.googleapis.com/v1beta/openai/'
}) : null;

const openrouter = OPENROUTER_API_KEY ? new OpenAI({
  apiKey: OPENROUTER_API_KEY,
  baseURL: 'https://openrouter.ai/api/v1',
  defaultHeaders: {
    'HTTP-Referer': process.env.APP_URL || 'https://evo-ninja-render.onrender.com',
    'X-OpenRouter-Title': 'Evo Ninja Render v1'
  }
}) : null;

const app = express();
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'dist')));

app.get('/health', (_req, res) => {
  res.json({
    ok: true,
    version: '1.0.0',
    providers: {
      gemini: Boolean(gemini),
      openrouter: Boolean(openrouter),
      assemblyai: Boolean(ASSEMBLYAI_API_KEY)
    }
  });
});

app.get('/api/config', (_req, res) => {
  res.json({
    version: '1.0.0',
    maxSteps: MAX_STEPS,
    models: { gemini: GEMINI_MODEL, openrouter: OPENROUTER_MODEL },
    providers: {
      planner: 'Google Gemini',
      agents: 'OpenRouter',
      stt: 'AssemblyAI'
    }
  });
});

function textOf(message) {
  const content = message?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.filter(x => x?.type === 'text').map(x => x.text).join('\n');
  }
  return '';
}

async function callModel(client, model, messages, opts = {}) {
  if (!client) throw new Error(`Provider for model ${model} is not configured.`);
  const response = await client.chat.completions.create({
    model,
    messages,
    temperature: opts.temperature ?? 0.2,
    max_tokens: opts.max_tokens ?? 1200,
    response_format: opts.json ? { type: 'json_object' } : undefined
  });
  return textOf(response.choices?.[0]?.message) || '';
}

async function planStep(goal, history, previousAgent) {
  const system = `You are Evo Planner/Router. You are the control brain of a multi-agent assistant.\n` +
    `Your job is to decide the SINGLE best next step toward the user's goal.\n` +
    `Choose one agent from: researcher, developer, synthesizer, general.\n` +
    `Return STRICT JSON: {"status":"CONTINUE"|"SUCCESS","agent":"researcher"|"developer"|"synthesizer"|"general","task":"...","reason":"..."}.\n` +
    `Use SUCCESS only when the goal is actually satisfied by the accumulated work. Never declare success merely because a step completed.`;
  const prompt = JSON.stringify({ goal, previousAgent: previousAgent || null, history });
  const raw = await callModel(gemini, GEMINI_MODEL, [
    { role: 'system', content: system },
    { role: 'user', content: prompt }
  ], { json: true, temperature: 0 });
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.status) throw new Error('bad planner response');
    return parsed;
  } catch {
    return { status: 'CONTINUE', agent: previousAgent || 'general', task: 'Continue solving the goal using the available context.', reason: raw };
  }
}

const AGENT_PROMPTS = {
  researcher: `You are the Researcher agent. Find and reason from reliable information when the goal requires research. You may use public web pages through normal HTTP fetches available from your environment only when necessary. Produce concrete facts, links, calculations, or findings for the next agent. Do not invent sources.`,
  developer: `You are the Developer agent. Turn the current task into an implementable technical result. Inspect the supplied context, propose code/configuration/architecture, and be explicit about files, commands, APIs, and edge cases.`,
  synthesizer: `You are the Synthesizer agent. Combine previous agent outputs into a coherent result. Resolve conflicts, preserve useful details, and decide what is still missing before the user's goal can be considered complete.`,
  general: `You are a general execution agent. Complete the assigned task carefully using the goal and prior context. Ask yourself what concrete artifact or answer advances the goal most.`
};

async function runAgent(agent, task, goal, history) {
  const system = `${AGENT_PROMPTS[agent] || AGENT_PROMPTS.general}\n` +
    `The controller may send your output to another agent. Return a concise but information-dense result. Do not claim external actions were completed unless they actually were.`;
  return callModel(openrouter, OPENROUTER_MODEL, [
    { role: 'system', content: system },
    { role: 'user', content: JSON.stringify({ goal, task, context: history }) }
  ], { temperature: 0.2, max_tokens: 1600 });
}

async function verifyGoal(goal, history) {
  const system = `You are the Goal Verifier. Decide whether the user's goal is fully satisfied. Return STRICT JSON {"achieved":true|false,"reason":"...","final_answer":"..."}. The final_answer should be the best user-facing answer only if achieved.`;
  const raw = await callModel(gemini, GEMINI_MODEL, [
    { role: 'system', content: system },
    { role: 'user', content: JSON.stringify({ goal, history }) }
  ], { json: true, temperature: 0, max_tokens: 1400 });
  try { return JSON.parse(raw); } catch { return { achieved: false, reason: raw, final_answer: '' }; }
}

app.post('/api/goal', async (req, res) => {
  const goal = String(req.body?.goal || '').trim();
  if (!goal) return res.status(400).json({ error: 'goal is required' });
  if (!gemini || !openrouter) {
    return res.status(503).json({ error: 'Set GEMINI_API_KEY and OPENROUTER_API_KEY in Render environment variables.' });
  }

  const history = [{ role: 'user', content: goal }];
  const trace = [];
  let previousAgent = null;

  try {
    for (let step = 1; step <= MAX_STEPS; step += 1) {
      const plan = await planStep(goal, history, previousAgent);
      trace.push({ step, type: 'plan', ...plan });
      if (plan.status === 'SUCCESS') break;

      const agent = AGENT_PROMPTS[plan.agent] ? plan.agent : 'general';
      const output = await runAgent(agent, plan.task || 'Advance the goal.', goal, history);
      trace.push({ step, type: 'agent', agent, task: plan.task, output });
      history.push({ role: 'assistant', content: `[${agent}] ${output}` });
      previousAgent = agent;

      const verification = await verifyGoal(goal, history);
      trace.push({ step, type: 'verify', ...verification });
      if (verification.achieved) {
        return res.json({ ok: true, goal, completed: true, finalAnswer: verification.final_answer || output, trace });
      }
    }

    const fallback = await verifyGoal(goal, history);
    return res.json({ ok: true, goal, completed: Boolean(fallback.achieved), finalAnswer: fallback.final_answer || history.at(-1)?.content || '', trace });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || 'Goal execution failed', trace });
  }
});

// AssemblyAI v3 streaming proxy. Browser sends raw PCM16 mono audio chunks.
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws/stt' });

wss.on('connection', (browser, req) => {
  if (!ASSEMBLYAI_API_KEY) {
    browser.close(1011, 'ASSEMBLYAI_API_KEY is not configured');
    return;
  }

  const url = new URL(req.url, `http://${req.headers.host}`);
  const sampleRate = Math.max(8000, Math.min(48000, Number(url.searchParams.get('sample_rate') || 16000)));
  const assemblyUrl = `wss://streaming.assemblyai.com/v3/ws?sample_rate=${sampleRate}&format_turns=true`;
  const assembly = new WebSocket(assemblyUrl, { headers: { Authorization: ASSEMBLYAI_API_KEY } });

  assembly.on('open', () => {
    browser.send(JSON.stringify({ type: 'ready' }));
  });

  assembly.on('message', data => {
    browser.send(data.toString());
  });

  assembly.on('error', err => {
    console.error('AssemblyAI WS error', err);
    try { browser.send(JSON.stringify({ type: 'error', message: err.message })); } catch {}
  });

  browser.on('message', data => {
    if (assembly.readyState === WebSocket.OPEN) assembly.send(data);
  });

  const closeBoth = () => {
    try { if (assembly.readyState === WebSocket.OPEN) assembly.send(JSON.stringify({ type: 'Terminate' })); } catch {}
    try { assembly.close(); } catch {}
  };
  browser.on('close', closeBoth);
  assembly.on('close', () => { try { browser.close(); } catch {} });
});

app.get('*', (_req, res) => res.sendFile(path.join(__dirname, 'dist', 'index.html')));
server.listen(PORT, HOST, () => console.log(`Evo Ninja Render v1 listening on ${HOST}:${PORT}`));
