// Media Studio's screen: the trips, one trip's timeline with its sidebar, and the full-screen viewer.

const $ = (id) => document.getElementById(id);
const SOURCES = { mine: '我拍的', received: '收到的', screenshot: '截图' };
const FILTERS = [['all', '全部'], ['mine', '我拍的'], ['received', '收到的'], ['screenshot', '截图']];
const PICKS = [['all', '全部'], ['none', '未选'], ['yes', '要'], ['no', '不要']];
const SUBJECTS = [['all', '全部'], ['portrait', '人像'], ['landscape', '风景'], ['video', '视频']];
const SUBJECT_NAMES = { portrait: '人像', landscape: '风景' };
const FORMATS = {
  webp: { name: 'WebP', says: '放网站用：每张三种大小，文件小。' },
  jpeg: { name: 'JPEG', says: '分享、存档用：原尺寸一张，哪里都能打开。放在 jpeg 文件夹。' },
};
const SAVE_FAILED = (error) => `没存上（${error.message}）。关掉 Media Studio 再双击 start.cmd 打开试试。`;

const state = {
  trip: null, view: null, list: [], cards: [], at: 0, mode: 'photos', looks: null,
  filter: remembered('filter', 'all'), picks: remembered('picks', 'all'), subject: remembered('subject', 'all'),
  lookFor: 'landscape', stacked: remembered('stacked', 'yes') === 'yes', details: remembered('details', 'no') === 'yes',
};

function remembered(key, fallback) {
  try { return localStorage.getItem(`studio.${key}`) ?? fallback; } catch { return fallback; }
}
function remember(key, value) {
  try { localStorage.setItem(`studio.${key}`, value); } catch { /* a convenience only */ }
}

async function get(url) {
  const answer = await fetch(url);
  if (!answer.ok) throw new Error((await answer.json().catch(() => ({}))).error || `${answer.status}`);
  return answer.json();
}
async function post(url, body) {
  const answer = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!answer.ok) throw new Error((await answer.json().catch(() => ({}))).error || `${answer.status}`);
  return answer.json();
}
const q = (path, id) => `${path}?trip=${encodeURIComponent(state.trip)}&id=${encodeURIComponent(id)}`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  // src goes last, after any load listener, or a picture already in the cache can land before anyone listens.
  const { src, ...rest } = attrs;
  for (const [k, v] of Object.entries(src === undefined ? rest : { ...rest, src })) {
    if (v === false || v == null) continue;
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}
// replaceChildren that skips the false and null an `a && b` leaves behind, so they never show as text.
const fill = (node, ...children) => node.replaceChildren(...children.filter((c) => c != null && c !== false));
const dots = () => el('span', { class: 'dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i'));

// The window stays alive while it pings; the server stops itself some minutes after the last one.
setInterval(() => fetch('/api/ping').catch(() => {}), 20000);

// ---- times, as the camera recorded them (the place's own local time)

