const R = require(require('path').join(__dirname, '..', 'static', 'render.js'));
const assert = require('assert');
// XSS: nothing from the model can become markup
const evil = R.renderResponse({response_type:'text', segments:[
  {type:'text', content:'<img src=x onerror=alert(1)> **bold** `<b>` [x](javascript:alert(1)) [ok](https://a.b/c?d=1&e=2)'},
  {type:'code', language:'html', filename:'<script>.html', content:'<script>alert(1)</script>'},
  {type:'math', content:'a < b \\frac{1}{2}'},
  {type:'warning', content:'<b>hi</b>'},
]});
assert(!/<(img|script|b)\b/i.test(evil.replace(/<\/?(strong|code|pre|p|div|b|span|button|a|h4)\b[^>]*>/g,'')) , 'unescaped markup: ' + evil);
assert(!/<img|<script/i.test(evil));
assert(!evil.includes('href="javascript'), 'js link allowed');
assert(evil.includes('href="https://a.b/c?d=1&amp;e=2"'));
assert(evil.includes('\\[a &lt; b \\frac{1}{2}\\]'));
// structure
const ok = R.renderResponse({response_type:'mixed', segments:[
  {type:'text', content:'## Title\nline1\nline2\n\npara2'},
  {type:'code', language:'python', filename:'calc.py', content:'def f():\n    return 1'},
  {type:'table', header:['a','b'], rows:[['1','2']]},
  {type:'list', items:['x','y'], ordered:true},
], }, {canRun:true});
assert(ok.includes('<h4>Title</h4>') && ok.includes('line1<br>line2') && ok.includes('<p class="seg-text">para2</p>'));
assert(ok.includes('data-act="run"') && ok.includes('<pre><code>def f():\n    return 1</code></pre>'));
assert(ok.includes('<ol><li>x</li><li>y</li></ol>') && ok.includes('<td>1</td>'));
const id = /data-code="(c\d+)"/.exec(ok)[1];
assert.strictEqual(R.codeStore[id].content, 'def f():\n    return 1');
assert.strictEqual(R.fileName(R.codeStore[id]), 'calc.py');
assert.strictEqual(R.fileName({language:'javascript'}), 'code.js');
assert(R.renderResponse({response_type:'clarification', segments:[{type:'text', content:'Which one?'}]}).includes('clarify'));

const artifact = R.renderResponse({response_type:'code', segments:[{type:'text',content:'Created it.'}], meta:{artifacts:[{id:'demo',type:'code_project',title:'Login page',entrypoint:'index.html',preview:true,files:[{path:'index.html',language:'html',content:'<html><body><h1>Login</h1></body></html>'},{path:'styles.css',language:'css',content:'body{color:red}'},{path:'script.js',language:'javascript',content:"console.log('ok')"}]}]}});
assert(artifact.includes('artifact-card') && artifact.includes('artifact-preview') && artifact.includes('index.html'));
console.log('render.js OK');
const fs = require('fs');
const appJs = fs.readFileSync(require('path').join(__dirname, '..', 'static', 'app.js'), 'utf8');
assert(appJs.includes("$('message').onkeydown") && appJs.includes("!e.shiftKey") && appJs.includes("e.preventDefault()"), 'Enter key handler missing');
assert(appJs.includes("requestSubmit()"), 'Enter should submit the composer form');
console.log('composer enter handler OK');
