/* Astra Resolve v2.7.1 rich response + artifact workbench.
 * Pure string -> HTML functions. Everything user/model-supplied is escaped first,
 * so nothing from the model can inject markup or scripts. */
(function (root) {
  'use strict';

  const codeStore = {};
  const artifactStore = {};
  let codeSeq = 0;

  const EXT = {
    python: 'py', javascript: 'js', typescript: 'ts', jsx: 'jsx', tsx: 'tsx', html: 'html', css: 'css', json: 'json',
    bash: 'sh', c: 'c', cpp: 'cpp', java: 'java', kotlin: 'kt', go: 'go', rust: 'rs', ruby: 'rb', php: 'php',
    sql: 'sql', yaml: 'yml', xml: 'xml', csharp: 'cs', swift: 'swift', markdown: 'md', text: 'txt'
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // escape only what HTML needs; keep LaTeX backslashes/braces intact for MathJax
  function escMath(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function inline(text) {
    let t = esc(text);
    t = t.replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>');
    t = t.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return t;
  }

  function renderText(content) {
    const out = [];
    let buf = [];
    function flush() {
      if (buf.length) { out.push('<p class="seg-text">' + buf.map(inline).join('<br>') + '</p>'); buf = []; }
    }
    String(content || '').split('\n').forEach(function (line) {
      const h = /^\s{0,3}#{1,6}\s+(.*)$/.exec(line);
      if (h) { flush(); out.push('<h4>' + inline(h[1]) + '</h4>'); }
      else if (!line.trim()) flush();
      else buf.push(line);
    });
    flush();
    return out.join('');
  }

  function renderCode(seg, opts) {
    opts = opts || {};
    const id = 'c' + (++codeSeq);
    codeStore[id] = { content: seg.content || '', language: seg.language || '', filename: seg.filename || '' };
    const lang = seg.language || 'code';
    const title = seg.filename ? esc(seg.filename) : esc(lang);
    const runnable = opts.canRun && /^(python|py)$/i.test(seg.language || '');
    return '<div class="code-card" data-code="' + id + '">' +
      '<div class="code-head"><b>' + title + '</b>' + (seg.filename ? '<span>' + esc(lang) + '</span>' : '') + '<span class="sp"></span>' +
      '<button type="button" data-act="copy">Copy</button>' +
      '<button type="button" data-act="save">Save</button>' +
      (runnable ? '<button type="button" data-act="run">Run</button>' : '') +
      '</div><pre><code>' + esc(seg.content) + '</code></pre></div>';
  }

  function renderSegment(seg, opts) {
    switch (seg.type) {
      case 'text': return renderText(seg.content);
      case 'code': return renderCode(seg, opts);
      case 'math': return '<div class="math-block">\\[' + escMath(seg.content) + '\\]</div>';
      case 'table':
        return '<div class="table-wrap"><table><thead><tr>' + (seg.header || []).map(function (h) { return '<th>' + inline(h) + '</th>'; }).join('') +
          '</tr></thead><tbody>' + (seg.rows || []).map(function (r) {
            return '<tr>' + r.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
          }).join('') + '</tbody></table></div>';
      case 'list': {
        const tag = seg.ordered ? 'ol' : 'ul';
        return '<' + tag + '>' + (seg.items || []).map(function (i) { return '<li>' + inline(i) + '</li>'; }).join('') + '</' + tag + '>';
      }
      case 'warning':
      case 'error': return '<div class="callout" role="status">' + inline(seg.content) + '</div>';
      case 'link': return '<p class="seg-text">' + inline(seg.content) + '</p>';
      default: return '';
    }
  }

  function renderResponse(resp, opts) {
    if (!resp || !resp.segments) return '';
    if (resp.response_type === 'clarification') {
      return '<div class="callout clarify">' + resp.segments.map(function (s) { return inline(s.content); }).join('<br>') + '</div>';
    }
    var body = resp.segments.map(function (s) { return renderSegment(s, opts); }).join('');
    var artifacts = resp.meta && Array.isArray(resp.meta.artifacts) ? resp.meta.artifacts : [];
    if (artifacts.length) body += artifacts.map(renderArtifact).join('');
    return body;
  }

  function buildPreviewDoc(bundle) {
    const files = bundle && Array.isArray(bundle.files) ? bundle.files : [];
    const index = files.find(function (f) { return String(f.path || '').toLowerCase() === 'index.html'; });
    if (!index) return '';
    let html = String(index.content || '');
    const css = files.filter(function (f) { return /\.css$/i.test(f.path || ''); }).map(function (f) { return String(f.content || ''); }).join('\n');
    const js = files.filter(function (f) { return /\.(js|mjs|ts)$/i.test(f.path || ''); }).map(function (f) { return String(f.content || ''); }).join('\n');
    if (css) {
      html = html.replace(/<link[^>]+href=["'][^"']+\.css[^"']*["'][^>]*>/gi, '');
      if (/<\/head>/i.test(html)) html = html.replace(/<\/head>/i, '<style>/* Astra artifact styles */\n' + css + '\n</style></head>');
      else html = '<style>' + css + '</style>' + html;
    }
    if (js) {
      html = html.replace(/<script[^>]+src=["'][^"']+\.(?:js|mjs|ts)[^"']*["'][^>]*>\s*<\/script>/gi, '');
      const script = '<script>\n' + js.replace(/<\/script/gi, '<\\/script') + '\n<\/script>';
      if (/<\/body>/i.test(html)) html = html.replace(/<\/body>/i, script + '</body>');
      else html += script;
    }
    return '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n' + html;
  }

  function renderArtifact(bundle) {
    const id = 'a' + (++codeSeq);
    const files = Array.isArray(bundle.files) ? bundle.files : [];
    artifactStore[id] = { bundle: bundle, previewDoc: buildPreviewDoc(bundle) };
    const fileRows = files.map(function (f, i) {
      const lang = esc(f.language || 'text');
      const name = esc(f.path || fileName(f));
      const content = esc(f.content || '');
      return '<details class="artifact-file" ' + (i === 0 ? 'open' : '') + '><summary><span class="artifact-file-name">' + name + '</span><span class="artifact-lang">' + lang + '</span></summary><div class="artifact-code"><button type="button" class="artifact-copy" data-artifact="' + id + '" data-file-index="' + i + '">Copy</button><pre><code>' + content + '</code></pre></div></details>';
    }).join('');
    const preview = bundle.preview ? '<div class="artifact-preview-wrap"><div class="artifact-toolbar"><span>LIVE PREVIEW</span><b>' + esc(bundle.entrypoint || 'index.html') + '</b></div><iframe class="artifact-preview" title="Generated application preview" sandbox="allow-scripts"></iframe></div>' : '';
    return '<section class="artifact-card" data-artifact-card="' + id + '">' +
      '<div class="artifact-head"><div><span>WORK PRODUCT</span><h4>' + esc(bundle.title || 'Generated artifact') + '</h4></div><div class="artifact-count">' + files.length + ' FILE' + (files.length === 1 ? '' : 'S') + '</div></div>' +
      preview + '<div class="artifact-files"><div class="artifact-toolbar"><span>FILES</span><b>COMPLETE OUTPUT</b></div>' + fileRows + '</div></section>';
  }

  function hydrateArtifacts(rootEl) {
    rootEl = rootEl || document;
    rootEl.querySelectorAll('.artifact-preview').forEach(function (frame) {
      const card = frame.closest('[data-artifact-card]');
      if (!card) return;
      const storeEntry = artifactStore[card.getAttribute('data-artifact-card')];
      if (storeEntry && storeEntry.previewDoc && !frame.srcdoc) frame.srcdoc = storeEntry.previewDoc;
    });
  }

  function fileName(entry) {
    if (entry.filename) return entry.filename.split('/').pop();
    return 'code.' + (EXT[(entry.language || '').toLowerCase()] || 'txt');
  }

  const api = { esc: esc, escMath: escMath, inline: inline, renderText: renderText, renderCode: renderCode,
                renderSegment: renderSegment, renderResponse: renderResponse, hydrateArtifacts: hydrateArtifacts, codeStore: codeStore, artifactStore: artifactStore, fileName: fileName };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NXRender = api;
})(typeof window !== 'undefined' ? window : globalThis);