function clock(when) {
  const [, m, d, hh, mm] = when.match(/^\d{4}-(\d\d)-(\d\d)T(\d\d):(\d\d)/);
  return `${+m}月${+d}日 ${hh}:${mm}`;
}
function length(seconds) {
  const s = Math.round(seconds || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// A problem shows where the eyes are: over the viewer when it's open, else in the corner of the page. It fades on
// its own after a while.
function alarm(message) {
  const where = $('loupe').open ? $('dock') : $('toast');
  const note = el('p', { class: 'alarm', role: 'alert' }, message);
  where.prepend(note);
  setTimeout(() => note.remove(), 8000);
}

// ---- trips

async function showTrips() {
  state.trip = null;
  state.view = null;
  state.mode = 'photos';
  fill($('side'), el('div', { class: 'brand' }, 'MEDIA STUDIO'));
  const { trips, folder } = await get('/api/trips');
  const welcome = el('section', { class: 'welcome' }, el('h1', {}, '旅行'));
  if (!trips.length) {
    welcome.append(el('p', {}, '还没有旅行。在 ', el('code', {}, folder), ' 里建一个文件夹（比如「2026-10 Yunnan」），把照片和视频放进它的 ', el('code', {}, 'originals'), ' 文件夹，再打开这里。'));
  } else {
    welcome.append(el('p', {}, '选一次旅行，开始选片。'), el('div', { class: 'trips' }, ...trips.map((t) =>
      el('button', { type: 'button', class: 'trip', disabled: !t.ready, onclick: () => openTrip(t.name) },
        el('strong', {}, t.name), el('span', {}, t.ready ? '打开 ›' : '里面还没有 originals 文件夹')))));
  }
  fill($('main'), welcome);
}

// ---- one trip

async function openTrip(name) {
  state.trip = name;
  fill($('side'), el('div', { class: 'brand' }, 'MEDIA STUDIO'));
  fill($('main'), el('p', { class: 'empty' }, '正在读取文件…'));
  state.view = await post('/api/refresh', { trip: name });
  render();
  follow();
}

// A fresh answer from the server updates the file objects already on the page instead of replacing them, so the
// cards, the viewer's list and the picks all keep pointing at the same objects.
function adopt(view) {
  const known = new Map((state.view?.items || []).map((i) => [i.id, i]));
  view.items = view.items.map((fresh) => (known.has(fresh.id) ? Object.assign(known.get(fresh.id), fresh) : fresh));
  state.view = view;
}

// While thumbnails are being made, keep asking; show each one as it lands, then lay the page out again.
async function follow() {
  const trip = state.trip;
  const busy = () => state.view.progress.running || state.view.export.running;
  // An export alone doesn't change the photos, so the page isn't redrawn after it, only the sidebar's foot.
  const scanned = state.view.progress.running;
  while (state.trip === trip && busy()) {
    await new Promise((r) => setTimeout(r, 1000));
    if (state.trip !== trip) return;
    const view = await get(`/api/trip?trip=${encodeURIComponent(trip)}`);
    const hadThumb = new Map(state.view.items.map((i) => [i.id, i.thumb]));
    const wasScanning = state.view.progress.total === 0;
    adopt(view);
    if (wasScanning && view.progress.total > 0) render();
    for (const item of view.items) if (item.thumb && hadThumb.get(item.id) === false) showThumb(item.id);
    status();
  }
  if (state.trip === trip) (scanned ? render : status)();
}

function showThumb(id) {
  for (const img of document.querySelectorAll(`img[data-id="${CSS.escape(id)}"]`)) {
    if (!img.getAttribute('src')) img.src = `${q('/thumb', id)}`;
  }
}

// ---- the sidebar: the trip, every filter with its count, the tools, and the export at the foot

function side() {
  fill($('side'),
    el('button', { type: 'button', class: 'back', onclick: showTrips }, '‹ 所有旅行'),
    el('div', { class: 'trip-head' }, el('b', {}, state.trip), el('span', { id: 'trip-sum' })),
    el('div', { id: 'side-groups', class: 'side-groups' }),
    el('div', { class: 'grow' }),
    el('div', { class: 'progress', id: 'side-progress', role: 'progressbar', 'aria-valuemin': '0', hidden: true },
      el('div', {}, el('span'), el('b')), el('div', { class: 'track' }, el('i'))),
    el('div', { class: 'foot', id: 'side-foot' }));
  filters();
  status();
}

function group(title, options, current, counts, choose) {
  return el('nav', { class: 'group', role: 'radiogroup', 'aria-label': title }, el('h3', {}, title), ...options.map(([key, label]) =>
    el('button', { type: 'button', class: 'item', role: 'radio', 'aria-checked': String(current === key), onclick: () => choose(key) },
      el('span', {}, label), el('i', {}, String(counts[key] || 0)))));
}

function filters() {
  const box = $('side-groups');
  if (!box) return;
  const items = state.view.items;
  const bySource = { all: items.length };
  for (const item of items) bySource[item.source] = (bySource[item.source] || 0) + 1;
  const inSource = items.filter((i) => state.filter === 'all' || i.source === state.filter);
  const picked = { all: inSource.length, none: 0, yes: 0, no: 0 };
  for (const item of inSource) picked[item.pick || 'none'] += 1;
  const bySubject = { all: inSource.length, portrait: 0, landscape: 0, video: 0 };
  for (const item of inSource) bySubject[item.kind === 'video' ? 'video' : item.subject] += 1;
  const looks = state.view.looks;
  const looking = state.mode === 'looks';
  fill(box,
    !looking && group('来源', FILTERS.filter(([k]) => k !== 'screenshot' || bySource.screenshot), state.filter, bySource, (k) => { state.filter = k; remember('filter', k); render(); }),
    !looking && group('选片', PICKS, state.picks, picked, (k) => { state.picks = k; remember('picks', k); render(); }),
    !looking && group('类型', SUBJECTS, state.subject, bySubject, (k) => { state.subject = k; remember('subject', k); render(); }),
    el('nav', { class: 'group', 'aria-label': '工具' }, el('h3', {}, '工具'),
      el('button', { type: 'button', class: 'item', 'aria-pressed': String(looking), onclick: toggleLooks },
        el('span', {}, looking ? '‹ 回到照片' : '风格'), el('i', {}, `${looks.landscape || '原图'} · ${looks.portrait || '原图'}`)),
      !looking && el('button', { type: 'button', class: 'item', 'aria-pressed': String(state.stacked),
        onclick: () => { state.stacked = !state.stacked; remember('stacked', state.stacked ? 'yes' : 'no'); render(); } },
        el('span', {}, '相似的叠在一起'), el('span', { class: 'switch' })),
      el('button', { type: 'button', class: 'item', onclick: () => begin('/api/refresh') },
        el('span', {}, '重新扫描'), el('i', {}, '新文件'))));
}

function status() {
  const foot = $('side-foot');
  if (!foot) return;
  const { progress, items, stacks, export: out, days } = state.view;
  $('trip-sum').textContent = `${items.length} 个 · ${days.length} 天 · ${stacks} 组相似`;
  const kept = items.filter((i) => i.pick === 'yes' && i.kind === 'photo').length;
  const clips = items.filter((i) => i.pick === 'yes' && i.kind === 'video').length;
  if (progress.running) showProgress(progress.total ? '缩略图' : '正在读取文件', progress.done, progress.total);
  else if (out.running) showProgress('导出', out.done, out.total);
  else finishProgress();
  const formats = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '导出格式' },
    ...Object.keys(FORMATS).map((key) => el('button', { type: 'button', role: 'radio', 'aria-checked': String(out.format === key),
      disabled: out.running, onclick: () => setFormat(key) }, FORMATS[key].name)));
  fill(foot,
    el('div', { class: 'format' }, formats, el('p', {}, FORMATS[out.format].says)),
    el('button', { type: 'button', class: 'export', disabled: !(kept || clips) || out.running,
      onclick: (e) => { e.currentTarget.disabled = true; begin('/api/export'); } },
      el('b', {}, kept || clips ? `导出 ${kept + clips} 个` : '导出'),
      el('small', {}, kept || clips ? `${kept} 张照片 · ${FORMATS[out.format].name}${clips ? ` + ${clips} 段视频` : ''}` : '先用 Z 标出要的照片和视频')),
    out.ready && !out.running && el('button', { type: 'button', class: 'link', onclick: () => post('/api/open-export', { trip: state.trip }) },
      out.failed ? `打开导出文件夹（${out.failed} 个失败）` : '打开导出文件夹 ›'));
}

