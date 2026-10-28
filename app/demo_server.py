'''
    Tiny web page for demo mode - see demo_printer_handler.py.  Stdlib only, dev use only, no auth.
'''
import collections
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

CONTENT_TYPES = {'pdf': 'application/pdf', 'zpl': 'text/plain; charset=utf-8', 'text': 'text/plain; charset=utf-8'}

# Pinned: the WASM must match the wasm_exec runtime bundled in the JS.  Renders entirely in the browser.
ZPL_RENDERER = 'https://cdn.jsdelivr.net/npm/zpl-renderer-js@4.0.0/dist'


class JobStore():
    def __init__(self, size):
        self.lock = threading.Lock()
        self.jobs = collections.deque(maxlen=size)

    def add(self, meta, data):
        with self.lock:
            self.jobs.appendleft((meta, data))

    def list(self):
        with self.lock:
            return [meta for meta, _ in self.jobs]

    def get(self, job_id):
        with self.lock:
            return next(((meta, data) for meta, data in self.jobs if meta['id'] == job_id), (None, None))

    def clear(self):
        with self.lock:
            self.jobs.clear()


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.debug(fmt % args)

        def _send(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self._send(PAGE.replace('{{ZPL_RENDERER}}', ZPL_RENDERER).encode(), 'text/html; charset=utf-8')
            elif self.path == '/api/jobs':
                self._send(json.dumps({'jobs': store.list(), 'max': store.jobs.maxlen}).encode(), 'application/json')
            elif self.path.startswith('/jobs/'):
                try:
                    meta, data = store.get(int(self.path.split('/')[2]))
                except ValueError:
                    meta, data = None, None
                if meta is None:
                    self._send(b'Not found (only the last few jobs are kept)', 'text/plain', 404)
                elif meta['kind'] == 'image':
                    self._send(data, 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg')
                else:
                    self._send(data, CONTENT_TYPES.get(meta['kind'], 'application/octet-stream'))
            else:
                self._send(b'Not found', 'text/plain', 404)

        def do_POST(self):
            if self.path == '/api/clear':
                store.clear()
                self._send(b'{}', 'application/json')
            else:
                self._send(b'Not found', 'text/plain', 404)

    return Handler


def start(store, host, port):
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name='demo-web', daemon=True).start()
    return server


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo printer</title>
<style>
  :root { --bg: #f4f4f5; --card: #fff; --text: #18181b; --muted: #71717a; --border: #e4e4e7; --accent: #2563eb;
          --new: #fef9c3; --error: #b91c1c; --code-bg: #f4f4f5; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #18181b; --card: #27272a; --text: #f4f4f5; --muted: #a1a1aa; --border: #3f3f46; --accent: #60a5fa;
            --new: #3f3a12; --error: #f87171; --code-bg: #18181b; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.4 system-ui, -apple-system, sans-serif; }
  header { position: sticky; top: 0; z-index: 1; display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
           padding: 12px 16px; background: var(--card); border-bottom: 1px solid var(--border); }
  header h1 { font-size: 16px; margin: 0 auto 0 0; }
  header label { color: var(--muted); font-size: 13px; }
  select, button { font: inherit; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border);
                   background: var(--card); color: var(--text); }
  button { cursor: pointer; }
  #status { color: var(--muted); font-size: 13px; }
  main { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 420px), 1fr)); gap: 16px; padding: 16px; }
  .job { background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
         display: flex; flex-direction: column; }
  .job.fresh { animation: fresh 4s ease-out; }
  @keyframes fresh { from { background: var(--new); } to { background: var(--card); } }
  .meta { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; padding: 10px 12px;
          border-bottom: 1px solid var(--border); }
  .meta b { font-size: 15px; }
  .tag { font-size: 12px; padding: 1px 6px; border-radius: 4px; background: var(--code-bg); color: var(--muted); }
  .tag.kind { color: var(--accent); font-weight: 600; text-transform: uppercase; }
  .meta .right { margin-left: auto; display: flex; gap: 8px; }
  .meta a { color: var(--accent); font-size: 13px; text-decoration: none; }
  .body { padding: 12px; display: flex; flex-direction: column; gap: 12px; align-items: center; }
  .body iframe { width: 100%; height: 560px; border: 0; background: #fff; }
  .body img { max-width: 100%; height: auto; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.25); image-rendering: pixelated; }
  .body pre { width: 100%; margin: 0; max-height: 300px; overflow: auto; padding: 8px; background: var(--code-bg);
              border-radius: 6px; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
  .error { color: var(--error); font-size: 13px; }
  .empty { grid-column: 1 / -1; text-align: center; color: var(--muted); padding: 64px 16px; }
</style>
</head>
<body>
<header>
  <h1>Demo printer</h1>
  <label>Label size
    <select id="size">
      <option value="101.6x152.4">4 × 6 in</option>
      <option value="100x150">100 × 150 mm</option>
      <option value="101.6x101.6">4 × 4 in</option>
      <option value="105x148">A6</option>
      <option value="76.2x50.8">3 × 2 in</option>
      <option value="50.8x25.4">2 × 1 in</option>
    </select>
  </label>
  <label>Resolution
    <select id="dpmm">
      <option value="8">203 dpi</option>
      <option value="12">300 dpi</option>
      <option value="24">600 dpi</option>
    </select>
  </label>
  <button id="clear">Clear</button>
  <span id="status">Connecting…</span>
</header>
<main id="jobs"><div class="empty">Nothing printed yet. Print to a demo printer from the OMS and it'll show up here.</div></main>

<script type="module">
const RENDERER = '{{ZPL_RENDERER}}';
const jobsEl = document.getElementById('jobs');
const statusEl = document.getElementById('status');
const sizeEl = document.getElementById('size');
const dpmmEl = document.getElementById('dpmm');
const cards = new Map();   // id -> element
let firstLoad = true;
let unseen = 0;

const store = {
  get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
};
for (const [el, key] of [[sizeEl, 'demo-size'], [dpmmEl, 'demo-dpmm']]) {
  const saved = store.get(key);
  if (saved && [...el.options].some((o) => o.value === saved)) el.value = saved;
  el.addEventListener('change', () => { store.set(key, el.value); rerenderZpl(); });
}

let zplApi = null;
const zpl = () => {
  if (!zplApi) {
    zplApi = import(`${RENDERER}/index.external.esm.js`)
      .then((mod) => mod.init({ wasmUrl: `${RENDERER}/zebrash.wasm` }).then(() => mod));
    zplApi.catch(() => { zplApi = null; });
  }
  return zplApi;
};

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v; else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
};

