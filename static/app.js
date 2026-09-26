/* Astra web UI.
 * One brain (/api/chat/stream, SSE), two voice engines:
 *   mode "hackathon"  -> AssemblyAI streaming, voice-first
 *   mode "personal"   -> free API: text box + push-to-talk (Whisper) + optional hands-free wake word
 *
 * UI chrome text (state words, hints, sample prompts) is localized via i18n.js;
 * the orchestration detail panel (agent names, plan kind) stays in English on
 * purpose - that is what hackathon judges read.
 */
(function () {
  'use strict';

  const R = window.NXRender;
  const V = window.NXVoice;
  const I = window.NXi18n;
  const $ = (s) => document.querySelector(s);

  const S = {
    mode: 'hackathon', sessionId: null, state: 'idle', busy: false, health: null,
    assembly: null, ptt: null, wake: null, handsFree: false, wakeActive: false, sessionsCache: [],
    uiLang: 'en', hasMessages: false,
  };

  const store = {
    get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  const el = {
    feed: $('#feed'), live: $('#live'), hint: $('#hint'), stateWord: $('#stateWord'), mic: $('#mic'), micLabel: $('#micLabel'),
    handsFree: $('#handsFree'), silence: $('#silence'), message: $('#message'), send: $('#send'), composer: $('#composer'),
    lang: $('#lang'), speakPref: $('#speakPref'), missions: $('#missions'), health: $('#health'),
    rail: $('#rail'), orch: $('#orch'), scrim: $('#scrim'), chips: $('#chips'),
  };

  // ------------------------------------------------------------------- i18n
  function uiLang() { return el.lang.value !== 'auto' ? el.lang.value : S.uiLang; }
  function tr(key, ...args) { return I.t(uiLang(), key, ...args); }
  function noteResponseLanguage(lang) {
    if (el.lang.value === 'auto' && (lang === 'gu' || lang === 'hi')) S.uiLang = lang;
    else if (el.lang.value === 'auto' && lang === 'en') S.uiLang = 'en';
  }

  // ------------------------------------------------------------------ state
  function setState(state, hint) {
    S.state = state;
    document.body.dataset.state = state === 'transcribing' ? 'thinking' : state;
    const key = state === 'idle' ? 'ready' : (state === 'transcribing' ? 'transcribing' : state);
    el.stateWord.textContent = tr(key);
    el.silence.hidden = state !== 'speaking';
    if (hint !== undefined) setHint(hint);
    updateMic();
  }
  function setHint(text, warn) { el.hint.textContent = text || ''; el.hint.classList.toggle('warn', !!warn); }
  function setLevel(v) { document.documentElement.style.setProperty('--level', v.toFixed(3)); }
  function setLive(text, final) { el.live.textContent = text || ''; el.live.classList.toggle('final', !!final); }

  function updateMic() {
    const active = S.assembly && S.assembly.active || (S.ptt && S.ptt.active);
    const busy = S.state === 'thinking' || S.state === 'transcribing' || S.state === 'connecting';
    el.mic.disabled = busy && !active;
    el.micLabel.textContent = active ? tr('stopVoice') : (S.mode === 'hackathon' ? tr('startVoice') : tr('talk'));
    el.mic.setAttribute('aria-label', active ? 'Stop listening' : 'Start voice');
  }

  function language() { return el.lang.value; }
  function outputPref() { return el.speakPref.value; }

  // --------------------------------------------------------------- api helpers
  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let msg = 'Request failed (HTTP ' + res.status + ')';
      try { const j = await res.json(); msg = (j.error && j.error.message) || j.detail || msg; } catch (e) { /* */ }
      throw new Error(msg);
    }
    return res.json();
  }

  // --------------------------------------------------------------------- feed
  function typeset(node) {
    if (window.MathJax && window.MathJax.typesetPromise) window.MathJax.typesetPromise([node]).catch(() => {});
  }
  function scrollFeed() { el.feed.scrollTop = el.feed.scrollHeight; }

  function markHasMessages() {
    if (S.hasMessages) return;
    S.hasMessages = true;
    if (el.chips) el.chips.hidden = true;
  }

  function addUser(text, source) {
    markHasMessages();
    const d = document.createElement('div');
    d.className = 'msg user';
    d.textContent = text;
    if (source === 'voice') { const s = document.createElement('small'); s.textContent = 'voice'; d.appendChild(s); }
    el.feed.appendChild(d);
    scrollFeed();
  }

  function addAssistant(resp) {
    markHasMessages();
    const d = document.createElement('div');
    d.className = 'msg assistant';
    d.innerHTML = R.renderResponse(resp, { canRun: !!(S.health && S.health.code_execution) });
    el.feed.appendChild(d);
    typeset(d);
    scrollFeed();
    return d;
  }

  function addNotice(text) {
    addAssistant({ response_type: 'error', segments: [{ type: 'warning', content: text }] });
  }

  el.feed.addEventListener('click', async (e) => {
    const thinkHead = e.target.closest('.thinking-head');
    if (thinkHead) { thinkHead.parentElement.classList.toggle('is-open'); return; }
    const chip = e.target.closest('.sample-chip');
    if (chip) { handleUtterance(chip.dataset.prompt, 'text'); return; }
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const card = btn.closest('.code-card');
    const entry = R.codeStore[card.dataset.code];
    if (!entry) return;
    const act = btn.dataset.act;
    if (act === 'copy') {
      try { await navigator.clipboard.writeText(entry.content); }
      catch (err) {
        const ta = document.createElement('textarea'); ta.value = entry.content; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); } catch (e2) { /* */ } ta.remove();
      }
      btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
    } else if (act === 'save') {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([entry.content], { type: 'text/plain' }));
      a.download = R.fileName(entry);
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } else if (act === 'run') {
      btn.disabled = true; btn.textContent = 'Running…';
      let out = card.querySelector('.code-out');
      if (!out) { out = document.createElement('div'); out.className = 'code-out'; card.appendChild(out); }
      try {
        const r = await api('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: entry.content, language: entry.language }) });
        out.textContent = r.error || ((r.stdout || '') + (r.stderr ? '\n' + r.stderr : '')).trim() || '(no output)';
      } catch (err) { out.textContent = err.message; }
      btn.disabled = false; btn.textContent = 'Run';
    }
  });

  // -------------------------------------------------------------- sample chips
  function renderChips() {
    if (!el.chips || S.hasMessages) return;
    const list = I.DICT[uiLang()].chips;
    el.chips.innerHTML = '<p class="sample-chips-title">' + R.esc(tr('chipsTitle')) + '</p>' +
      '<div class="sample-chips">' + list.map((p) => '<button type="button" class="sample-chip" data-prompt="' + R.esc(p) + '">' + R.esc(p) + '</button>').join('') + '</div>';
    el.chips.hidden = false;
  }

  // ---------------------------------------------------- live "thinking" trace
  const AGENT_LABEL = { general_agent: 'thinking', math_agent: 'doing the math', code_agent: 'writing code', research_agent: 'recalling what it knows',
                       web_agent: 'searching the web', summarizer_agent: 'summarizing', verifier_agent: 'double-checking' };

  function thinkingLabel(agent) { return AGENT_LABEL[agent] || agent.replace(/_/g, ' '); }

  function createThinkingBlock() {
    const d = document.createElement('div');
    d.className = 'thinking is-live';
    d.innerHTML = '<div class="thinking-head"><span class="thinking-clock"></span><span class="th-label">' + R.esc(tr('thinkingLive')) + '</span><span class="chev">›</span></div><ol class="thinking-list"></ol>';
    el.feed.appendChild(d);
    scrollFeed();
    return { el: d, list: d.querySelector('.thinking-list'), label: d.querySelector('.th-label'), items: {}, start: performance.now(), stepCount: 0 };
  }

  function thinkingAddPlan(block, planEvent) {
    if (!planEvent.steps || !planEvent.steps.length) return;
    block.el.classList.add('is-open');
  }
  function thinkingStepStart(block, e) {
    block.el.classList.add('is-open');
    const li = document.createElement('li');
    li.className = 'live';
    li.textContent = 'Running ' + thinkingLabel(e.agent) + '…';
    block.list.appendChild(li);
    block.items[e.id + ':' + e.iteration] = li;
    block.stepCount++;
    scrollFeed();
  }
  function thinkingStepEnd(block, e) {
    const li = block.items[e.id + ':' + e.iteration];
    if (!li) return;
    li.className = e.status === 'error' ? 'err' : '';
    if (e.status === 'success') li.textContent = 'Finished ' + thinkingLabel(e.agent) + (e.attempts > 1 ? ' (fixed an issue)' : '');
    else if (e.status === 'skipped') li.textContent = 'Skipped ' + thinkingLabel(e.agent);
    else li.textContent = thinkingLabel(e.agent) + ' hit a problem' + (e.issue ? ': ' + e.issue : '');
  }
  function thinkingFinish(block) {
    const secs = Math.max(0, Math.round((performance.now() - block.start) / 100) / 10);
    block.el.classList.remove('is-live');
    block.label.textContent = block.stepCount ? tr('thinkingDone', block.stepCount, secs) : tr('thinkingNone');
    block.el.classList.remove('is-open');
  }

  // ------------------------------------------------------------- orchestration
  function renderOrch(d) {
    $('#orchEmpty').hidden = true;
    $('#orchBody').hidden = false;
    const n = d.normalized || {};
    const chips = [];
    chips.push([(n.language || '?') + (n.romanized ? ' · romanized' : ''), false]);
    chips.push([n.modality || 'text', false]);
    chips.push(['intent: ' + (n.intent || '?'), false]);
    chips.push(['plan: ' + d.plan.kind + ' · ' + d.plan.source, true]);
    if (d.iterations > 1) chips.push([d.iterations + ' rounds', true]);
    if (d.output.speak) chips.push(['spoken', true]);
    $('#orchChips').innerHTML = chips.map((c) => '<span class="chip' + (c[1] ? ' hot' : '') + '">' + R.esc(c[0]) + '</span>').join('');
    $('#orchGoal').textContent = d.plan.goal || '';
    const box = $('#orchSteps');
    if (!d.trace.length) {
      const why = d.response.response_type === 'clarification' ? 'No agent needed: asking a clarifying question.'
        : d.plan.direct_action ? 'No agent needed: reading from earlier work.' : 'No agent needed.';
      box.innerHTML = '<li class="step"><b>Brain only</b><small>' + R.esc(why) + '</small></li>';
    } else {
      const deps = {};
      (d.plan.steps || []).forEach((s) => { deps[s.id] = s.depends_on || []; });
      box.innerHTML = d.trace.map((t, i) => {
        const meta = ['<span>' + t.duration_ms + ' ms</span>'];
        if (t.attempts > 1) meta.push('<span>' + t.attempts + ' attempts</span>');
        if (deps[t.id] && deps[t.id].length) meta.push('<span class="dep">after ' + deps[t.id].join(', ') + '</span>');
        if (t.iteration > 1) meta.push('<span>round ' + t.iteration + '</span>');
        const detail = t.error ? t.error.message : (t.issues && t.issues.length ? 'fixed: ' + t.issues[0] : t.task);
        return '<li class="step ' + t.status + '" style="animation-delay:' + (i * 110) + 'ms"><b>' + R.esc(t.agent.replace(/_/g, ' ')) + '</b>' +
          '<small>' + R.esc(String(detail).slice(0, 140)) + '</small><div class="meta">' + meta.join('') + '</div></li>';
      }).join('');
    }
    $('#orchWhy').textContent = 'Output: ' + d.output.reason + '.';
  }

  // --------------------------------------------------------------------- chat
  async function ensureSession() {
    if (S.sessionId) return;
    const s = await api('/api/sessions', { method: 'POST' });
    S.sessionId = s.session_id;
    store.set('nexus.session', S.sessionId);
    await refreshMissions();
  }

  function parseSSE(buffer, onEvent) {
    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split('\n').find((l) => l.startsWith('data: '));
      if (line) { try { onEvent(JSON.parse(line.slice(6))); } catch (e) { /* ignore malformed frame */ } }
    }
    return buffer;
  }

  /** The one function every input path (typed, AssemblyAI, Whisper, wake word, sample chip) calls. */
  async function handleUtterance(text, source) {
    text = (text || '').trim();
    if (!text || S.busy) return;
    S.busy = true;
    if (S.assembly) S.assembly.pause();
    if (S.wake) S.wake.pause();
    addUser(text, source);
    setLive(source === 'voice' ? text : '', true);
    setState('thinking', '');
    $('#orchEmpty').hidden = false; $('#orchBody').hidden = true; $('#orchEmpty').textContent = 'Planning…';

    let block = null;
    let data = null;
    try {
      await ensureSession();
      const res = await fetch('/api/chat/stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: S.sessionId, message: text, source, language: language(), mode: S.mode, output: outputPref(),
          stt_provider: source === 'voice' ? (S.mode === 'hackathon' ? 'assemblyai' : (S.wakeUsed ? 'browser' : 'groq_whisper')) : null,
        }),
      });
      if (!res.ok || !res.body) throw new Error(await (async () => { try { const j = await res.json(); return (j.error && j.error.message) || 'Request failed'; } catch (e) { return 'Request failed (HTTP ' + res.status + ')'; } })());

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = parseSSE(buf + decoder.decode(value, { stream: true }), (evt) => {
          if (evt.type === 'plan') {
            if (!block) block = createThinkingBlock();
            thinkingAddPlan(block, evt);
          } else if (evt.type === 'step_start') {
            if (!block) block = createThinkingBlock();
            thinkingStepStart(block, evt);
          } else if (evt.type === 'step_end') {
            thinkingStepEnd(block, evt);
          } else if (evt.type === 'final') {
            data = evt.data;
          }
        });
      }
    } catch (e) {
      if (block) thinkingFinish(block);
      addNotice(e.message);
      $('#orchEmpty').textContent = 'The request failed before reaching the brain.';
      setState('error', e.message);
      finishTurn(false);
      return;
    }

    if (block) thinkingFinish(block);
    if (!data || data.error && !data.response) {
      addNotice((data && data.error && data.error.message) || 'No response received.');
      setState('error');
      finishTurn(false);
      return;
    }

    noteResponseLanguage((data.normalized || {}).language);
    addAssistant(data.response);
    renderOrch(data);
    refreshMissions();

    if (data.output.speak && data.output.speech_text) {
      setState('speaking', '');
      const r = await V.tts.speak(data.output.speech_text, data.output.speech_lang);
      if (!r.ok && r.reason === 'no-voice') {
        setHint('This device has no voice for ' + data.output.speech_lang + '. The answer is on screen; install that voice in your system settings to hear it.', true);
      } else if (!r.ok && r.reason === 'unsupported') {
        setHint('This browser cannot speak replies.', true);
      }
    }
    finishTurn(true);
  }

  function finishTurn(ok) {
    S.busy = false;
    if (S.assembly && S.assembly.active) { S.assembly.resume(); setState('listening', ''); setLive('', false); }
    else if (S.wake && S.wake.on) { S.wake.resume(); setState('idle', S.wakeActive ? tr('hintListening') : "Hands-free: say 'Astra' to talk"); }
    else setState(ok ? 'idle' : 'error', ok ? '' : undefined);
    if (!ok) setTimeout(() => { if (S.state === 'error') setState('idle'); }, 4000);
  }

  // -------------------------------------------------------------------- voice
  function fail(msg) {
    setState('error', msg);
    setHint(msg, true);
    setLevel(0);
    setTimeout(() => { if (S.state === 'error') setState('idle', S.mode === 'hackathon' ? '' : undefined); }, 5000);
  }

  async function toggleMic() {
    if (S.mode === 'hackathon') return toggleAssembly();
    return togglePushToTalk();
  }

  async function toggleAssembly() {
    if (S.assembly && S.assembly.active) { stopVoice(); setState('idle', tr('hintStopped')); return; }
    if (S.health && !S.health.assemblyai_configured) {
      fail('AssemblyAI is not configured on the server. Set ASSEMBLYAI_API_KEY, or switch to Free API mode to test.');
      return;
    }
    tts_stop();
    setState('connecting', '');
    S.assembly = new V.AssemblyVoice({
      getLanguage: language,
      onStatus: (t) => setHint(t),
      onPartial: (t) => setLive(t, false),
      onTurn: (t) => handleUtterance(t, 'voice'),
      onError: (m) => fail(m),
      onLevel: setLevel,
      onSpeechStart: () => { /* barge-in is off: audio is gated while the agent speaks to avoid echo */ },
    });
    try {
      await S.assembly.start();
      setState('listening', tr('hintListening'));
    } catch (e) { S.assembly = null; fail(e.message); }
  }

  async function togglePushToTalk() {
    if (S.ptt && S.ptt.active) { S.ptt.stop(); return; }
    if (S.health && !S.health.free_stt_configured) {
      fail('Free voice input needs GROQ_API_KEY on the server. Typing still works.');
      return;
    }
    if (!V.PushToTalk.supported()) { fail('Recording is not supported in this browser.'); return; }
    tts_stop();
    S.ptt = new V.PushToTalk({
      getLanguage: language,
      onStatus: (t) => setHint(t),
      onLevel: setLevel,
      onBusy: (b) => { if (b) setState('transcribing', tr('transcribing')); },
      onText: (t) => { S.wakeUsed = false; handleUtterance(t, 'voice'); },
      onError: (m) => { fail(m); },
    });
    try { await S.ptt.start(); setState('listening', tr('hintPTT')); updateMic(); }
    catch (e) { fail(e.message); }
  }

  function toggleHandsFree() {
    if (S.wake && S.wake.on) {
      S.wake.stop(); S.wake = null; S.wakeActive = false;
      el.handsFree.classList.remove('is-on'); setState('idle', tr('hintStopped'));
      return;
    }
    if (!V.WakeVoice.supported()) { fail('Hands-free needs browser speech recognition (Chrome/Edge). Use the Talk button instead.'); return; }
    S.wake = new V.WakeVoice({
      getLanguage: language,
      onStatus: (t) => setHint(t),
      onActive: (a) => { S.wakeActive = a; setState(a ? 'listening' : 'idle', a ? 'Listening. Say "stop" when you are done.' : "Hands-free: say 'Astra' to talk"); },
      onText: (t) => { S.wakeUsed = true; handleUtterance(t, 'voice'); },
      onError: (m) => { fail(m); el.handsFree.classList.remove('is-on'); S.wake = null; },
    });
    try { S.wake.start(); el.handsFree.classList.add('is-on'); setState('idle', "Hands-free on: say 'Astra' to talk, 'stop' to end."); }
    catch (e) { S.wake = null; fail(e.message); }
  }

  function tts_stop() { V.tts.cancel(); }

  function stopVoice() {
    if (S.assembly) { S.assembly.stop(); S.assembly = null; }
    if (S.ptt) { S.ptt.stop(); S.ptt = null; }
    if (S.wake) { S.wake.stop(); S.wake = null; el.handsFree.classList.remove('is-on'); }
    setLevel(0); setLive('', false); tts_stop();
  }

  // ------------------------------------------------------------------- modes
  function applyMode(mode, persist) {
    if (S.mode !== mode || persist === 'force') stopVoice();
    S.mode = mode;
    document.body.dataset.mode = mode;
    document.querySelectorAll('.seg-btn').forEach((b) => {
      const on = b.dataset.mode === mode;
      b.classList.toggle('is-on', on); b.setAttribute('aria-selected', String(on));
    });
    el.handsFree.hidden = !(mode === 'personal' && V.WakeVoice.supported());
    S.busy = false;
    setState('idle', '');
    setLive('', false);
    if (persist !== false) store.set('nexus.mode', mode);
    const h = S.health;
    if (mode === 'hackathon') {
      if (h && !h.assemblyai_configured) setHint(tr('hintHackathonNoKey'), true);
      else setHint(tr('hintHackathonReady'));
    } else {
      setHint(h && h.llm_configured ? tr('hintPersonalReady') : tr('hintPersonalNoKey'), !!(h && !h.llm_configured));
    }
    renderChips();
  }

  document.querySelectorAll('.seg-btn').forEach((b) => b.addEventListener('click', () => applyMode(b.dataset.mode)));
  el.mic.addEventListener('click', toggleMic);
  el.handsFree.addEventListener('click', toggleHandsFree);
  el.silence.addEventListener('click', () => { tts_stop(); });
  function refreshChromeText() {
    setState(S.state);
    if (S.state === 'idle') {
      const h = S.health;
      if (S.mode === 'hackathon') setHint(h && !h.assemblyai_configured ? tr('hintHackathonNoKey') : tr('hintHackathonReady'), !!(h && !h.assemblyai_configured));
      else setHint(h && h.llm_configured ? tr('hintPersonalReady') : tr('hintPersonalNoKey'), !!(h && !h.llm_configured));
    }
  }

  el.lang.addEventListener('change', () => {
    store.set('nexus.lang', el.lang.value);
    if (S.assembly || S.wake) { stopVoice(); setState('idle', 'Language changed - start again.'); }
    else { refreshChromeText(); }
    renderChips();
  });
  el.speakPref.addEventListener('change', () => store.set('nexus.speak', el.speakPref.value));

  el.composer.addEventListener('submit', (e) => {
    e.preventDefault();
    const t = el.message.value;
    if (!t.trim()) return;
    el.message.value = ''; autoGrow();
    tts_stop();
    handleUtterance(t, 'text');
  });
  el.message.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); el.composer.requestSubmit(); }
  });
  function autoGrow() { el.message.style.height = 'auto'; el.message.style.height = Math.min(el.message.scrollHeight, 190) + 'px'; }
  el.message.addEventListener('input', autoGrow);

  // ------------------------------------------------------------- missions list
  async function refreshMissions() {
    try {
      const d = await api('/api/sessions');
      S.sessionsCache = d.sessions;
      el.missions.innerHTML = '';
      d.sessions.forEach((s) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'mission' + (s.id === S.sessionId ? ' is-active' : '');
        const t = document.createElement('span'); t.textContent = s.title;
        const x = document.createElement('span'); x.className = 'x'; x.textContent = '✕'; x.title = 'Delete';
        b.append(t, x);
        b.addEventListener('click', (ev) => { if (ev.target === x) { deleteMission(s.id); } else { loadMission(s.id); closeDrawers(); } });
        el.missions.appendChild(b);
      });
    } catch (e) { /* offline: ignore */ }
  }

  async function newMission() {
    stopVoice();
    const s = await api('/api/sessions', { method: 'POST' });
    S.sessionId = s.session_id; store.set('nexus.session', S.sessionId);
    el.feed.innerHTML = ''; S.hasMessages = false; setLive('', false);
    $('#orchEmpty').hidden = false; $('#orchBody').hidden = true; $('#orchEmpty').textContent = 'Ask something. The plan and every agent step appear here.';
    if (el.chips) { el.feed.appendChild(el.chips); }
    renderChips();
    await refreshMissions();
    closeDrawers();
  }

  async function loadMission(id) {
    stopVoice();
    S.sessionId = id; store.set('nexus.session', id);
    el.feed.innerHTML = ''; S.hasMessages = false;
    if (el.chips) el.feed.appendChild(el.chips);
    try {
      const d = await api('/api/sessions/' + encodeURIComponent(id) + '/history');
      d.messages.forEach((m) => {
        if (m.role === 'user') addUser(m.content, m.source);
        else if (m.metadata && m.metadata.response) addAssistant(m.metadata.response);
        else addAssistant({ response_type: 'text', segments: [{ type: 'text', content: m.content }] });
      });
      if (!d.messages.length) renderChips();
    } catch (e) { S.sessionId = null; renderChips(); }
    refreshMissions();
  }

  async function deleteMission(id) {
    await api('/api/sessions/' + encodeURIComponent(id), { method: 'DELETE' }).catch(() => {});
    if (id === S.sessionId) { S.sessionId = null; el.feed.innerHTML = ''; S.hasMessages = false; if (el.chips) el.feed.appendChild(el.chips); renderChips(); }
    refreshMissions();
  }
  $('#newMission').addEventListener('click', newMission);

  // ----------------------------------------------------------------- drawers
  function closeDrawers() { el.rail.classList.remove('is-open'); el.orch.classList.remove('is-open'); el.scrim.hidden = true; }
  $('#menuBtn').addEventListener('click', () => { el.rail.classList.add('is-open'); el.scrim.hidden = false; });
  $('#orchBtn').addEventListener('click', () => { el.orch.classList.add('is-open'); el.scrim.hidden = false; });
  el.scrim.addEventListener('click', closeDrawers);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeDrawers(); tts_stop(); } });

  // -------------------------------------------------------------------- boot
  function healthRow(ok, label) { return '<div><span class="dot ' + (ok ? 'ok' : 'warn') + '"></span>' + R.esc(label) + '</div>'; }

  async function boot() {
    const q = new URLSearchParams(location.search);
    if (q.get('app') === '1') document.body.classList.add('in-app');      // compact layout inside the Android WebView
    el.lang.value = store.get('nexus.lang', 'auto');
    el.speakPref.value = store.get('nexus.speak', 'auto');
    V.tts.load();

    try { S.health = await api('/api/health'); } catch (e) { S.health = null; }
    const h = S.health;
    el.health.innerHTML = h
      ? healthRow(h.assemblyai_configured, 'AssemblyAI voice') + healthRow(h.llm_configured, 'AI: ' + (h.llm_providers.filter((p) => p.configured).map((p) => p.name).join(', ') || 'none configured')) + healthRow(h.free_stt_configured, 'Free voice input')
      : healthRow(false, 'Server unreachable');

    applyMode(q.get('mode') === 'personal' || q.get('mode') === 'hackathon' ? q.get('mode') : store.get('nexus.mode', 'hackathon'), false);

    await refreshMissions();
    const last = store.get('nexus.session', '');
    if (last && S.sessionsCache.some((s) => s.id === last)) await loadMission(last);
    else if (S.sessionsCache.length === 0) { await ensureSession().catch(() => {}); renderChips(); }
    else renderChips();
    window.addEventListener('load', () => typeset(el.feed));
  }

  window.addEventListener('beforeunload', stopVoice);
  boot();
})();