async function setFormat(key) {
  const before = state.view.export.format;
  state.view.export.format = key;
  status();
  try {
    await post('/api/export-format', { trip: state.trip, format: key });
  } catch (error) {
    state.view.export.format = before;
    status();
    alarm(SAVE_FAILED(error));
  }
}

// The bar stays one element while work runs, so its fill slides from one count to the next. With no total yet, a
// short piece drifts back and forth instead.
let progressGone = null;

function showProgress(label, done, total) {
  const bar = $('side-progress');
  clearTimeout(progressGone);
  bar.hidden = false;
  bar.classList.remove('finished');
  bar.classList.toggle('waiting', !total);
  bar.setAttribute('aria-label', label);
  bar.setAttribute('aria-valuemax', String(total));
  bar.setAttribute('aria-valuenow', String(done));
  bar.querySelector('span').textContent = label;
  bar.querySelector('b').textContent = total ? `${done} / ${total}` : '';
  bar.querySelector('i').style.width = total ? `${(done / total) * 100}%` : '';
}

// When the work is done the bar fills up, says so, and fades away.
function finishProgress() {
  const bar = $('side-progress');
  if (bar.hidden || bar.classList.contains('finished')) return;
  bar.classList.remove('waiting');
  bar.classList.add('finished');
  bar.querySelector('b').textContent = '完成';
  bar.querySelector('i').style.width = '100%';
  progressGone = setTimeout(() => { bar.hidden = true; }, 1800);
}

// Starts a scan or an export on the server, then follows its progress in the sidebar.
async function begin(url) {
  try {
    adopt(await post(url, { trip: state.trip }));
  } catch (error) {
    alarm(`没能开始（${error.message}）。关掉 Media Studio 再双击 start.cmd 打开试试。`);
  }
  status();
  follow();
}

function toggleLooks() {
  state.mode = state.mode === 'looks' ? 'photos' : 'looks';
  window.scrollTo({ top: 0, behavior: 'instant' });
  render();
}

// ---- the timeline

const shows = (item) => (state.filter === 'all' || item.source === state.filter) &&
  (state.picks === 'all' || (state.picks === 'none' ? !item.pick : item.pick === state.picks)) &&
  (state.subject === 'all' || (state.subject === 'video' ? item.kind === 'video' : item.subject === state.subject));

// Cards: one per file, or one per stack of look-alikes (at the place of its first file).
function cards() {
  const shown = state.view.items.filter(shows);
  const out = [];
  const byStack = new Map();
  for (const item of shown) {
    if (state.stacked && item.stack != null) {
      if (byStack.has(item.stack)) { byStack.get(item.stack).members.push(item); continue; }
      const card = { members: [item] };
      byStack.set(item.stack, card);
      out.push(card);
    } else out.push({ members: [item] });
  }
  return out;
}

function render() {
  side();
  if (state.mode === 'looks') { renderLooks(); return; }
  const focused = document.activeElement?.dataset?.first;
  const list = cards();
  const showing = $('loupe').open ? state.list[state.at] : null;
  state.cards = list;
  state.list = list.flatMap((c) => c.members);
  // The viewer stays on the file it shows, wherever the new layout puts it.
  if (showing) {
    const at = state.list.findIndex((i) => i.id === showing.id);
    if (at >= 0) state.at = at; else closeLoupe();
  }
  const days = new Map();
  for (const card of list) {
    const key = card.members[0].day ?? 'none';
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(card);
  }
  const labels = new Map(state.view.days.map((d) => [d.day, d.label]));
  const sections = [...days].map(([day, dayCards]) => {
    const files = dayCards.reduce((n, c) => n + c.members.length, 0);
    const videos = dayCards.reduce((n, c) => n + c.members.filter((m) => m.kind === 'video').length, 0);
    const head = day === 'none'
      ? el('div', { class: 'day-head' }, el('h2', {}, '没有拍摄时间'), el('p', {}, '发送它们的 App 把时间删掉了，多半是收到的。'))
      : el('div', { class: 'day-head' }, el('h2', {}, labels.get(day) || day), el('span', {}, `${files} 个${videos ? `，其中 ${videos} 段视频` : ''}`));
    return el('section', { class: 'day' }, head, el('div', { class: 'rows' }, ...dayCards.map(cardFor)));
  });
  fill($('main'), ...(sections.length ? sections : [el('p', { class: 'empty' }, '这一类里没有文件。')]));
  if (focused) document.querySelector(`.card[data-first="${CSS.escape(focused)}"]`)?.focus();
}

const ROW_HEIGHT = 200;

function cardFor(card) {
  const first = card.members[0];
  const stack = card.members.length > 1;
  const what = first.source === 'screenshot' ? '截图' : `${SOURCES[first.source]}${first.kind === 'video' ? '视频' : '照片'}`;
  const label = `${what}${first.when ? `，${clock(first.when)}` : ''}${stack ? `，相似的 ${card.members.length} 个` : ''}`;
  const yes = card.members.filter((m) => m.pick === 'yes').length;
  const allNo = card.members.every((m) => m.pick === 'no');
  // Each photo keeps its own shape: its width in the row follows its proportions.
  const ratio = first.width && first.height ? Math.min(3, Math.max(0.4, first.width / first.height)) : 1;
  const img = el('img', { alt: '', 'data-id': first.id, loading: 'lazy', decoding: 'async', onload: (e) => e.target.classList.add('ready') });
  if (first.thumb) img.src = q('/thumb', first.id);
  const marks = `${yes ? `，要了 ${yes} 个` : ''}${allNo ? '，不要' : ''}`;
  return el('button', { type: 'button', class: `card${allNo ? ' no' : ''}${yes ? ' yes' : ''}`, style: `flex-basis:${Math.round(ROW_HEIGHT * ratio)}px`,
    'data-first': first.id, 'aria-label': label + marks, onclick: () => openLoupe(state.list.indexOf(first)) },
    img,
    first.source !== 'mine' && el('span', { class: `chip source ${first.source}` }, first.source === 'received' ? '收到' : '截图'),
    stack && el('span', { class: 'chip count' }, `${card.members.length}`),
    first.kind === 'video' && el('span', { class: 'chip length' }, length(first.duration)),
    // A dropped card says so by going grey; only keeps get a mark, with how many of a stack were kept.
    yes > 0 && el('span', { class: 'chip mark' }, stack ? `✓ ${yes}` : '✓'),
    first.error && el('span', { class: 'chip broken', title: first.error }, '读不了'));
}

