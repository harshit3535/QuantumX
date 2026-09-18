let sessionId = null;
let socket = null;
let audioContext = null;
let processor = null;
let sourceNode = null;
let listening = false;
let currentLanguage = 'en';
let voiceMediaStream = null;
let healthState = null;

const $ = (s) => document.querySelector(s);
const chat = $('#chat');

function addMessage(role, text, meta='') {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `<div class="avatar">${role === 'user' ? 'U' : 'N'}</div><div><div class="bubble"></div></div>`;
  wrap.querySelector('.bubble').textContent = text;
  if (meta) wrap.querySelector('.bubble').dataset.meta = meta;
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

function addWelcome(){
  if (chat.children.length) return;
  addMessage('assistant', 'I’m NEXUS. Give me a goal, a question, or a casual message. I’ll decide whether it needs a specialist agent, a multi-step plan, or just a normal conversation.');
}

async function createSession(){
  const r = await fetch('/api/sessions', {method:'POST'});
  const data = await r.json();
  sessionId = data.session_id;
  $('#missionTitle').textContent = data.title;
  chat.innerHTML = '';
  addWelcome();
  await refreshSessions();
}

async function refreshSessions(){
  const r = await fetch('/api/sessions');
  const data = await r.json();
  const box = $('#sessionList'); box.innerHTML='';
  data.sessions.forEach(s=>{
    const el=document.createElement('div'); el.className='session'+(s.id===sessionId?' active':''); el.textContent=s.title;
    el.onclick=()=>loadSession(s.id); box.appendChild(el);
  });
}

async function loadSession(id){
  sessionId=id;
  const r = await fetch(`/api/sessions/${id}/history`); const data=await r.json();
  chat.innerHTML=''; data.messages.forEach(m=>addMessage(m.role==='user'?'user':'assistant',m.content));
  const session = (await (await fetch('/api/sessions')).json()).sessions.find(s=>s.id===id);
  $('#missionTitle').textContent = session?.title || 'Mission';
  $('#planGoal').textContent='Loaded session. Send the next instruction to continue.';
  await refreshSessions();
}

function setPlan(plan){
  $('#planGoal').textContent = plan.goal || 'No goal';
  $('#confidence').textContent = `${Math.round((plan.confidence||0)*100)}% confidence`;
  $('#outputType').textContent = (plan.response_mode||'text').toUpperCase();
  const box=$('#planSteps'); box.innerHTML='';
  if(!plan.steps?.length){box.innerHTML='<div class="empty-small">Conversation mode — no task plan required.</div>';return;}
  plan.steps.forEach(s=>{
    const el=document.createElement('div'); el.className='step';
    el.innerHTML=`<div class="step-num">${s.id}</div><div><div class="step-name">${s.agent.replaceAll('_',' ')}</div><div class="step-task">${escapeHtml(s.task)}</div></div><div class="step-badge">READY</div>`;
    box.appendChild(el);
  });
}

function renderArtifact(final){
  const box=$('#artifact'); box.innerHTML='';
  if(final.visual_type==='math'){
    box.innerHTML=`<div class="math-card"><div class="expr">\\(${escapeHtml(final.data?.latex||final.data?.result||final.summary)}\\)</div><div class="result">${escapeHtml(final.summary||'')}</div></div>`;
    if(window.MathJax) MathJax.typesetPromise([box]);
  } else if(final.visual_type==='code'){
    box.innerHTML=`<pre><code>${escapeHtml(final.data?.code||'')}</code></pre>`;
  } else {
    box.innerHTML=`<div class="empty-small">${escapeHtml((final.summary||'').slice(0,320))}</div>`;
  }
}

function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

async function sendMessage(source='text', language=currentLanguage, explicitText=null){
  const text = (explicitText ?? $('#message').value).trim();
  if(!text) return;
  if(!sessionId) await createSession();
  $('#message').value=''; addMessage('user',text);
  $('#sendBtn').disabled=true; $('#voiceStatus').textContent='CORE is planning…';
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,message:text,source,language})});
    const data=await r.json();
    if(!r.ok) throw new Error(data.detail||'Request failed');
    setPlan(data.plan); renderArtifact(data.final); addMessage('assistant',data.final.summary||data.final.spoken_response||'Done.');
    if(source==='voice' && language.startsWith('en')) speak(data.final.spoken_response||data.final.summary||'Done.');
    $('#voiceStatus').textContent='Ready. Give NEXUS another instruction.';
    await refreshSessions();
  }catch(e){
    addMessage('assistant',`I hit a recoverable error: ${e.message}`); $('#voiceStatus').textContent='Ready.';
  }finally{$('#sendBtn').disabled=false;}
}