const formatSize = (bytes) => (bytes > 1024 * 1024 ? `${(bytes / 1048576).toFixed(1)} MB`
  : bytes > 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`);

async function renderZpl(card) {
  const body = card.querySelector('.body');
  const source = card.dataset.zpl;
  const [width, height] = sizeEl.value.split('x').map(Number);
  body.replaceChildren(el('span', { class: 'tag' }, 'Rendering…'));
  try {
    const mod = await zpl();
    const labels = await mod.zplToBase64MultipleAsync(source, width, height, Number(dpmmEl.value));
    body.replaceChildren(...labels.map((png, i) => el('img', { src: `data:image/png;base64,${png}`, alt: `Label ${i + 1}` })));
    if (labels.length > 1) body.prepend(el('span', { class: 'tag' }, `${labels.length} labels`));
  } catch (error) {
    body.replaceChildren(el('div', { class: 'error' }, `Couldn't render ZPL (${error.message || error}). Showing source.`));
  }
  const details = el('details', {}, el('summary', {}, 'ZPL source'), el('pre', {}, source));
  details.style.width = '100%';
  body.append(details);
}

function rerenderZpl() {
  for (const card of cards.values()) if (card.dataset.zpl) renderZpl(card);
}

async function buildCard(job) {
  const time = new Date(job.ts * 1000);
  const options = Object.entries(job.options || {}).map(([k, v]) => `${k}=${v}`).join(' ');
  const card = el('article', { class: firstLoad ? 'job' : 'job fresh' },
    el('div', { class: 'meta' },
      el('b', {}, `#${job.id}`),
      el('span', { class: 'tag kind' }, job.kind),
      el('span', {}, job.printer),
      job.raw ? el('span', { class: 'tag' }, 'raw') : null,
      job.test ? el('span', { class: 'tag' }, 'test page') : null,
      options ? el('span', { class: 'tag' }, options) : null,
      el('span', { class: 'right' },
        el('span', { class: 'tag', title: time.toLocaleString() }, `${time.toLocaleTimeString()} · ${formatSize(job.size)}`),
        el('a', { href: `/jobs/${job.id}`, target: '_blank' }, 'Open'))),
    el('div', { class: 'body' }));
  const body = card.querySelector('.body');
  if (job.kind === 'pdf') {
    body.append(el('iframe', { src: `/jobs/${job.id}#view=FitH`, loading: 'lazy', title: `Job ${job.id}` }));
  } else if (job.kind === 'image') {
    body.append(el('img', { src: `/jobs/${job.id}`, alt: `Job ${job.id}` }));
  } else {
    const text = await fetch(`/jobs/${job.id}`).then((r) => r.text());
    if (job.kind === 'zpl') {
      card.dataset.zpl = text;
      renderZpl(card);
    } else {
      body.append(el('pre', {}, text));
    }
  }
  return card;
}

async function poll() {
  let data;
  try {
    data = await fetch('/api/jobs', { cache: 'no-store' }).then((r) => r.json());
    statusEl.textContent = `Showing last ${data.max} jobs · live`;
  } catch (e) {
    statusEl.textContent = 'Client not running - retrying…';
    return;
  }
  const ids = new Set(data.jobs.map((job) => job.id));
  for (const [id, card] of cards) {
    if (!ids.has(id)) { card.remove(); cards.delete(id); }
  }
  const fresh = data.jobs.filter((job) => !cards.has(job.id)).reverse();   // oldest first, each goes on top
  for (const job of fresh) {
    const card = await buildCard(job);
    cards.set(job.id, card);
    jobsEl.prepend(card);
  }
  if (fresh.length && !firstLoad) {
    if (document.hidden) unseen += fresh.length;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  document.title = unseen ? `(${unseen}) Demo printer` : 'Demo printer';
  const empty = jobsEl.querySelector('.empty');
  if (empty) empty.hidden = cards.size > 0;
  firstLoad = false;
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) { unseen = 0; document.title = 'Demo printer'; } });
document.getElementById('clear').addEventListener('click', async () => {
  await fetch('/api/clear', { method: 'POST' });
  poll();
});

async function loop() {
  await poll();
  setTimeout(loop, 1000);
}
loop();
</script>
</body>
</html>
'''