// ---- picks: Z keep, X drop, the same key again to take it back. On a card in the grid they cover every file in
// the card (a whole stack at once); in the viewer, only the photo on show.

async function mark(items, pick) {
  const before = items.map((i) => [i, i.pick]);
  for (const i of items) i.pick = pick;
  showMarks(items);
  let failed = null;
  try {
    await post('/api/mark', { trip: state.trip, ids: items.map((i) => i.id), pick });
  } catch (error) {
    for (const [i, old] of before) i.pick = old;
    failed = error;
  }
  showMarks(items);
  if (failed) alarm(SAVE_FAILED(failed));
}

// Redraw only the cards those files are in, so the page doesn't jump while picking.
function showMarks(items) {
  const focused = document.activeElement?.dataset?.first;
  for (const card of state.cards) {
    if (!card.members.some((m) => items.includes(m))) continue;
    const old = document.querySelector(`.card[data-first="${CSS.escape(card.members[0].id)}"]`);
    if (!old) continue;
    const fresh = cardFor(card);
    old.replaceWith(fresh);
    if (focused === card.members[0].id) fresh.focus();
  }
  filters();
  status();
  if ($('loupe').open) info(state.list[state.at]);
}

// Keep or drop (or take it back, when it's already so), from a key or a button; in the viewer a new choice moves on
// to the next file.
function choose(items, pick, viewing) {
  const undo = items.every((i) => i.pick === pick);
  mark(items, undo ? null : pick);
  if (viewing && !undo) step(1);
}

function keepOnly(item) {
  // Keep this one, drop the rest of its stack: the quick way through a run of near-identical shots.
  const others = state.view.items.filter((i) => i.stack === item.stack && i.id !== item.id);
  mark([item], 'yes');
  mark(others, 'no');
}

// T swaps portrait and landscape when the guess is wrong.
async function swapSubject(items) {
  const photos = items.filter((i) => i.subject);
  if (!photos.length) return;
  const to = photos[0].subject === 'portrait' ? 'landscape' : 'portrait';
  const before = photos.map((i) => [i, i.subject, i.subject_reason]);
  for (const i of photos) Object.assign(i, { subject: to, subject_reason: '你改的' });
  showMarks(photos);
  try {
    await post('/api/subject', { trip: state.trip, ids: photos.map((i) => i.id), subject: to });
    // Portraits are coloured more lightly, so the preview changes with the subject.
    if ($('loupe').open && photos.includes(state.list[state.at])) refreshPreview(state.list[state.at]);
  } catch (error) {
    for (const [i, s, r] of before) Object.assign(i, { subject: s, subject_reason: r });
    showMarks(photos);
    alarm(SAVE_FAILED(error));
  }
}

const KEYS = { KeyZ: 'yes', KeyX: 'no' };

// Keys are heard on the whole page, not on whatever has focus: clicking a picture in the viewer's strip redraws the
// bar and drops the focus, and the arrows must keep working after it.
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey || !state.view || ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
  if ($('peek').open) return peekKeys(e);
  const viewing = $('loupe').open;
  if (viewing && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.target.tagName !== 'VIDEO') {
    e.preventDefault();
    return step(e.key === 'ArrowLeft' ? -1 : 1);
  }
  if (viewing && e.code === 'KeyI' && !e.repeat) { e.preventDefault(); return toggleDetails(); }
  const items = viewing ? [state.list[state.at]].filter(Boolean)
    : state.cards.find((c) => c.members[0].id === e.target.dataset?.first)?.members;
  if (!items?.length) return;
  if (e.code === 'KeyT') { e.preventDefault(); return swapSubject(items); }
  if (viewing && e.code === 'KeyO' && !e.repeat) { e.preventDefault(); return showPlain(true); }
  if (viewing && e.code === 'KeyS' && items[0].clip) { e.preventDefault(); return setClipStart(items[0]); }
  const pick = KEYS[e.code];
  if (!pick) return;
  e.preventDefault();
  // Holding the key down must not run through the photos.
  if (e.repeat) return;
  if (viewing && e.code === 'KeyZ' && e.shiftKey && items[0].stack != null) return keepOnly(items[0]);
  choose(items, pick, viewing);
});
document.addEventListener('keyup', (e) => { if (e.code === 'KeyO' && $('loupe').open) showPlain(false); });

