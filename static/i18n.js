/* UI chrome text only (state words, hints, sample chips, the live "thinking" line).
 * Technical orchestration detail (agent names, plan kind, error kinds) stays in
 * English on purpose - hackathon judges read that panel, and it is not the kind
 * of "suggestion" text this covers. This dictionary IS what changes when the
 * person selects a language, or (if left on Auto) once they speak/type in one. */
(function (root) {
  'use strict';

  const DICT = {
    en: {
      ready: 'Ready', connecting: 'Connecting', listening: 'Listening', transcribing: 'Transcribing',
      thinking: 'Thinking', speaking: 'Speaking', error: 'Trouble',
      startVoice: 'Start', stopVoice: 'Stop', talk: 'Talk',
      hintHackathonReady: 'Voice-first: press Start, then just talk.',
      hintHackathonNoKey: 'AssemblyAI key is not set on the server yet. Use Free API mode until then.',
      hintPersonalReady: 'Type, or press Talk. Free AI providers answer; nothing here uses AssemblyAI.',
      hintPersonalNoKey: 'No AI key on the server yet - math and casual chat still work. Add an AI key for the rest.',
      hintListening: 'Speak naturally. I answer when you pause.',
      hintPTT: 'Listening… stop talking to send',
      hintStopped: 'Stopped.',
      thinkingLive: 'Working…',
      thinkingDone: (n, s) => `Thought for ${s}s · ${n} step${n === 1 ? '' : 's'}`,
      thinkingNone: 'Answered directly',
      chipsTitle: 'Try asking',
      chips: ['Solve a quadratic equation', 'Write a Python calculator', 'What is the capital of France?', 'Mare ghare javu che'],
    },
    gu: {
      ready: 'તૈયાર', connecting: 'જોડાણ થાય છે', listening: 'સાંભળે છે', transcribing: 'લખાય છે',
      thinking: 'વિચારે છે', speaking: 'બોલે છે', error: 'મુશ્કેલી',
      startVoice: 'શરૂ કરો', stopVoice: 'બંધ કરો', talk: 'બોલો',
      hintHackathonReady: 'વોઈસ-ફર્સ્ટ: Start દબાવો, પછી બોલો.',
      hintHackathonNoKey: 'AssemblyAI કી હજી સેટ નથી. ત્યાં સુધી Free API મોડ વાપરો.',
      hintPersonalReady: 'લખો, અથવા બોલો દબાવો. Free AI જવાબ આપશે.',
      hintPersonalNoKey: 'હજી AI કી નથી - ગણિત અને સામાન્ય વાત ચાલશે.',
      hintListening: 'સ્વાભાવિક રીતે બોલો. અટકશો એટલે જવાબ મળશે.',
      hintPTT: 'સાંભળે છે… બોલવાનું બંધ કરો એટલે મોકલાશે',
      hintStopped: 'બંધ થયું.',
      thinkingLive: 'કામ ચાલુ છે…',
      thinkingDone: (n, s) => `${s} સેકન્ડ વિચાર્યું · ${n} પગલાં`,
      thinkingNone: 'સીધો જવાબ આપ્યો',
      chipsTitle: 'આ પૂછી જુઓ',
      chips: ['એક વર્ગ સમીકરણ ઉકેલો', 'Python કેલ્ક્યુલેટર લખો', 'ફ્રાન્સની રાજધાની શું છે?', 'મારે ઘરે જવું છે'],
    },
    hi: {
      ready: 'तैयार', connecting: 'जुड़ रहा है', listening: 'सुन रहा है', transcribing: 'लिखा जा रहा है',
      thinking: 'सोच रहा है', speaking: 'बोल रहा है', error: 'समस्या',
      startVoice: 'शुरू करें', stopVoice: 'रोकें', talk: 'बोलें',
      hintHackathonReady: 'वॉइस-फर्स्ट: Start दबाएँ, फिर बोलें।',
      hintHackathonNoKey: 'AssemblyAI key अभी सेट नहीं है। तब तक Free API मोड इस्तेमाल करें।',
      hintPersonalReady: 'लिखें, या बोलें दबाएँ। मुफ़्त AI जवाब देगा।',
      hintPersonalNoKey: 'अभी कोई AI key नहीं है - गणित और सामान्य बातचीत फिर भी चलेगी।',
      hintListening: 'सामान्य रूप से बोलें। रुकते ही जवाब मिलेगा।',
      hintPTT: 'सुन रहा है… बोलना बंद करें तो भेज दिया जाएगा',
      hintStopped: 'रुक गया।',
      thinkingLive: 'काम चल रहा है…',
      thinkingDone: (n, s) => `${s} सेकंड सोचा · ${n} कदम`,
      thinkingNone: 'सीधा जवाब दिया',
      chipsTitle: 'यह पूछ कर देखें',
      chips: ['एक द्विघात समीकरण हल करें', 'Python कैलकुलेटर लिखें', 'फ्रांस की राजधानी क्या है?', 'मुझे घर जाना है'],
    },
  };

  function t(lang, key, ...args) {
    const L = DICT[lang] || DICT.en;
    const v = (key in L ? L : DICT.en)[key];
    return typeof v === 'function' ? v(...args) : v;
  }

  root.NXi18n = { t, DICT };
})(typeof window !== 'undefined' ? window : globalThis);