function speak(text){
  if(!('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(text); u.lang='en-US'; u.rate=.98; speechSynthesis.speak(u);
}

async function startVoice(){
  if(listening){stopVoice();return;}

  const selectedLang=$('#voiceLang').value;
  currentLanguage=selectedLang;
  if(selectedLang !== 'en'){
    $('#voiceStatus').textContent='Hindi/Gujarati are text-first in this demo. Select English for voice input.';
    return;
  }
  if(!healthState?.voice_ready){
    $('#voiceStatus').textContent='Voice is disabled: add ASSEMBLYAI_API_KEY in Render → Environment.';
    return;
  }
  if(!navigator.mediaDevices?.getUserMedia){
    $('#voiceStatus').textContent='This browser does not support microphone input.';
    return;
  }

  try {
    voiceMediaStream = await navigator.mediaDevices.getUserMedia({audio:true});
    const tokenResp = await fetch(`/api/assemblyai/token?language=en`);
    const tokenData = await tokenResp.json();
    if(!tokenResp.ok) throw new Error(tokenData.detail||'AssemblyAI token unavailable');

    const query = new URLSearchParams({
      sample_rate:'16000',
      speech_model:tokenData.speech_model,
      format_turns:'true',
      token:tokenData.token
    });
    socket = new WebSocket(`wss://streaming.assemblyai.com/v3/ws?${query.toString()}`);
    socket.binaryType='arraybuffer';

    socket.onopen=()=>{
      listening=true;
      $('#micBtn').classList.add('listening');
      $('#voiceStatus').textContent='Listening… speak in English.';
      audioContext = new AudioContext({sampleRate:16000});
      sourceNode=audioContext.createMediaStreamSource(voiceMediaStream);
      processor=audioContext.createScriptProcessor(4096,1,1);
      processor.onaudioprocess=(e)=>{
        if(!socket || socket.readyState!==1) return;
        const input=e.inputBuffer.getChannelData(0);
        const pcm=new Int16Array(input.length);
        for(let i=0;i<input.length;i++) pcm[i]=Math.max(-1,Math.min(1,input[i]))*0x7fff;
        socket.send(pcm.buffer);
      };
      sourceNode.connect(processor);
      processor.connect(audioContext.destination);
    };

    socket.onmessage=(ev)=>{
      const m=JSON.parse(ev.data);
      if(m.type==='Turn' && m.end_of_turn && m.transcript){
        const transcript=m.transcript.trim();
        stopVoice();
        if(transcript) sendMessage('voice','en',transcript);
      }
    };
    socket.onerror=()=>{
      $('#voiceStatus').textContent='Voice connection failed. Check your AssemblyAI key and try again.';
      stopVoice();
    };
    socket.onclose=()=>{
      if(listening){
        listening=false;
        $('#micBtn').classList.remove('listening');
      }
    };
  } catch(e) {
    stopVoice();
    $('#voiceStatus').textContent=`Voice unavailable: ${e.message}`;
  }
}

function stopVoice(){
  listening=false;
  $('#micBtn').classList.remove('listening');
  if(processor){try{processor.disconnect()}catch{} processor=null}
  if(sourceNode){try{sourceNode.disconnect()}catch{} sourceNode=null}
  if(audioContext){try{audioContext.close()}catch{} audioContext=null}
  if(socket){try{socket.close()}catch{} socket=null}
  if(voiceMediaStream){voiceMediaStream.getTracks().forEach(t=>t.stop());voiceMediaStream=null;}
  if($('#voiceStatus').textContent === 'Listening… speak in English.') $('#voiceStatus').textContent='Ready.';
}

$('#sendBtn').onclick=()=>sendMessage('text','en');
$('#newMission').onclick=createSession;
$('#micBtn').onclick=()=>startVoice();
$('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage('text','en')}});

(async()=>{
  try {
    const r=await fetch('/api/health');
    healthState=await r.json();
    $('#systemStatus').textContent=healthState.ok ? (healthState.voice_ready ? 'System ready' : 'Text ready') : 'Offline';
    $('#voiceStatus').textContent=healthState.voice_ready
      ? 'Text or voice — English voice replies are enabled.'
      : 'Text mode ready. Add ASSEMBLYAI_API_KEY in Render for English voice.';
    $('#micBtn').disabled=!healthState.voice_ready;
    $('#micBtn').title=healthState.voice_ready ? 'Start English voice input' : 'Add ASSEMBLYAI_API_KEY in Render Environment';
    await refreshSessions();
    if(!sessionId){
      const r2=await fetch('/api/sessions',{method:'POST'});
      const s=await r2.json();
      sessionId=s.session_id;
      $('#missionTitle').textContent=s.title;
      addWelcome();
      await refreshSessions();
    }
  } catch(e) {
    $('#systemStatus').textContent='Connection issue';
    $('#voiceStatus').textContent='Backend health check failed. Refresh the page.';
  }
})();