// Arrow keys move between cards the way they sit on screen.
$('main').addEventListener('keydown', (e) => {
  if (!e.target.classList?.contains('card') || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
  const all = [...document.querySelectorAll('.card')];
  const at = all.indexOf(e.target);
  let to = null;
  if (e.key === 'ArrowLeft') to = all[at - 1];
  else if (e.key === 'ArrowRight') to = all[at + 1];
  else {
    const here = e.target.getBoundingClientRect();
    const down = e.key === 'ArrowDown';
    let best = Infinity;
    for (const card of all) {
      const box = card.getBoundingClientRect();
      const rows = down ? box.top - here.top : here.top - box.top;
      if (rows < 4) continue;
      const score = rows * 10 + Math.abs(box.left + box.width / 2 - here.left - here.width / 2);
      if (score < best) { best = score; to = card; }
    }
  }
  if (to) { e.preventDefault(); to.focus(); to.scrollIntoView({ block: 'nearest' }); }
});

// ---- looks: each look on a dozen of the trip's photos, side by side; landscapes and portraits each get one

const LOOK_COLUMNS = () => [{ id: null, name: '原图', idea: '照片本来的样子，不加风格。' }, ...state.looks];

// The photos to judge on: kept ones if there are enough, else the whole trip; one per stack, spread over the days.
function samples(count = 12) {
  const photos = state.view.items.filter((i) => i.kind === 'photo' && i.source === 'mine' && !i.error && i.subject === state.lookFor);
  const kept = photos.filter((i) => i.pick === 'yes');
  const pool = kept.length >= count ? kept : photos;
  const seen = new Set();
  const single = pool.filter((i) => i.stack == null || (!seen.has(i.stack) && seen.add(i.stack)));
  if (single.length <= count) return single;
  return Array.from({ length: count }, (_, k) => single[Math.floor((k + 0.5) * single.length / count)]);
}

async function renderLooks() {
  if (!state.looks) state.looks = (await get('/api/looks')).looks;
  const columns = LOOK_COLUMNS();
  state.samples = samples();
  const current = state.view.looks[state.lookFor] ?? null;
  const tabs = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '给哪一类挑风格' },
    ...[['landscape', '风景'], ['portrait', '人像']].map(([key, label]) =>
      el('button', { type: 'button', role: 'radio', 'aria-checked': String(state.lookFor === key), onclick: () => { state.lookFor = key; renderLooks(); } },
        `${label} · ${state.view.looks[key] || '原图'}`)));
  const head = columns.map((c) => el('div', { class: `look-head${c.id === current ? ' current' : ''}` },
    el('b', {}, c.id ? `${c.id} ${c.name}` : c.name),
    el('p', {}, c.idea),
    el('button', { type: 'button', class: 'pill-btn keep', 'aria-pressed': String(c.id === current), disabled: c.id === current, onclick: () => useLook(c.id) },
      c.id === current ? '正在用' : c.id ? '用这个' : '不用风格')));
  const rows = state.samples.flatMap((item, row) => columns.map((c, col) =>
    el('button', { type: 'button', class: `look-cell${c.id === current ? ' current' : ''}`, 'aria-label': `${c.name}：${item.file}`, onclick: () => openPeek(row, col) },
      // Not lazy: the table is redrawn while pictures arrive, and lazy pictures in a redrawn table can stall.
      el('img', { alt: '', decoding: 'async', src: lookUrl(item, c.id), onload: (e) => e.target.classList.add('ready') }))));
  const whose = state.samples.length && state.samples.every((i) => i.pick === 'yes') ? '你要了的' : '这次旅行的';
  const gentle = state.lookFor === 'portrait' ? '人像的风格只用四成力度，肤色保持自然。' : '';
  fill($('main'),
    el('div', { class: 'looks-head' }, el('h1', {}, '风格'), tabs),
    el('p', { class: 'looks-note' }, `${state.samples.length} 张${whose}${SUBJECT_NAMES[state.lookFor]}照片，每一列是一种风格。${gentle}点任何一张放大，用 ← → 切换对比。`),
    el('div', { class: 'looks' }, ...head, ...rows));
}

const lookUrl = (item, lookId) => `${q('/look', item.id)}&look=${lookId ?? ''}&for=${state.lookFor}`;

async function useLook(lookId) {
  try {
    state.view.looks = (await post('/api/look', { trip: state.trip, for: state.lookFor, look: lookId })).looks;
  } catch (error) {
    return alarm(SAVE_FAILED(error));
  }
  if ($('peek').open) showPeek();
  filters();
  renderLooks();
}

const peek = { row: 0, col: 0 };

function openPeek(row, col) {
  Object.assign(peek, { row, col });
  document.documentElement.style.overflow = 'hidden';
  $('peek').showModal();
  $('peek').focus();
  showPeek();
}

function showPeek() {
  const columns = LOOK_COLUMNS();
  const item = state.samples[peek.row];
  const look = columns[peek.col];
  $('peek-img').src = lookUrl(item, look.id);
  $('peek-name').textContent = look.id ? `${look.id} ${look.name}` : look.name;
  $('peek-file').textContent = `${item.file} · ${peek.row + 1} / ${state.samples.length}`;
  const current = (state.view.looks[state.lookFor] ?? null) === look.id;
  $('peek-use').disabled = current;
  $('peek-use').textContent = current ? '正在用' : look.id ? '用这个风格' : '不用风格';
  // The neighbours load now, so switching is instant.
  for (const c of columns) new Image().src = lookUrl(item, c.id);
}

function peekKeys(e) {
  const columns = LOOK_COLUMNS().length;
  const moves = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] };
  if (moves[e.key]) {
    e.preventDefault();
    peek.row = (peek.row + moves[e.key][0] + state.samples.length) % state.samples.length;
    peek.col = (peek.col + moves[e.key][1] + columns) % columns;
    showPeek();
  }
  if (e.key === 'Enter') { e.preventDefault(); useLook(LOOK_COLUMNS()[peek.col].id); }
}
$('peek').addEventListener('close', () => { document.documentElement.style.overflow = ''; });
$('peek').addEventListener('click', (e) => { if (e.target === $('peek') || e.target === $('peek-img')) $('peek').close(); });
$('peek-close').addEventListener('click', () => $('peek').close());
$('peek-use').addEventListener('click', () => useLook(LOOK_COLUMNS()[peek.col].id));

