/* Astra Resolve v2.8.0 — premium console UI + AssemblyAI Voice Agent bridge. */
(function(){
  'use strict';
  const $ = (id)=>document.getElementById(id);
  const esc=(v)=>String(v==null?'':v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const store={get(k,d){try{return localStorage.getItem(k)??d}catch(e){return d}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
  const S={sessionId:store.get('astra.session',''),mode:store.get('astra.mode','hackathon'),lang:store.get('astra.lang','auto'),theme:store.get('astra.theme','dark'),speak:'auto',busy:false,voice:null,ptt:null,forceWeb:false,forceThink:false,missionStarted:0,eventCount:0,events:[],scenario:store.get('astra.scenario','resolve'),voiceWork:0};

  function setMode(mode){S.mode=mode;store.set('astra.mode',mode);document.body.dataset.mode=mode;document.querySelectorAll('.mode-option').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));$('composerArea').style.display=mode==='personal'?'block':'none';$('voiceQuality').textContent=mode==='hackathon'?'AssemblyAI':'Whisper + AOB';$('micLabel').textContent=mode==='hackathon'?'START SESSION':'TALK TO ASTRA';stopVoice();toast(mode==='hackathon'?'AssemblyAI Voice Agent enabled':'Personal mode enabled');}
  function setState(state,msg){document.body.dataset.state=state;$('stateWord').textContent=({idle:'READY',connecting:'CONNECTING',listening:'LISTENING',transcribing:'TRANSCRIBING',thinking:'THINKING',speaking:'SPEAKING',error:'ERROR'}[state]||String(state).toUpperCase());if(msg!==undefined)$('live').textContent=msg;$('visualizer').className='audio-visualizer '+(state==='speaking'?'speaking':state==='thinking'?'thinking':state==='error'?'error':state==='listening'?'active':'');updateMissionPhase(state);}
  function toast(msg){$('toast').textContent=msg;$('toast').classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>$('toast').classList.remove('show'),2600)}
  function language(){return S.lang==='auto'?'auto':S.lang}
  function addEvent(label,kind='info'){S.eventCount++;const now=new Date();const time=now.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});S.events.unshift({time,label,kind});S.events=S.events.slice(0,30);$('eventBadge').textContent=S.eventCount+' events';$('eventStream').innerHTML=S.events.map((e,i)=>'<div class="event-row '+(i===0?'active':'')+'"><span class="event-time">'+esc(e.time)+'</span><span>'+esc(e.label)+'</span></div>').join('')}
  function updateMissionPhase(state){const map={idle:'READY',connecting:'CONNECTING',listening:'LISTENING',transcribing:'PROCESSING',thinking:'THINKING',speaking:'SPEAKING',error:'ERROR'};$('missionPhase').textContent=map[state]||String(state).toUpperCase();$('missionStatus').textContent=map[state]||state;}
  function timerTick(){if(!S.missionStarted){$('missionElapsed').textContent='00:00';return}const sec=Math.max(0,Math.floor((Date.now()-S.missionStarted)/1000));$('missionElapsed').textContent=String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0');}
  setInterval(timerTick,1000);

  async function api(path,opts={}){const r=await fetch(path,opts);if(!r.ok){let msg='Request failed (HTTP '+r.status+')';try{const j=await r.json();msg=(j.error&&j.error.message)||j.detail||msg}catch(e){}throw new Error(msg)}return r.json()}
  async function ensureSession(){if(S.sessionId)return;const s=await api('/api/sessions',{method:'POST'});S.sessionId=s.session_id;store.set('astra.session',S.sessionId);$('missionTitle').textContent=s.title;await refreshMissions()}
  async function refreshMissions(){try{const j=await api('/api/sessions');$('missions').innerHTML=(j.sessions||[]).map(s=>'<div class="mission-item '+(s.id===S.sessionId?'active':'')+'" data-id="'+esc(s.id)+'"><b>'+esc(s.title||'Mission')+'</b><small>'+esc(String(s.updated_at||'').replace('T',' '))+'</small></div>').join('')||'<div class="empty-feed">No missions yet.</div>';document.querySelectorAll('.mission-item').forEach(x=>x.onclick=()=>loadSession(x.dataset.id))}catch(e){}}
  async function loadSession(id){S.sessionId=id;store.set('astra.session',id);const j=await api('/api/sessions/'+encodeURIComponent(id)+'/history');$('feed').innerHTML='';(j.messages||[]).forEach(m=>addBubble(m.role,(m.metadata&&m.metadata.response)||m.content,m.source));const first=(j.messages||[])[0];$('missionTitle').textContent=first&&first.content?(first.content.slice(0,42)+(first.content.length>42?'…':'')):'Mission';await loadMissionEvents();await refreshMissions();}
  function responsePlainText(response){
    if(!response)return '';
    if(typeof response.plain_text==='string')return response.plain_text;
    const segs=Array.isArray(response.segments)?response.segments:[];
    const out=[];
    for(const s of segs){
      const t=s&&s.type;
      if(['text','warning','error','link','math'].includes(t)&&s.content)out.push(String(s.content));
      else if(t==='list'&&Array.isArray(s.items))out.push(s.items.map(x=>'- '+x).join('\n'));
      else if(t==='code'&&s.content){out.push('['+(s.language||'code')+(s.filename?' '+s.filename:'')+']');}
    }
    return out.filter(Boolean).join('\n').trim();
  }
  function addBubble(role,text,source){
    const d=document.createElement('div');d.className='bubble '+(role==='user'?'user':'assistant');
    const head='<div class="label">'+(role==='user'?'YOU':'ASTRA')+(source==='voice'?' · VOICE':'')+'</div>';
    let body='';
    if(role==='assistant'){
      const payload=(text&&typeof text==='object')?text:{response_type:'text',segments:[{type:'text',content:String(text==null?'':text)}]};
      body=(window.R&&R.renderResponse)?R.renderResponse(payload):esc(responsePlainText(payload));
    }else{body=esc(String(text==null?'':text));}
    d.innerHTML=head+body;$('feed').appendChild(d);if(role==='assistant'&&window.R&&R.hydrateArtifacts)R.hydrateArtifacts(d);$('feed').scrollTop=$('feed').scrollHeight;
  }
  function clearFeed(){ $('feed').innerHTML='<div class="empty-feed">Your next mission starts here. Use your voice to describe a real problem.</div>'; }
  function setLive(t,final){$('transcript').textContent=t||'Waiting for your voice…';if(t)$('live').textContent=t;if(final){setTimeout(()=>{$('live').textContent=''},900)}}
  function noteTool(name,status){const grid=$('toolGrid');if(!grid)return;grid.querySelectorAll('.tool-pill').forEach(x=>x.classList.remove('active'));const map={'astra_resolve':'Voice Agent','web_search':'Web Search','check_url':'URL Health'};const label=map[name];if(label){const el=[...grid.querySelectorAll('.tool-pill')].find(x=>x.textContent.trim()===label);if(el)el.classList.add('active')}}
  function renderEvidence(meta,result){
    meta=meta||{};const ev=meta.evidence||[];if($('evidenceCount'))$('evidenceCount').textContent=String(ev.length);if($('evidenceList'))$('evidenceList').innerHTML=ev.length?ev.map(x=>'<div class="evidence-row"><span class="evidence-dot"></span><div><b>'+esc(x.label||x.type||'Evidence')+'</b><small>'+esc(x.value||'Verified result')+'</small></div></div>').join(''):'<div class="agent-empty">Evidence appears when Astra verifies something.</div>';if($('evidenceMini'))$('evidenceMini').innerHTML=ev.slice(0,4).map(x=>'<span class="evidence-chip">✓ '+esc(x.label||x.type||'Verified')+'</span>').join('');const body=result?.response?.plain_text||result?.response?.segments?.map(x=>x.content||'').join(' ')||'';if($('outcomeState'))$('outcomeState').textContent=(meta.approval?.required?'ACTION READY':(ev.length?'VERIFIED':(meta.outcome?'COMPLETE':'READY')));if($('outcomeBody'))$('outcomeBody').textContent=meta.approval?.required?'Astra verified the proposed action and is waiting for your confirmation.':(body.slice(0,360)||'Your verified result will appear here after the mission runs.');}
  function showApproval(meta){if(!meta?.approval?.required||!$('approvalModal'))return;const p=meta.pending_action?.payload||{};$('approvalTitle').textContent=meta.approval.label||'Confirm action';const bits=[];if(p.customer_name)bits.push('Name: '+p.customer_name);if(p.service_id)bits.push('Service: '+p.service_id.replace(/_/g,' '));if(p.date)bits.push('Date: '+p.date);if(p.time)bits.push('Time: '+p.time);$('approvalText').textContent=bits.join(' · ')||'Astra is ready to perform this action.';$('approvalModal').hidden=false;}
  function hideApproval(){if($('approvalModal'))$('approvalModal').hidden=true}
  async function loadMissionEvents(){if(!S.sessionId)return;try{const j=await api('/api/sessions/'+encodeURIComponent(S.sessionId)+'/events?limit=500');S.eventCount=j.events?.length||0;$('eventBadge').textContent=S.eventCount+' events';const es=(j.events||[]).slice(-30).reverse();$('eventStream').innerHTML=es.length?es.map((e,i)=>'<div class="event-row '+(i===0?'active':'')+'"><span class="event-time">'+esc(String(e.created_at||'').slice(11,19))+'</span><span>'+esc(e.label||e.event_type)+'</span></div>').join(''):'<div class="event-empty">Mission events will appear here.</div>'}catch(e){}}
  function setScenario(name){S.scenario=name;store.set('astra.scenario',name);document.querySelectorAll('.scenario-card,.mode-menu button').forEach(b=>b.classList.toggle('active',b.dataset.scenario===name));const label=name==='receptionist'?'FRONT DESK':name==='floorops'?'FLOOROPS':'RESOLVE';if($('scenarioName'))$('scenarioName').textContent=name==='receptionist'?'Front Desk':name==='floorops'?'FloorOps':'Resolve';if($('scenarioTopLabel'))$('scenarioTopLabel').textContent=label;if($('live'))$('live').textContent=name==='receptionist'?'Try: “Book an appointment tomorrow at 3 PM.”':name==='floorops'?'Try: “Check SKU-104 stock.”':'Try: “Check whether my website is reachable.”';if($('frontdeskPanel'))$('frontdeskPanel').hidden=name!=='receptionist';if($('flooropsPanel'))$('flooropsPanel').hidden=name!=='floorops';if(name==='receptionist')loadFrontDesk();if(name==='floorops')loadFloorOps()}
  function renderFrontDesk(rows){if(!$('bookingList'))return;$('bookingList').innerHTML=(rows||[]).length?(rows||[]).slice(0,6).map(x=>'<div class="booking-row"><div><b>'+esc(x.customer_name||'Visitor')+'</b><small>'+esc(x.service||'Appointment')+'</small></div><div><b>'+esc((x.appointment_date||'')+' '+(x.appointment_time||''))+'</b><small>'+esc(x.confirmation_code||'')+'</small></div></div>').join(''):'<div class="agent-empty">Confirmed appointments will appear here.</div>';}
  async function loadFloorOps(){if(!$('flooropsPanel'))return;try{const [inv,inc]=await Promise.all([api('/api/floorops/inventory'),api('/api/floorops/incidents')]);$('floorInventoryCount').textContent=(inv.items||[]).length+' tracked';$('floorIncidentCount').textContent=(inc.incidents||[]).filter(x=>x.status==='open').length+' open';$('floorIncidentList').innerHTML=(inc.incidents||[]).slice(0,5).map(x=>'<div class="booking-row"><div><b>'+esc(x.incident_code)+'</b><small>'+esc(x.status)+'</small></div><div><b>'+esc(String(x.description).slice(0,40))+'</b></div></div>').join('')||'<div class="agent-empty">No open incidents.</div>';if($('floorStatus'))$('floorStatus').textContent='ONLINE'}catch(e){if($('floorStatus'))$('floorStatus').textContent='OFFLINE'}}
  async function loadFrontDesk(){if(!$('frontdeskPanel'))return;try{const p=await api('/api/receptionist/profile');$('frontDeskBusiness').textContent=p.business_name||'Astra Front Desk';$('frontDeskHours').textContent=p.hours||'—';const j=await api('/api/receptionist/bookings');renderFrontDesk(j.bookings||[]);$('frontDeskStatus').textContent=(j.bookings||[]).length+' BOOKED'}catch(e){$('frontDeskStatus').textContent='OFFLINE'}}

  function renderAobTelemetry(result){
    const trace=result.trace||[];
    const meta=(result.response&&result.response.meta)||{};
    renderEvidence(meta,result);
    const roles=(result.plan&&result.plan.assignments)||[];
    if($('assignmentBadge'))$('assignmentBadge').textContent=roles.length+' roles';
    if($('assignmentList'))$('assignmentList').innerHTML=roles.length?roles.map(a=>'<div class="assignment-row"><span class="role-badge">'+esc(a.role||'specialist')+'</span><div><b>'+esc((a.agent||'agent').replace(/_/g,' '))+'</b><small>'+esc(a.done_when||a.task||'')+'</small></div></div>').join(''):'<div class="agent-empty">Astra assigns roles when a mission starts.</div>';
    $('agentBadge').textContent=trace.filter(t=>t.status==='success'||t.status==='error').length+' finished';
    $('agentList').innerHTML=trace.length?trace.map(t=>'<div class="agent-row '+esc(t.status)+'"><i class="agent-dot"></i><div><b>'+esc(t.role?((t.role)+' · '):'')+esc((t.agent||'agent').replace(/_/g,' '))+'</b><small>'+esc(t.done_when||t.task||'')+'</small></div><em>'+esc(String(t.duration_ms||0))+'ms</em></div>').join(''):'<div class="agent-empty">No agent run yet.</div>';
    $('missionGoal').textContent=(result.plan&&result.plan.goal)||'Mission';
    const objective=meta.task_contract?.objective || result.plan?.goal || 'Give Astra a real outcome to complete.';
    const deliverables=meta.deliverables||result.plan?.deliverables||[];
    const criteria=meta.success_criteria||result.plan?.success_criteria||[];
    if($('taskTeam'))$('taskTeam').textContent=(meta.team||result.plan?.team||'General Team').toUpperCase();
    if($('taskObjective'))$('taskObjective').textContent=objective;
    if($('taskDeliverable'))$('taskDeliverable').textContent=deliverables[0]||'A verified result.';
    if($('taskDone'))$('taskDone').textContent=criteria[0]||'Success criteria are satisfied.';
    if(result.trace&&result.trace.some(t=>t.agent==='operator_agent')){noteTool('check_url');addEvent('Real public diagnostic executed','tool')}
    if(result.trace&&result.trace.some(t=>t.agent==='web_agent')){noteTool('web_search');addEvent('Live web search executed','tool')}
    if(result.response&&result.response.meta?.artifacts&&window.R&&R.hydrateArtifacts) setTimeout(()=>R.hydrateArtifacts($('feed')),0);
  }


  async function sendText(text){text=(text||'').trim();if(!text||S.busy)return;S.busy=true;await ensureSession();S.missionStarted=S.missionStarted||Date.now();addBubble('user',text,'text');addEvent('User request received');setState('thinking','Astra is planning…');try{const res=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:S.sessionId,message:text,source:'text',language:language(),mode:S.mode==='hackathon'?'hackathon':'personal',workspace:S.scenario,output:S.speak,force_agent:S.forceWeb?'web_agent':null,force_think:S.forceThink,stt_provider:null})});if(!res.ok||!res.body)throw new Error('Astra request failed');const reader=res.body.getReader(),dec=new TextDecoder();let buf='',data=null;while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let idx;while((idx=buf.indexOf('\n\n'))>=0){const frame=buf.slice(0,idx);buf=buf.slice(idx+2);const line=frame.split('\n').find(x=>x.startsWith('data: '));if(!line)continue;let ev;try{ev=JSON.parse(line.slice(6))}catch(e){continue}if(ev.type==='plan'){addEvent('Plan created · '+(ev.goal||ev.kind));$('missionGoal').textContent=ev.goal||'';if($('taskTeam'))$('taskTeam').textContent=String(ev.team||'General').toUpperCase();if($('taskObjective'))$('taskObjective').textContent=ev.goal||'';if($('taskDeliverable'))$('taskDeliverable').textContent=(ev.deliverables||[])[0]||'Verified result';if($('taskDone'))$('taskDone').textContent=(ev.success_criteria||[])[0]||'Success criteria are satisfied.';const steps=ev.steps||[];if($('assignmentBadge'))$('assignmentBadge').textContent=steps.length+' roles';if($('assignmentList'))$('assignmentList').innerHTML=steps.length?steps.map(a=>'<div class=\"assignment-row\"><span class=\"role-badge\">'+esc(a.role||'specialist')+'</span><div><b>'+esc((a.agent||'agent').replace(/_/g,' '))+'</b><small>'+esc(a.done_when||a.activation||'Assigned to mission')+'</small></div></div>').join(''):'<div class=\"agent-empty\">Astra assigns roles when a mission starts.</div>';if((ev.team||'General')!=='General')addEvent('Team assigned · '+ev.team,'success');}if(ev.type==='step_start'){addEvent('Agent started · '+ev.agent);setState('thinking','Running '+String(ev.agent||'agent').replace(/_/g,' ')+'…')}if(ev.type==='step_end'){addEvent('Agent '+ev.status+' · '+ev.agent,ev.status);if(ev.duration_ms)$('latencyStat').textContent=ev.duration_ms+'ms'}if(ev.type==='final')data=ev.data}}if(!data)throw new Error('No final response');if(data.response){addBubble('assistant',data.response, 'text');renderAobTelemetry(data);if(data.response.meta?.approval?.required)showApproval(data.response.meta);if(S.scenario==='receptionist')loadFrontDesk()}if(data.error){const msg=data.error.message||'Astra reported an error';if(!data.response)addBubble('assistant',{response_type:'error',segments:[{type:'error',content:msg}]},'text');toast(msg);addEvent('Mission failed · '+msg,'error');setState('error',msg)}else{addEvent('Mission result ready','success');setState('idle','')}await refreshMissions()}catch(e){addBubble('assistant',e.message||'Request failed','text');addEvent('Request failed','error');setState('error',e.message)}finally{S.busy=false}}

  // Managed AssemblyAI Voice Agent ------------------------------------------------
  function toggleVoice(){if(S.mode==='hackathon')toggleAssemblyAgent();else togglePtt()}
  async function toggleAssemblyAgent(){if(S.voice&&S.voice.active){stopVoice();setState('idle','Session ended');return}if(!S.health?.assemblyai_voice_agent?.configured){toast('Set ASSEMBLYAI_API_KEY in Render first');return}if(!V.AssemblyVoiceAgent.supported()){toast('Use a modern HTTPS browser for voice mode');return}ttsStop();await ensureSession();S.missionStarted=S.missionStarted||Date.now();S.voice=new V.AssemblyVoiceAgent({
    getSessionId:()=>S.sessionId,getLanguage:()=>language(),
    onStatus:t=>{setLive(t,false);if(/checking|processing|thinking|composing/i.test(t))setState('thinking',t);else if(/listening/i.test(t))setState('listening',t);},
    onPartial:t=>{setLive(t,false);setState('listening','Listening…')},
    onUser:t=>{addBubble('user',t,'voice');setLive(t,true);addEvent('Voice turn received')},
    onAgent:(t,interrupted)=>{if(t)addBubble('assistant',t,'voice');if(interrupted)addEvent('Agent reply interrupted · barge-in');else addEvent('Voice reply delivered','success');if(S.voiceWork>0)setState('thinking','Astra is still working on your task…');else setState('listening','Listening — ready for you')},
    onToolCall:m=>{S.voiceWork++;noteTool(m.name);addEvent('Tool requested · '+m.name,'tool');setState('thinking','Astra is working on your task…')},
    onToolResult:(call,r)=>{S.voiceWork=Math.max(0,S.voiceWork-1);if(r.trace)renderAobTelemetry(r);addEvent('Astra finished a work step','success');if(r.normalized&&r.normalized.needs_clarification)toast('Astra asked for one missing detail');if(S.voiceWork>0)setState('thinking','Astra is continuing the task…')},
    onError:m=>{toast(m);addEvent('Voice error · '+m,'error');setState('error',m)},onLevel:l=>{document.documentElement.style.setProperty('--mic-level',l)},onSpeechStart:()=>{addEvent('Barge-in detected · playback flushed')},onReady:id=>{addEvent('AssemblyAI Voice Agent session ready');setState('listening','Listening — tell Astra the problem')},onInterrupted:()=>{addEvent('Astra stopped speaking because you interrupted');setState(S.voiceWork>0?'thinking':'listening',S.voiceWork>0?'Astra is continuing the task…':'Listening — your turn')}
  });try{setState('connecting','Opening AssemblyAI Voice Agent…');await S.voice.start();$('micLabel').textContent='END SESSION';$('latencyStat').textContent='LIVE'}catch(e){S.voice=null;toast(e.message);setState('error',e.message)}}
  function spokenAck(text){const t=String(text||'').toLowerCase();if(/\b(create|build|make|write|generate|fix|debug|code|website|app|page)\b|બનાવ|લખ|સુધાર|कोड|बनाओ|लिखो/i.test(t))return S.lang==='gu'?'હા, હું તમારું કામ હવે બનાવી રહ્યો છું.':S.lang==='hi'?'हाँ, मैं आपका काम अभी शुरू कर रहा हूँ।':'Got it — I’m building that now.';if(/\b(check|research|find|search|diagnose|compare|book|appointment)\b|ચેક|શોધ|બુક|अपॉइंटमेंट/i.test(t))return S.lang==='gu'?'હા, હું આ તપાસવાનું અને કામ કરવાનું શરૂ કરું છું.':S.lang==='hi'?'ठीक है, मैं इसकी जाँच और काम अभी शुरू करता हूँ।':'Got it — I’m working on that now.';return S.lang==='gu'?'હા, સમજી ગયો. હું આ કામ હવે કરું છું.':S.lang==='hi'?'ठीक है, समझ गया। मैं अभी यह काम करता हूँ।':'Got it — I’ll take care of it now.';}

  async function togglePtt(){if(S.ptt&&S.ptt.active){S.ptt.stop();return}if(!S.health?.free_stt_configured){toast('Free voice needs GROQ_API_KEY');return}ttsStop();S.ptt=new V.PushToTalk({getLanguage:()=>language(),onStatus:t=>setState('listening',t),onLevel:()=>{},onBusy:b=>{if(b)setState('transcribing','Converting speech…')},onText:t=>{V.tts.speak(spokenAck(t), S.lang==='gu'?'gu-IN':S.lang==='hi'?'hi-IN':'en-US');sendText(t);},onError:m=>toast(m)});try{await S.ptt.start()}catch(e){toast(e.message)}}
  function stopVoice(){if(S.voice){S.voice.stop();S.voice=null}if(S.ptt){S.ptt.stop();S.ptt=null}V.tts.cancel();$('micLabel').textContent=S.mode==='hackathon'?'START SESSION':'TALK TO ASTRA'}
  function ttsStop(){V.tts.cancel()}

  async function loadHealth(){try{S.health=await api('/api/health');$('healthText').textContent=S.health.assemblyai_voice_agent?.configured?'Systems online · Voice Agent ready':'Systems online · add AssemblyAI key';$('healthDot').className=S.health.assemblyai_voice_agent?.configured?'ok':'bad'}catch(e){$('healthText').textContent='Backend unreachable';$('healthDot').className='bad'}}

  // Rich artifact actions: copy complete files without exposing any hidden data.
  document.addEventListener('click',(e)=>{
    const btn=e.target.closest('.artifact-copy,[data-code][data-act]');
    if(!btn)return;
    if(btn.classList.contains('artifact-copy')){
      const card=btn.closest('[data-artifact-card]'); const id=card&&card.getAttribute('data-artifact-card'); const entry=window.R&&R.artifactStore&&R.artifactStore[id];
      const idx=Number(btn.getAttribute('data-file-index'));
      const file=entry&&entry.bundle&&entry.bundle.files&&entry.bundle.files[idx];
      if(file){if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(String(file.content||'')).then(()=>toast('Copied '+file.path)).catch(()=>toast('Copy failed'));else toast('Clipboard is unavailable in this browser');} return;
    }
    const card=btn.closest('[data-code]'); const id=card&&card.getAttribute('data-code'); const item=window.R&&R.codeStore&&R.codeStore[id];
    if(!item)return;
    const act=btn.getAttribute('data-act');
    if(act==='copy'){if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(item.content).then(()=>toast('Code copied')).catch(()=>toast('Copy failed'));else toast('Clipboard is unavailable in this browser');}
    if(act==='save'){const blob=new Blob([item.content],{type:'text/plain'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=item.filename||R.fileName(item);document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),500);}
    if(act==='run')toast('Python execution is disabled in this public build.');
  });

  $('mic').onclick=toggleVoice;
  $('newMission').onclick=async()=>{stopVoice();S.sessionId='';store.set('astra.session','');S.events=[];S.eventCount=0;S.voiceWork=0;$('eventBadge').textContent='0 events';$('agentList').innerHTML='<div class="agent-empty">No agent run yet.</div>';$('eventStream').innerHTML='<div class="event-empty">Mission events will appear here.</div>';clearFeed();$('missionTitle').textContent='New mission';S.missionStarted=Date.now();await ensureSession();toast('New mission created')};
  $('clearMission').onclick=clearFeed;
  if($('historySearch'))$('historySearch').oninput=()=>{const q=$('historySearch').value.toLowerCase().trim();document.querySelectorAll('.mission-item').forEach(x=>x.style.display=!q||x.textContent.toLowerCase().includes(q)?'':'none')};
  $('composer').onsubmit=e=>{e.preventDefault();const t=$('message').value;$('message').value='';$('message').style.height='auto';sendText(t)};
  $('message').onkeydown=e=>{
    if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){
      e.preventDefault();
      if(S.busy)return;
      $('composer').requestSubmit();
    }
  };
  $('message').oninput=()=>{$('message').style.height='auto';$('message').style.height=Math.min(170,$('message').scrollHeight)+'px'};
  $('webBtn').onclick=()=>{S.forceWeb=!S.forceWeb;$('webBtn').classList.toggle('on',S.forceWeb);toast(S.forceWeb?'Web tool forced':'Automatic web routing')};
  $('thinkBtn').onclick=()=>{S.forceThink=!S.forceThink;$('thinkBtn').classList.toggle('on',S.forceThink);toast(S.forceThink?'Deep planning enabled':'Normal planning')};
  $('selftestBtn').onclick=async()=>{try{toast('Running self-test…');const j=await api('/api/selftest');toast(j.all_ok?'Self-test passed':'Some self-tests need attention');}catch(e){toast(e.message)}};
  $('themeBtn').onclick=()=>{S.theme=S.theme==='dark'?'light':'dark';store.set('astra.theme',S.theme);document.body.classList.toggle('light',S.theme==='light');toast(S.theme==='light'?'Light theme':'Dark theme')};
  $('langBtn').onclick=()=>{const cycle=['auto','en','hi','gu'];S.lang=cycle[(cycle.indexOf(S.lang)+1)%cycle.length];store.set('astra.lang',S.lang);$('langBtn').textContent=S.lang.toUpperCase();toast('Language: '+(S.lang==='auto'?'Auto':S.lang))};
  $('orchBtn').onclick=()=>{$('orch').classList.add('open');$('scrim').hidden=false};$('scrim').onclick=()=>{$('orch').classList.remove('open');$('rail').classList.remove('open');$('scrim').hidden=true};$('menuBtn').onclick=()=>{$('rail').classList.add('open');$('scrim').hidden=false};$('closeTelemetry').onclick=()=>{$('orch').classList.remove('open');$('scrim').hidden=true};
  document.querySelectorAll('.mode-option').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
  document.querySelectorAll('.scenario-card').forEach(b=>b.onclick=()=>setScenario(b.dataset.scenario));if($('scenarioBtn'))$('scenarioBtn').onclick=()=>{const c=['resolve','receptionist','floorops'];setScenario(c[(c.indexOf(S.scenario)+1)%c.length])};if($('scenarioTopBtn'))$('scenarioTopBtn').onclick=(e)=>{e.stopPropagation();const m=$('scenarioMenu');m.hidden=!m.hidden;$('scenarioTopBtn').setAttribute('aria-expanded',String(!m.hidden))};document.querySelectorAll('.mode-menu button').forEach(b=>b.onclick=()=>{$('scenarioMenu').hidden=true;$('scenarioTopBtn').setAttribute('aria-expanded','false');setScenario(b.dataset.scenario)});document.addEventListener('click',e=>{if(!$('modePicker')?.contains(e.target)&&$('scenarioMenu')){$('scenarioMenu').hidden=true;if($('scenarioTopBtn'))$('scenarioTopBtn').setAttribute('aria-expanded','false')}});if($('frontDeskBtn'))$('frontDeskBtn').onclick=()=>setScenario('receptionist');if($('approvalCancel'))$('approvalCancel').onclick=()=>{hideApproval();sendText('No, cancel that action.')};if($('approvalConfirm'))$('approvalConfirm').onclick=()=>{hideApproval();sendText('Yes, confirm that action.')};if($('reportBtn'))$('reportBtn').onclick=async()=>{try{const j=await api('/api/sessions/'+encodeURIComponent(S.sessionId)+'/report');const m=j.summary||{};$('outcomeState').textContent=(m.status||'complete').toUpperCase();$('outcomeBody').textContent='Report · '+(m.mission_type||'general')+' · '+(m.event_count||0)+' events · '+(m.evidence_count||0)+' evidence items';addEvent('Mission report generated','success');toast('Mission report ready')}catch(e){toast(e.message)}};if($('replayBtn'))$('replayBtn').onclick=async()=>{try{const j=await api('/api/sessions/'+encodeURIComponent(S.sessionId)+'/replay');await loadMissionEvents();const count=j.event_count||0;addEvent('Mission replay loaded · '+count+' events','tool');if(j.state?.mission_type)$('missionGoal').textContent='Replay · '+j.state.mission_type.replace(/_/g,' ');toast('Mission replay loaded')}catch(e){toast(e.message)}};setScenario(S.scenario);document.body.classList.toggle('light',S.theme==='light');$('langBtn').textContent=S.lang.toUpperCase();setMode(S.mode);loadHealth();ensureSession().then(loadSession.bind(null,S.sessionId)).catch(()=>{});
})();
