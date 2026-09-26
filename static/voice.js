/* Voice adapters. They only turn speech into text and text into speech.
 * They know nothing about the brain: app.js connects them to /api/chat.
 *
 *   AssemblyVoice  hackathon mode - real-time streaming STT via AssemblyAI (temporary token)
 *   PushToTalk     personal mode  - records, server transcribes with free Whisper (/api/stt)
 *   WakeVoice      personal mode  - hands-free wake word using the browser's SpeechRecognition
 *   tts            spoken replies via the browser's speechSynthesis (swap-able)
 */
(function (root) {
  'use strict';

  const TARGET_RATE = 16000;

  async function apiError(res, fallback) {
    try {
      const j = await res.json();
      if (j && j.error && j.error.message) return j.error.message;
      if (j && j.detail) return String(j.detail);
    } catch (e) { /* ignore */ }
    return fallback + ' (HTTP ' + res.status + ')';
  }

  function micError(err) {
    const n = err && err.name;
    if (n === 'NotAllowedError' || n === 'SecurityError') return 'Microphone permission was denied. Allow it in the browser/app settings and try again.';
    if (n === 'NotFoundError') return 'No microphone found on this device.';
    if (n === 'NotReadableError') return 'The microphone is busy in another app.';
    return 'Could not open the microphone: ' + ((err && err.message) || n || 'unknown error');
  }

  // ------------------------------------------------------------------ level meter
  function makeMeter(ctx, source, onLevel) {
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    let raf = 0, alive = true;
    (function tick() {
      if (!alive) return;
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      onLevel(Math.min(1, rms * 6));
      raf = requestAnimationFrame(tick);
    })();
    return { stop() { alive = false; cancelAnimationFrame(raf); try { analyser.disconnect(); } catch (e) { /* */ } } };
  }

  function downsample(input, inRate) {
    if (inRate === TARGET_RATE) return input;
    const ratio = inRate / TARGET_RATE;
    const out = new Float32Array(Math.floor(input.length / ratio));
    for (let i = 0, pos = 0; i < out.length; i++) {
      const next = Math.floor((i + 1) * ratio);
      let sum = 0, n = 0;
      for (; pos < next && pos < input.length; pos++) { sum += input[pos]; n++; }
      out[i] = n ? sum / n : 0;
    }
    return out;
  }

  function toInt16(f32) {
    const out = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  // ------------------------------------------------------------------ AssemblyAI
  class AssemblyVoice {
    /** cb: { getLanguage, onStatus(text), onPartial(text), onTurn(text), onError(msg), onLevel(n), onSpeechStart() } */
    constructor(cb) {
      this.cb = cb;
      this.ws = null; this.stream = null; this.ctx = null; this.proc = null; this.meter = null;
      this.sending = false; this.active = false; this.turns = new Set(); this.needsFormatted = false;
      this.reconnecting = false;
    }

    async start() {
      if (this.active) return;
      const lang = this.cb.getLanguage() === 'auto' ? 'en' : this.cb.getLanguage();
      this.cb.onStatus('Opening microphone…');
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      } catch (e) { this.cleanup(); throw new Error(micError(e)); }

      try {
        await this.openSocket(lang);
      } catch (e) { this.cleanup(); throw e; }

      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      if (this.ctx.state === 'suspended') await this.ctx.resume();
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.meter = makeMeter(this.ctx, src, this.cb.onLevel);
      // ScriptProcessor is deprecated but works in every browser and in Android WebView.
      this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
      const inRate = this.ctx.sampleRate;
      this.proc.onaudioprocess = (e) => {
        if (!this.sending || !this.ws || this.ws.readyState !== 1) return;
        const pcm = toInt16(downsample(e.inputBuffer.getChannelData(0), inRate));
        if (pcm.length) this.ws.send(pcm.buffer);
      };
      const mute = this.ctx.createGain();
      mute.gain.value = 0;
      src.connect(this.proc); this.proc.connect(mute); mute.connect(this.ctx.destination);
      this.active = true;
      this.sending = true;
    }

    async openSocket(lang) {
      const res = await fetch('/api/assemblyai/token?language=' + encodeURIComponent(lang));
      if (!res.ok) throw new Error(await apiError(res, 'Could not get an AssemblyAI token'));
      const t = await res.json();
      const q = new URLSearchParams(Object.assign({}, t.params, { token: t.token }));
      this.needsFormatted = String(t.params.format_turns) === 'true';
      this.turns.clear();
      await new Promise((resolve, reject) => {
        const ws = new WebSocket(t.ws_url + '?' + q.toString());
        ws.binaryType = 'arraybuffer';
        let opened = false;
        ws.onopen = () => { opened = true; };
        ws.onmessage = (ev) => {
          let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
          if (m.type === 'Begin') { this.ws = ws; this.cb.onStatus('Connected to AssemblyAI'); resolve(); }
          else this.onMessage(m);
        };
        ws.onerror = () => { if (!opened) reject(new Error('Could not connect to AssemblyAI. Check your network and API key.')); };
        ws.onclose = (ev) => {
          if (!opened || !this.ws) { reject(new Error('AssemblyAI closed the connection' + (ev.reason ? ': ' + ev.reason : '') + '.')); return; }
          if (this.ws === ws) { this.ws = null; if (this.active) this.cb.onStatus('AssemblyAI session ended - reconnecting on next turn'); }
        };
        setTimeout(() => { if (!this.ws) reject(new Error('AssemblyAI did not answer in time.')); }, 10000);
      });
    }

    onMessage(m) {
      if (m.type === 'SpeechStarted') { if (this.cb.onSpeechStart) this.cb.onSpeechStart(); return; }
      if (m.type !== 'Turn') return;
      const text = (m.transcript || '').trim();
      if (!m.end_of_turn) { if (text) this.cb.onPartial(text); return; }
      // universal-streaming models send an unformatted then a formatted end_of_turn; wait for the formatted one
      if (this.needsFormatted && m.turn_is_formatted === false) { if (text) this.cb.onPartial(text); return; }
      const key = m.turn_order;
      if (key != null) { if (this.turns.has(key)) return; this.turns.add(key); }
      if (text) this.cb.onTurn(text);
    }

    pause() { this.sending = false; }
    async resume() {
      if (!this.active) return;
      if (!this.ws) {                                   // session expired while we were busy: new one-time token
        try { const l = this.cb.getLanguage(); await this.openSocket(l === 'auto' ? 'en' : l); }
        catch (e) { this.cb.onError(e.message); return; }
      }
      this.sending = true;
    }

    cleanup() {
      this.sending = false; this.active = false;
      if (this.meter) this.meter.stop();
      if (this.proc) { try { this.proc.disconnect(); } catch (e) { /* */ } this.proc.onaudioprocess = null; }
      if (this.ctx) { try { this.ctx.close(); } catch (e) { /* */ } }
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
      this.proc = this.ctx = this.stream = this.meter = null;
      this.cb.onLevel(0);
    }

    stop() {
      const ws = this.ws; this.ws = null;
      if (ws) { try { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'Terminate' })); ws.close(); } catch (e) { /* */ } }
      this.cleanup();
    }
  }

  // ------------------------------------------------------------------ push to talk
  class PushToTalk {
    /** cb: { getLanguage, onStatus, onLevel, onText(text), onError(msg), onBusy(bool) } */
    constructor(cb) { this.cb = cb; this.rec = null; this.stream = null; this.ctx = null; this.meter = null; this.chunks = []; this.timer = 0; this.active = false; }

    static supported() { return !!(navigator.mediaDevices && window.MediaRecorder); }

    async start() {
      if (this.active) return;
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      } catch (e) { throw new Error(micError(e)); }
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find((t) => MediaRecorder.isTypeSupported(t)) || '';
      this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
      this.mime = this.rec.mimeType || mime || 'audio/webm';
      this.chunks = [];
      this.rec.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
      this.rec.onstop = () => this.finish();

      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      const src = this.ctx.createMediaStreamSource(this.stream);
      let heard = false, lastVoice = performance.now();
      const startedAt = performance.now();
      this.meter = makeMeter(this.ctx, src, (lvl) => {
        this.cb.onLevel(lvl);
        const now = performance.now();
        if (lvl > 0.08) { heard = true; lastVoice = now; }
        if (heard && now - lastVoice > 1300) this.stop();               // finished talking
        else if (!heard && now - startedAt > 9000) this.stop();          // nothing said
      });
      this.rec.start();
      this.active = true;
      this.timer = setTimeout(() => this.stop(), 30000);                 // hard cap
      this.cb.onStatus('Listening… stop talking to send');
    }

    stop() {
      if (!this.active) return;
      this.active = false;
      clearTimeout(this.timer);
      if (this.meter) this.meter.stop();
      this.cb.onLevel(0);
      try { if (this.rec && this.rec.state !== 'inactive') this.rec.stop(); } catch (e) { /* */ }
    }

    async finish() {
      const blob = new Blob(this.chunks, { type: this.mime });
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
      if (this.ctx) { try { this.ctx.close(); } catch (e) { /* */ } }
      this.stream = this.ctx = this.meter = this.rec = null;
      if (blob.size < 1500) { this.cb.onError('I did not hear anything. Tap the mic and try again.'); return; }
      this.cb.onBusy(true);
      try {
        const fd = new FormData();
        const ext = this.mime.includes('mp4') ? 'm4a' : this.mime.includes('ogg') ? 'ogg' : 'webm';
        fd.append('audio', blob, 'speech.' + ext);
        fd.append('language', this.cb.getLanguage());
        const res = await fetch('/api/stt', { method: 'POST', body: fd });
        if (!res.ok) throw new Error(await apiError(res, 'Speech-to-text failed'));
        const j = await res.json();
        if (!j.text) throw new Error('I could not make out any words. Try again a little closer to the mic.');
        this.cb.onText(j.text);
      } catch (e) { this.cb.onError(e.message); }
      finally { this.cb.onBusy(false); }
    }
  }

  // ------------------------------------------------------------------ wake word
  const WAKE = ['astra', 'hey astra', 'ok astra', 'अस्त्र', 'अस्त्रा', 'આસ્ટ્રા', 'એસ્ટ્રા'];
  const STOP = ['stop', 'cancel', 'goodbye', 'બંધ', 'બસ', 'रुको', 'बंद', 'बस'];

  class WakeVoice {
    /** cb: { getLanguage, onStatus, onText(text), onActive(bool), onError(msg) } */
    constructor(cb) { this.cb = cb; this.rec = null; this.on = false; this.active = false; this.paused = false; this.idleTimer = 0; }

    static supported() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); }

    start() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) throw new Error('This browser has no built-in speech recognition. Use the mic button instead.');
      this.on = true;
      const rec = new SR();
      const l = this.cb.getLanguage();
      rec.lang = l === 'gu' ? 'gu-IN' : l === 'hi' ? 'hi-IN' : 'en-IN';
      rec.continuous = true; rec.interimResults = false;
      rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) this.handle(e.results[i][0].transcript.trim());
      };
      rec.onerror = (e) => {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { this.on = false; this.cb.onError('Microphone permission was denied.'); }
      };
      rec.onend = () => { if (this.on && !this.paused) { try { rec.start(); } catch (err) { /* already started */ } } };
      this.rec = rec;
      try { rec.start(); } catch (err) { /* */ }
      this.cb.onStatus("Hands-free on - say 'Nexus' to talk, 'stop' to end");
    }

    handle(text) {
      if (!text) return;
      const low = text.toLowerCase();
      if (this.active && STOP.some((w) => low === w || low.startsWith(w + ' ') || low.endsWith(' ' + w))) { this.setActive(false); return; }
      if (!this.active) {
        const w = WAKE.find((k) => low.includes(k));
        if (!w) return;
        this.setActive(true);
        const rest = text.slice(low.indexOf(w) + w.length).replace(/^[\s,.:;-]+/, '');
        if (rest) this.emit(rest);
        return;
      }
      this.emit(text);
    }

    emit(text) { this.armIdle(); this.cb.onText(text); }
    setActive(v) { this.active = v; clearTimeout(this.idleTimer); if (v) this.armIdle(); this.cb.onActive(v); }
    armIdle() { clearTimeout(this.idleTimer); this.idleTimer = setTimeout(() => this.setActive(false), 25000); }

    pause() { this.paused = true; try { this.rec && this.rec.abort(); } catch (e) { /* */ } }
    resume() { this.paused = false; if (this.on && this.rec) { try { this.rec.start(); } catch (e) { /* */ } } }
    stop() { this.on = false; this.active = false; clearTimeout(this.idleTimer); try { this.rec && this.rec.abort(); } catch (e) { /* */ } this.rec = null; }
  }

  // ------------------------------------------------------------------ text to speech
  const tts = {
    _voices: [],
    _token: 0,
    speaking: false,

    load() {
      if (!('speechSynthesis' in window)) return;
      const grab = () => { tts._voices = speechSynthesis.getVoices() || []; };
      grab();
      speechSynthesis.addEventListener && speechSynthesis.addEventListener('voiceschanged', grab);
    },

    voiceFor(lang) {
      const prefix = lang.split('-')[0].toLowerCase();
      const exact = tts._voices.find((v) => v.lang.toLowerCase().replace('_', '-') === lang.toLowerCase());
      return exact || tts._voices.find((v) => v.lang.toLowerCase().startsWith(prefix)) || null;
    },

    chunks(text) {
      const parts = text.match(/[^.!?।]+[.!?।]*\s*/g) || [text];
      const out = [];
      let cur = '';
      parts.forEach((p) => { if ((cur + p).length > 180 && cur) { out.push(cur.trim()); cur = p; } else cur += p; });
      if (cur.trim()) out.push(cur.trim());
      return out;
    },

    /** resolves {ok, reason}. reason 'no-voice' means the device has no voice for that language. */
    speak(text, lang) {
      return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) { resolve({ ok: false, reason: 'unsupported' }); return; }
        tts.cancel();
        const voice = tts.voiceFor(lang);
        if (!voice && lang !== 'en-US' && tts._voices.length) { resolve({ ok: false, reason: 'no-voice' }); return; }
        const my = ++tts._token;
        const queue = tts.chunks(text);
        tts.speaking = true;
        const next = () => {
          if (my !== tts._token) { resolve({ ok: true, cancelled: true }); return; }
          const piece = queue.shift();
          if (!piece) { tts.speaking = false; resolve({ ok: true }); return; }
          const u = new SpeechSynthesisUtterance(piece);
          u.lang = lang; if (voice) u.voice = voice; u.rate = 1;
          let done = false;
          const advance = () => { if (done) return; done = true; clearTimeout(guard); next(); };
          // some browsers never fire onend (no voices installed): do not hang the whole conversation
          const guard = setTimeout(advance, Math.max(4000, piece.length * 120));
          u.onend = advance; u.onerror = advance;
          speechSynthesis.speak(u);
        };
        next();
      });
    },

    cancel() { tts._token++; tts.speaking = false; if ('speechSynthesis' in window) speechSynthesis.cancel(); }
  };

  root.NXVoice = { AssemblyVoice, PushToTalk, WakeVoice, tts, downsample, toInt16, micError };
})(typeof window !== 'undefined' ? window : globalThis);