// ---- the viewer: the photo alone on the screen; its choices in one floating bar at the bottom

const zoom = { s: 1, x: 0, y: 0 };

function openLoupe(index) {
  state.at = index;
  // The page behind stays put while the viewer is open.
  document.documentElement.style.overflow = 'hidden';
  $('loupe').showModal();
  // The viewer itself takes the focus, not its first button, so no focus ring shows while keys are used.
  $('loupe').focus();
  showItem();
}

function closeLoupe() {
  const box = $('loupe');
  const item = state.list[state.at];
  // Back to the card the photo belongs to: its own, or its stack's, whose first photo leads the stack.
  const first = state.stacked && item?.stack != null ? state.list.find((i) => i.stack === item.stack) : item;
  const done = () => {
    box.classList.remove('closing');
    box.close();
    document.documentElement.style.overflow = '';
    $('stage').replaceChildren();
    if (first) document.querySelector(`.card[data-first="${CSS.escape(first.id)}"]`)?.focus();
  };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return done();
  box.classList.add('closing');
  box.addEventListener('animationend', done, { once: true });
}

function setZoom(s, x, y) {
  const stage = $('stage');
  const media = stage.querySelector('img, video');
  zoom.s = Math.min(6, Math.max(1, s));
  const w = stage.clientWidth;
  const h = stage.clientHeight;
  zoom.x = Math.min(0, Math.max(w - w * zoom.s, x));
  zoom.y = Math.min(0, Math.max(h - h * zoom.s, y));
  if (zoom.s === 1) { zoom.x = 0; zoom.y = 0; }
  if (media) media.style.transform = `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.s})`;
  stage.classList.toggle('zoomed', zoom.s > 1);
}

function showItem() {
  const item = state.list[state.at];
  if (!item) return;
  zoom.s = 1; zoom.x = 0; zoom.y = 0;
  const stage = $('stage');
  stage.classList.remove('zoomed');
  if (item.kind === 'video') {
    const video = el('video', { id: 'clip-video', src: q('/video', item.id), controls: true, autoplay: true, muted: true, playsinline: true });
    stage.replaceChildren(video, el('audio', { id: 'clip-audio', preload: 'auto' }));
    // A video that couldn't be read has no clip; it still plays, without the clip tools.
    if (item.clip) clipPlayer(item, video);
  } else {
    // The thumbnail shows at once; the sharp preview, in the trip's look, takes its place when it arrives.
    const img = el('img', { alt: item.file, src: item.thumb ? q('/thumb', item.id) : '' });
    stage.replaceChildren(img, el('div', { class: 'wait' }, dots()));
    refreshPreview(item);
    const next = state.list[state.at + 1];
    if (next?.kind === 'photo') new Image().src = previewUrl(next);
  }
  info(item);
  $('prev').hidden = state.at === 0;
  $('next').hidden = state.at === state.list.length - 1;
}

// The preview's address names everything that shapes it, so a change fetches a fresh one and going back is instant.
function previewUrl(item) {
  const look = state.view.looks[item.subject || 'landscape'] || 'none';
  return `${q('/preview', item.id)}&v=${look}-${item.subject}-${item.adjust.exposure}-${item.adjust.warmth}`;
}

// The new picture replaces the old one only once it has arrived, so the photo never blinks while adjusting.
function refreshPreview(item) {
  const sharp = new Image();
  sharp.onload = () => {
    const img = $('stage').querySelector('img');
    if (state.list[state.at] !== item || !img) return;
    img.src = sharp.src;
    $('stage').querySelector('.wait')?.remove();
  };
  sharp.onerror = () => $('stage').querySelector('.wait')?.replaceChildren('这张照片打不开');
  sharp.src = previewUrl(item);
}

// Holding O (or the button) shows the photo as shot, to compare.
function showPlain(on) {
  const item = state.list[state.at];
  const img = $('stage').querySelector('img');
  if (!item || item.kind !== 'photo' || !img) return;
  img.src = on ? `${q('/preview', item.id)}&plain=1` : previewUrl(item);
  $('verdict').hidden = on;
  $('plain-tag').hidden = !on;
}

function toggleDetails() {
  state.details = !state.details;
  remember('details', state.details ? 'yes' : 'no');
  info(state.list[state.at]);
}

let adjusting = null;
const showValue = (n, warm) => (n === 0 ? '0' : warm ? (n > 0 ? `暖 ${n.toFixed(2)}` : `冷 ${(-n).toFixed(2)}`) : (n > 0 ? `+${n.toFixed(1)}` : n.toFixed(1)));

function slider(item, id, label, value, min, max, stepBy, warm) {
  const out = el('output', { for: id }, showValue(value, warm));
  const input = el('input', { type: 'range', id, min, max, step: stepBy, value, 'aria-label': label });
  input.addEventListener('input', () => { out.textContent = showValue(Number(input.value), warm); queueAdjust(item); });
  // Let go of the slider and the arrow keys go back to turning pages.
  input.addEventListener('change', () => input.blur());
  return el('label', { class: 'slider' }, el('span', {}, label), input, out);
}

// The photo's own controls in the bar: brightness, warmth, the way back, and a look at the original.
function photoControls(item) {
  const { exposure, warmth } = item.adjust;
  const plain = el('button', { type: 'button', class: 'pill-btn', title: '也可以按住 O' }, '看原图');
  plain.addEventListener('pointerdown', () => showPlain(true));
  for (const end of ['pointerup', 'pointerleave']) plain.addEventListener(end, () => showPlain(false));
  return [
    slider(item, 'exposure', '亮度', exposure, -2, 2, 0.1, false),
    slider(item, 'warmth', '冷暖', warmth, -1, 1, 0.05, true),
    exposure || warmth ? el('button', { type: 'button', class: 'pill-btn', onclick: () => saveAdjust(item, 0, 0) }, '还原') : null,
    el('span', { class: 'sep' }),
    plain,
  ];
}

// Slider moves are saved a moment after they stop, then the preview is redrawn.
function queueAdjust(item) {
  clearTimeout(adjusting);
  // The values are read now, not when the timer fires: by then the viewer may show another photo.
  const exposure = Number($('exposure').value);
  const warmth = Number($('warmth').value);
  adjusting = setTimeout(() => saveAdjust(item, exposure, warmth, false), 120);
}

async function saveAdjust(item, exposure, warmth, redraw = true) {
  const before = item.adjust;
  item.adjust = { exposure, warmth };
  try {
    await post('/api/adjust', { trip: state.trip, id: item.id, exposure, warmth });
  } catch (error) {
    item.adjust = before;
    return alarm(SAVE_FAILED(error));
  }
  if (state.list[state.at] !== item) return;
  refreshPreview(item);
  if (redraw) info(item);
}

// ---- video clips: about 7 seconds of each kept video, with its sound (none, its own, or a song)

let songs = null;
const clipState = { looping: false };
const seconds = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;

// The video plays whole until a clip is chosen or asked for; then it loops just the clip, with its sound, so what
// plays is what will be exported.
function clipPlayer(item, video) {
  clipState.looping = item.clip.chosen;
  video.addEventListener('loadedmetadata', () => { if (clipState.looping) playClip(item); }, { once: true });
  video.addEventListener('timeupdate', () => {
    if (clipState.looping && video.currentTime >= item.clip.start + item.clip.length) playClip(item);
  });
  // Scrubbing by hand outside the clip goes back to the whole video.
  video.addEventListener('seeking', () => {
    if (clipState.looping && !clipState.jumping && (video.currentTime < item.clip.start - 0.2 || video.currentTime > item.clip.start + item.clip.length)) {
      clipState.looping = false;
      clipSound(item, video);
    }
  });
}

function playClip(item) {
  const video = $('clip-video');
  if (!video) return;
  clipState.looping = true;
  clipState.jumping = true;
  video.currentTime = item.clip.start;
  setTimeout(() => { clipState.jumping = false; }, 100);
  video.play();
  clipSound(item, video);
}

// The sound follows the choice: muted, the video's own, or the song from its chosen point.
function clipSound(item, video) {
  const audio = $('clip-audio');
  const { sound, music, music_start: from } = item.clip;
  video.muted = !(clipState.looping && sound === 'original');
  if (clipState.looping && sound === 'music' && music) {
    const src = `/music?name=${encodeURIComponent(music)}`;
    if (!audio.src.endsWith(src)) audio.src = src;
    audio.currentTime = from + Math.max(0, video.currentTime - item.clip.start);
    audio.play().catch(() => {});
  } else {
    audio.pause();
  }
}

async function saveClip(item, changes) {
  try {
    item.clip = (await post('/api/clip', { trip: state.trip, id: item.id, ...changes })).clip;
  } catch (error) {
    return alarm(SAVE_FAILED(error));
  }
  info(item);
  playClip(item);
}

function setClipStart(item) {
  const video = $('clip-video');
  if (video) saveClip(item, { start: Math.round(Math.min(video.currentTime, Math.max(0, (video.duration || 0) - item.clip.length)) * 10) / 10 });
}

// The clip's own controls in the bar: where it starts, playing it, and its sound.
function clipControls(item) {
  const { start, length: span, sound, music, music_start: from } = item.clip;
  const sounds = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '声音' },
    ...[['mute', '静音'], ['original', '原声'], ['music', '音乐']].map(([key, label]) =>
      el('button', { type: 'button', role: 'radio', 'aria-checked': String(sound === key), onclick: () => saveClip(item, { sound: key }) }, label)));
  return [
    el('span', { class: 'note' }, `${seconds(start)} – ${seconds(start + span)}${item.clip.chosen ? '' : '（中间）'}`),
    el('button', { type: 'button', class: 'pill-btn', onclick: () => setClipStart(item) }, '从这里开始 S'),
    el('button', { type: 'button', class: 'pill-btn', onclick: () => playClip(item) }, '播放这一段'),
    el('span', { class: 'sep' }),
    sounds,
    ...(sound === 'music' ? songPicker(item, music, from, span) : []),
  ];
}

function songPicker(item, music, from, span) {
  if (!songs) {
    get('/api/music').then((answer) => { songs = answer; if (state.list[state.at] === item) info(item); });
    return [el('span', { class: 'note' }, '正在读取音乐…')];
  }
  if (!songs.songs.length) {
    return [el('span', { class: 'note' }, '音乐文件夹里还没有歌：', el('code', {}, songs.folder)),
      el('button', { type: 'button', class: 'pill-btn', onclick: () => { songs = null; info(item); } }, '重新读取')];
  }
  const select = el('select', { 'aria-label': '选一首歌', onchange: (e) => saveClip(item, { music: e.target.value || null, music_start: 0 }) },
    el('option', { value: '' }, '选一首歌…'),
    ...songs.songs.map((name) => el('option', { value: name, selected: name === music }, name)));
  if (!music) return [select];
  // Where in the song the clip begins: dragged like the song strip in a story.
  const audio = $('clip-audio');
  const top = Math.max(0, (audio?.duration || 240) - span);
  const out = el('output', {}, seconds(from));
  const input = el('input', { type: 'range', min: 0, max: top, step: 0.5, value: Math.min(from, top), 'aria-label': '从歌的哪里开始' });
  input.addEventListener('input', () => { out.textContent = seconds(Number(input.value)); });
  input.addEventListener('change', () => { input.blur(); saveClip(item, { music_start: Number(input.value) }); });
  return [select, el('label', { class: 'slider' }, el('span', {}, '从'), input, out)];
}

// Everything the viewer shows about the file on screen: the line at the top, the verdict, the bar, the stack strip
// and the details panel.
function info(item) {
  const members = item.stack != null ? state.list.filter((i) => i.stack === item.stack) : [];
  fill($('meta'),
    el('b', {}, item.file),
    el('span', {}, `${state.at + 1} / ${state.list.length}`),
    item.when && el('span', {}, clock(item.when)),
    item.subject && el('span', {}, SUBJECT_NAMES[item.subject]),
    item.source !== 'mine' && el('span', {}, SOURCES[item.source]));
  // The choice also sits on the picture itself, big enough to see without looking away.
  $('verdict').className = `verdict ${item.pick || 'none'}`;
  $('verdict').textContent = item.pick === 'yes' ? '✓ 要' : item.pick === 'no' ? '✕ 不要' : '';
  fill($('bar'),
    el('button', { type: 'button', class: 'pill-btn keep', 'aria-pressed': String(item.pick === 'yes'), onclick: () => choose([item], 'yes', true) }, 'Z 要'),
    el('button', { type: 'button', class: 'pill-btn drop', 'aria-pressed': String(item.pick === 'no'), onclick: () => choose([item], 'no', true) }, 'X 不要'),
    members.length > 1 && el('button', { type: 'button', class: 'pill-btn', title: 'Shift+Z', onclick: () => keepOnly(item) }, '只要这张'),
    el('span', { class: 'sep' }),
    ...(item.kind === 'photo' ? photoControls(item) : item.clip ? clipControls(item) : []));
  $('strip').hidden = members.length < 2;
  fill($('strip'), ...(members.length < 2 ? [] : members.map((m) =>
    el('button', { type: 'button', class: m.pick || '', 'aria-label': `${m.file}${m.pick === 'yes' ? '，要' : m.pick === 'no' ? '，不要' : ''}`, 'aria-current': String(m === item), onclick: () => { state.at = state.list.indexOf(m); showItem(); } },
      el('img', { alt: '', src: m.thumb ? q('/thumb', m.id) : '' })))));
  $('info-toggle').setAttribute('aria-pressed', String(state.details));
  $('details').hidden = !state.details;
  if (state.details) {
    const facts = [
      ['时间', item.when ? clock(item.when) : '没有记录'],
      ['相机', item.camera || '没有记录'],
      ['尺寸', item.width ? `${item.width} × ${item.height}` : '—'],
      item.kind === 'video' && ['长度', `${length(item.duration)}${item.hdr ? ' · HDR' : ''}`],
      ['位置', item.gps ? '有（只留在本机，不会导出）' : '没有'],
    ].filter(Boolean);
    fill($('details'),
      el('h4', {}, '来源'),
      el('div', { class: 'who' }, el('b', { class: item.source }, SOURCES[item.source]), el('span', {}, item.reason)),
      item.subject && el('h4', {}, '类型'),
      item.subject && el('div', { class: 'who' }, el('b', {}, SUBJECT_NAMES[item.subject]), el('span', {}, `${item.subject_reason} · 不对就按 T`)),
      el('h4', {}, '文件'),
      el('dl', {}, ...facts.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])),
      el('p', { class: 'keys' }, 'Z 要 · X 不要（再按一次取消）', el('br'),
        members.length > 1 ? 'Shift+Z 只要这张 · ' : '', item.kind === 'photo' ? 'T 人像/风景 · 按住 O 看原图' : 'S 从这里开始', el('br'),
        '← → 翻看 · I 这个面板 · Esc 关闭'));
  }
}

function step(by) {
  const to = state.at + by;
  if (to < 0 || to >= state.list.length) return;
  state.at = to;
  showItem();
}

$('prev').addEventListener('click', () => step(-1));
$('next').addEventListener('click', () => step(1));
$('close').addEventListener('click', closeLoupe);
$('info-toggle').addEventListener('click', toggleDetails);
$('loupe').addEventListener('cancel', (e) => { e.preventDefault(); closeLoupe(); });

// Zoom keeps the point under the mouse still; drag to look around; double-click to fit again.
$('stage').addEventListener('wheel', (e) => {
  if (!$('stage').querySelector('img')) return;
  e.preventDefault();
  const box = $('stage').getBoundingClientRect();
  const px = e.clientX - box.left;
  const py = e.clientY - box.top;
  const s = Math.min(6, Math.max(1, zoom.s * Math.exp(-e.deltaY * 0.0022)));
  setZoom(s, px - (px - zoom.x) * s / zoom.s, py - (py - zoom.y) * s / zoom.s);
}, { passive: false });
$('stage').addEventListener('dblclick', () => setZoom(1, 0, 0));
$('stage').addEventListener('pointerdown', (e) => {
  if (zoom.s === 1 || !$('stage').querySelector('img')) return;
  const stage = $('stage');
  stage.setPointerCapture(e.pointerId);
  const start = { x: e.clientX, y: e.clientY, zx: zoom.x, zy: zoom.y };
  const move = (m) => setZoom(zoom.s, start.zx + m.clientX - start.x, start.zy + m.clientY - start.y);
  const up = () => { stage.removeEventListener('pointermove', move); stage.removeEventListener('pointerup', up); };
  stage.addEventListener('pointermove', move);
  stage.addEventListener('pointerup', up);
});

showTrips().catch((error) => fill($('main'), el('p', { class: 'empty' }, `出错了：${error.message}`)));
