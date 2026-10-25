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
  lookFor: 'landscape', storyTab: remembered('storyTab', 'pick'), stacked: remembered('stacked', 'yes') === 'yes', details: remembered('details', 'no') === 'yes',
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
  stopListening();
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
  const busy = () => state.view.progress.running || state.view.export.running || state.view.publish.running;
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
  const telling = state.mode === 'story';
  const browsing = state.mode === 'photos';
  const told = storyItems().filter((i) => i.story).length;
  fill(box,
    browsing && group('来源', FILTERS.filter(([k]) => k !== 'screenshot' || bySource.screenshot), state.filter, bySource, (k) => { state.filter = k; remember('filter', k); render(); }),
    browsing && group('选片', PICKS, state.picks, picked, (k) => { state.picks = k; remember('picks', k); render(); }),
    browsing && group('类型', SUBJECTS, state.subject, bySubject, (k) => { state.subject = k; remember('subject', k); render(); }),
    el('nav', { class: 'group', 'aria-label': '工具' }, el('h3', {}, '工具'),
      el('button', { type: 'button', class: 'item', 'aria-pressed': String(looking), onclick: () => toggleMode('looks') },
        el('span', {}, looking ? '‹ 回到照片' : '风格'), el('i', {}, `${looks.landscape || '原图'} · ${looks.portrait || '原图'}`)),
      el('button', { type: 'button', class: telling ? 'item' : 'item story-go', 'aria-pressed': String(telling), onclick: () => toggleMode('story') },
        el('span', {}, telling ? '‹ 回到照片' : '故事'), el('i', {}, `${told} 个`)),
      browsing && el('button', { type: 'button', class: 'item', 'aria-pressed': String(state.stacked),
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
  else if (state.view.publish.running) showProgress('发布', state.view.publish.done, state.view.publish.total);
  else finishProgress();
  const formats = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '导出格式' },
    ...Object.keys(FORMATS).map((key) => el('button', { type: 'button', role: 'radio', 'aria-checked': String(out.format === key),
      disabled: out.running, onclick: () => setFormat(key) }, FORMATS[key].name)));
  if (state.mode === 'story') {
    // Look first, then publish: the two sit together, in that order.
    const told = storyItems().filter((i) => i.story).length;
    fill(foot, el('button', { type: 'button', class: 'export', disabled: !told, onclick: openShow },
      el('b', {}, '预览故事'), el('small', {}, told ? "大概看看在 Jack's Space 上的样子" : '先选几张照片')),
      el('div', { class: 'publish', id: 'publish' }));
    return publishNote();
  }
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

// The looks page and the story page each take the main area; the same button goes back to the photos.
function toggleMode(mode) {
  stopListening();
  state.mode = state.mode === mode ? 'photos' : mode;
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
  if (state.mode === 'story') { renderStory(); return; }
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
  if ($('story-show').open) return showKeys(e);
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

// ---- the story: first pick which kept photos tell the trip, in timeline order; then write under each one

const STORY_TABS = [['pick', '选照片'], ['write', '写字']];
// What can go into the story: the kept photos, and the kept videos that have a clip.
const storyItems = () => state.view.items.filter((i) => i.pick === 'yes' && !i.error && (i.kind === 'photo' || i.clip));

function renderStory() {
  const kept = storyItems();
  const chosen = kept.filter((i) => i.story);
  const tabs = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '故事' },
    ...STORY_TABS.map(([key, label]) => el('button', { type: 'button', role: 'radio', 'aria-checked': String(state.storyTab === key),
      onclick: () => { state.storyTab = key; remember('storyTab', key); window.scrollTo({ top: 0, behavior: 'instant' }); renderStory(); } },
      key === 'pick' ? `${label} · ${chosen.length}` : label)));
  const head = el('div', { class: 'looks-head' }, el('h1', {}, '故事'), tabs, storySong());
  if (state.storyTab === 'write') {
    fill($('main'), head,
      el('p', { class: 'looks-note' }, chosen.length ? `${chosen.length} 个，按拍摄时间排。对着照片和视频写下想说的话，会自动保存；不写也可以，文章里就只有照片或视频。` : '还没有照片或视频。先在「选照片」里点选。'),
      el('div', { class: 'story-write' }, titleBox(), endBox('intro', '开头', chosen),
        ...storyGroups(chosen).flatMap((members, k, all) => k < all.length - 1 ? [groupFor(members, k), noteSlot(members.at(-1))] : [groupFor(members, k)]),
        endBox('outro', '结尾', chosen)));
    publishNote();
    return;
  }
  const days = new Map();
  for (const item of kept) {
    const key = item.day ?? 'none';
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(item);
  }
  const labels = new Map(state.view.days.map((d) => [d.day, d.label]));
  fill($('main'), head,
    el('p', { class: 'looks-note' }, kept.length ? `按时间排出你要了的 ${kept.length} 个照片和视频（视频用你定的那一段）。点一下放进故事，再点一下拿出来；号码是它在文章里的顺序。` : '还没有要了的照片和视频。先回到照片，用 Z 标出要的。'),
    ...[...days].map(([day, list]) => el('section', { class: 'day' },
      el('div', { class: 'day-head' }, el('h2', {}, day === 'none' ? '没有拍摄时间' : labels.get(day) || day), el('span', {}, `${list.length} 张`)),
      el('div', { class: 'rows' }, ...list.map(storyCard)))));
  numberStory();
}

function storyCard(item) {
  const ratio = item.width && item.height ? Math.min(3, Math.max(0.4, item.width / item.height)) : 1;
  const img = el('img', { alt: '', loading: 'lazy', decoding: 'async', onload: (e) => e.target.classList.add('ready') });
  if (item.thumb) img.src = q('/thumb', item.id);
  return el('button', { type: 'button', class: `card story-card${item.story ? ' in' : ''}`, style: `flex-basis:${Math.round(ROW_HEIGHT * ratio)}px`,
    'data-id': item.id, 'aria-pressed': String(item.story), 'aria-label': `${item.file}${item.when ? `，${clock(item.when)}` : ''}`,
    onclick: () => chooseForStory(item) }, img, el('span', { class: 'chip order' }),
    item.kind === 'video' && el('span', { class: 'chip length' }, length(item.clip.length)));
}

// The badges show each chosen photo's place in the story, so they are redrawn whenever one goes in or out.
function numberStory() {
  const chosen = storyItems().filter((i) => i.story);
  for (const card of document.querySelectorAll('.story-card')) {
    const at = chosen.findIndex((i) => i.id === card.dataset.id);
    card.classList.toggle('in', at >= 0);
    card.setAttribute('aria-pressed', String(at >= 0));
    card.querySelector('.order').textContent = at >= 0 ? String(at + 1) : '';
  }
  const tab = document.querySelector('.looks-head [role=radio]');
  if (tab) tab.textContent = `选照片 · ${chosen.length}`;
  filters();
  publishNote();
}

// The story's one song: a full song from the music folder's 完整版, played under the whole story on the site (its clips
// are silent). It can be heard here first.
let fullSongs = null;
const listening = new Audio();
listening.loop = true;

// The preview's place in the song, on its bar and as "0:42 / 2:25".
function showPlace() {
  const seek = document.querySelector('.story-song .seek');
  if (!seek) return;
  const total = Number.isFinite(listening.duration) ? listening.duration : 0;
  seek.max = String(Math.max(1, Math.floor(total)));
  if (document.activeElement !== seek) seek.value = String(listening.currentTime);
  document.querySelector('.story-song .place').textContent = total ? `${length(listening.currentTime)} / ${length(total)}` : '';
}
listening.addEventListener('timeupdate', showPlace);
listening.addEventListener('loadedmetadata', showPlace);

function stopListening() {
  listening.pause();
  document.querySelector('.story-song .listen')?.replaceChildren('▶ 试听');
}

function storySong() {
  const box = el('div', { class: 'story-song' });
  const draw = () => {
    if (!fullSongs) {
      fill(box, el('span', { class: 'note' }, '正在读取音乐…'));
      return;
    }
    if (!fullSongs.songs.length) {
      fill(box, el('span', { class: 'note' }, '完整版文件夹里还没有歌：', el('code', {}, fullSongs.folder)));
      return;
    }
    const chosen = state.view.story_song;
    const select = el('select', { 'aria-label': '整个故事的音乐', onchange: async (e) => {
      const song = e.target.value || null;
      const before = state.view.story_song;
      state.view.story_song = song;
      stopListening();
      try {
        await post('/api/story-song', { trip: state.trip, song });
      } catch (error) {
        state.view.story_song = before;
        alarm(SAVE_FAILED(error));
      }
      draw();
    } },
      el('option', { value: '' }, '不要音乐'),
      ...fullSongs.songs.map((s) => el('option', { value: s.name, selected: s.name === chosen },
        `${s.title || s.name.replace(/\.[^.]+$/, '')}${s.artist ? ` · ${s.artist}` : ''}`)));
    const src = chosen && `/music?full=1&name=${encodeURIComponent(chosen)}`;
    const load = () => { if (src && !listening.src.endsWith(src)) listening.src = src; };
    const listen = el('button', { type: 'button', class: 'pill-btn listen', disabled: !chosen, onclick: () => {
      if (!listening.paused) return stopListening();
      load();
      listening.play().catch(() => {});
      listen.replaceChildren('❚❚ 停');
    } }, '▶ 试听');
    // Where in the song: dragged to hear another part of it.
    const seek = el('input', { type: 'range', class: 'seek', min: 0, max: 1, step: 0.5, value: 0, disabled: !chosen, 'aria-label': '试听到哪里' });
    seek.addEventListener('input', () => { load(); listening.currentTime = Number(seek.value); showPlace(); });
    fill(box, el('span', { class: 'note' }, '音乐'), select, listen, el('label', { class: 'slider' }, seek, el('output', { class: 'place' })));
    if (src && listening.src.endsWith(src)) showPlace();
  };
  if (!fullSongs) get('/api/full-music').then((answer) => { fullSongs = answer; draw(); });
  draw();
  return box;
}

// The story page's way out to Jack's Space: the button, and what the last publish did.
function publishNote() {
  const box = $('publish');
  if (!box) return;
  const run = state.view.publish;
  const chosen = storyItems().filter((i) => i.story).length;
  // After a publish, the post opens in the site's local preview (its dev server, npm run dev in jacks-space).
  fill(box, !run.running && run.error && el('span', { class: 'note bad' }, `没发布：${run.error}`),
    el('button', { type: 'button', class: 'pill-btn keep', disabled: !chosen || run.running || state.view.export.running,
      onclick: (e) => { e.currentTarget.disabled = true; begin('/api/publish'); } },
      run.running ? '正在发布' : `发布到网站 · ${chosen} 个`),
    !run.running && !run.error && run.address && el('a', { class: 'pill-btn', href: `http://localhost:4321/${run.address}/`, target: '_blank', rel: 'noopener' }, '在网站上看 ›'));
}

async function chooseForStory(item) {
  item.story = !item.story;
  numberStory();
  try {
    await post('/api/story', { trip: state.trip, id: item.id, chosen: item.story });
  } catch (error) {
    item.story = !item.story;
    numberStory();
    alarm(SAVE_FAILED(error));
  }
}

// A clip in the story plays as it will on the site: just its own seconds, over and over, without sound here.
function clipPreview(item) {
  const { start, length: span } = item.clip;
  const video = el('video', { src: q('/video', item.id), muted: true, playsinline: true, preload: 'metadata', controls: true });
  video.addEventListener('loadedmetadata', () => { video.currentTime = start; });
  video.addEventListener('timeupdate', () => { if (video.currentTime >= start + span || video.currentTime < start - 0.3) video.currentTime = start; });
  return video;
}

// The chosen photos as the story's moments: a photo joined to the one before it goes into that one's group, which
// shares one paragraph and shows its photos one after another on the site.
function storyGroups(chosen) {
  const groups = [];
  for (const item of chosen) {
    if (item.joined && groups.length) groups.at(-1).push(item);
    else groups.push([item]);
  }
  return groups;
}

async function joinStory(item, joined) {
  item.joined = joined;
  renderStory();
  try {
    await post('/api/story', { trip: state.trip, id: item.id, joined });
  } catch (error) {
    item.joined = !joined;
    renderStory();
    alarm(SAVE_FAILED(error));
  }
}

const storyMedia = (item) => (item.kind === 'video' ? clipPreview(item)
  : el('img', { alt: '', loading: 'lazy', decoding: 'async', src: previewUrl(item), width: item.width, height: item.height }));

// The post's title on Jack's Space; publishing writes it into the post.
function titleBox() {
  const note = el('span', { class: 'saved' }, '');
  const input = el('input', { type: 'text', class: 'title-box', maxlength: '120', 'aria-label': '文章标题' });
  input.value = state.view.story_title;
  let timer = null;
  let saved = state.view.story_title;
  const save = async () => {
    clearTimeout(timer);
    const title = input.value.trim();
    if (!title || title === saved) return;
    note.replaceChildren('正在保存', dots());
    try {
      await post('/api/story-title', { trip: state.trip, title });
      saved = state.view.story_title = title;
      note.textContent = '已保存，发布后网站上的标题会跟着改';
    } catch (error) {
      note.textContent = '没存上';
      alarm(SAVE_FAILED(error));
    }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(save, 700); });
  input.addEventListener('change', save);
  return el('section', { class: 'story-end' }, el('div', { class: 'moment-head' }, el('span', {}, '标题'), note), input);
}

// Between two moments: a button that opens a box for words on their own, which the site shows as a slide without a
// photo, over the blur of the photo before it. The box stays until removed, even empty; only written words publish.
function noteSlot(item) {
  const slot = el('div', { class: 'note-slot' });
  const send = (body) => post('/api/story', { trip: state.trip, id: item.id, ...body });
  const draw = () => {
    if (item.note == null) {
      return fill(slot, el('button', { type: 'button', class: 'join', onclick: async () => {
        item.note = '';
        draw();
        slot.querySelector('textarea').focus();
        try { await send({ note: '' }); } catch (error) { item.note = null; draw(); alarm(SAVE_FAILED(error)); }
      } }, '＋ 在这里加一段文字'));
    }
    const note = el('span', { class: 'saved' }, item.note ? '已保存' : '');
    const box = el('textarea', { rows: '2', placeholder: '只有文字的一段（网站上单独一格，没有照片）', 'aria-label': `${item.file} 之后的一段文字` });
    box.value = item.note;
    let timer = null;
    let saved = item.note;
    const save = async () => {
      clearTimeout(timer);
      const words = item.note;
      if (words === saved || item.note == null) return;
      note.replaceChildren('正在保存', dots());
      try {
        await send({ note: words });
        saved = words;
        if (item.note === words) note.textContent = '已保存';
      } catch (error) {
        note.textContent = '没存上';
        alarm(SAVE_FAILED(error));
      }
    };
    box.addEventListener('input', () => { item.note = box.value; clearTimeout(timer); timer = setTimeout(save, 700); });
    box.addEventListener('change', save);
    const remove = el('button', { type: 'button', class: 'join', onclick: async () => {
      clearTimeout(timer);
      const before = item.note;
      item.note = null;
      draw();
      try { await send({ remove_note: true }); } catch (error) { item.note = before; draw(); alarm(SAVE_FAILED(error)); }
    } }, '删掉这段');
    fill(slot, el('section', { class: 'story-end' }, el('div', { class: 'moment-head' }, el('span', {}, '只有文字的一段'), el('span', { class: 'saved' }, note, remove)), box));
  };
  draw();
  return slot;
}

// ---- the story's preview: its slides roughly as Jack's Space shows them (src/components/TravelStory.astro there),
// without the page around them: a scroll goes one slide on, the photo and words fading in on arrival.

const SHOW = { slides: [], at: 0, held: 0 };

function showSlides() {
  const chosen = storyItems().filter((i) => i.story);
  const v = state.view;
  const pickOr = (id, fallback) => chosen.find((i) => i.id === id) ?? fallback;
  const slides = [];
  if (v.story_intro.trim()) slides.push({ back: pickOr(v.story_intro_photo, chosen[0]), words: v.story_intro, key: 'intro' });
  storyGroups(chosen).forEach((members, g) => {
    members.forEach((m, j) => slides.push({ photo: m, glow: m, head: members[0], last: members.at(-1), key: `g${g}`, place: members.length > 1 ? `${j + 1} / ${members.length}` : '' }));
    const between = members.map((m) => m.note ?? '').filter((words) => words.trim()).join('\n');
    if (between) slides.push({ glow: members.at(-1), words: between, key: `n${g}` });
  });
  if (v.story_outro.trim()) slides.push({ back: pickOr(v.story_outro_photo, chosen.at(-1)), words: v.story_outro, key: 'outro' });
  return slides;
}

function openShow() {
  stopListening();
  SHOW.slides = showSlides();
  if (!SHOW.slides.length) return;
  const screen = $('show-screen');
  const paras = (text) => text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => el('p', {}, l));
  const items = [...new Set(SHOW.slides.flatMap((s) => [s.photo, s.glow, s.back]).filter(Boolean))];
  const words = new Map();
  for (const s of SHOW.slides) {
    if (words.has(s.key)) continue;
    if (s.head) {
      const when = s.head.when ? clock(s.head.when) + (s.last !== s.head && s.last.when ? ` – ${clock(s.last.when).split(' ')[1]}` : '') : '';
      words.set(s.key, el('div', { class: 'show-words', 'data-key': s.key },
        (s.head.place || when) && el('div', { class: 'show-head' }, s.head.place && el('b', {}, el('span', { class: 'pin', 'aria-hidden': 'true' }), s.head.place), when && el('span', {}, when)),
        ...paras(s.head.words)));
    } else words.set(s.key, el('div', { class: 'show-words end', 'data-key': s.key }, ...paras(s.words)));
  }
  fill(screen,
    ...items.map((item) => el('img', { class: 'show-glow', alt: '', 'data-id': item.id, 'data-src': item.thumb ? q('/thumb', item.id) : '' })),
    ...items.map((item) => el('img', { class: 'show-back', alt: '', 'data-id': item.id, 'data-src': previewUrl(item) })),
    ...items.map((item) => {
      if (item.kind !== 'video') return el('img', { class: 'show-photo', alt: '', 'data-id': item.id, 'data-src': previewUrl(item) });
      const video = clipPreview(item);
      video.controls = false;
      video.classList.add('show-photo');
      video.dataset.id = item.id;
      return video;
    }),
    ...words.values());
  SHOW.at = -1;
  $('show-seek').max = String(SHOW.slides.length);
  $('story-show').showModal();
  $('story-show').focus();
  showAt(0);
}

function showAt(k) {
  k = Math.max(0, Math.min(SHOW.slides.length - 1, k));
  if (k === SHOW.at) return;
  SHOW.at = k;
  const s = SHOW.slides[k];
  const screen = $('show-screen');
  // Pictures load a slide or two ahead.
  const near = SHOW.slides.slice(Math.max(0, k - 1), k + 3).flatMap((n) => [n.photo, n.glow, n.back]).filter(Boolean).map((i) => i.id);
  for (const img of screen.querySelectorAll('img[data-src]')) if (near.includes(img.dataset.id) && !img.getAttribute('src')) img.src = img.dataset.src;
  const on = (cls, item) => screen.querySelectorAll(cls).forEach((x) => x.classList.toggle('on', !!item && x.dataset.id === item.id));
  on('.show-glow', s.glow);
  on('.show-back', s.back);
  on('.show-photo', s.photo);
  screen.querySelectorAll('video.show-photo').forEach((v) => (v.classList.contains('on') ? v.play().catch(() => {}) : v.pause()));
  screen.querySelectorAll('.show-words').forEach((w) => w.classList.toggle('on', w.dataset.key === s.key));
  $('show-count').textContent = `${k + 1} / ${SHOW.slides.length}${s.place ? ` · 这组第 ${s.place}` : ''}`;
  $('show-seek').value = String(k + 1);
}

// One wheel turn or touchpad swipe is one slide: more turns are held back while a slide lands.
function showStep(way) {
  if (performance.now() < SHOW.held) return;
  SHOW.held = performance.now() + 500;
  showAt(SHOW.at + way);
}
$('story-show').addEventListener('wheel', (e) => {
  e.preventDefault();
  if (performance.now() < SHOW.held) { SHOW.held = Math.max(SHOW.held, performance.now() + 200); return; }
  if (Math.abs(e.deltaY) >= 4) showStep(Math.sign(e.deltaY));
}, { passive: false });
function showKeys(e) {
  const way = { ArrowDown: 1, PageDown: 1, ' ': 1, ArrowRight: 1, ArrowUp: -1, PageUp: -1, ArrowLeft: -1 }[e.key];
  if (way) { e.preventDefault(); showStep(way); }
  if (e.key === 'Home') { e.preventDefault(); showAt(0); }
  if (e.key === 'End') { e.preventDefault(); showAt(SHOW.slides.length - 1); }
}
$('show-close').addEventListener('click', () => $('story-show').close());
// Dragging the bar goes straight to any slide.
$('show-seek').addEventListener('input', (e) => showAt(Number(e.target.value) - 1));
$('story-show').addEventListener('close', () => {
  $('show-screen').querySelectorAll('video').forEach((v) => v.pause());
  fill($('show-screen'));
});

// The story's opening or closing words, apart from any photo: left empty, the story starts or ends with a photo.
// Under them, the photo the site dims behind them: the first (or last) unless Jack picks another.
function endBox(which, label, chosen) {
  const key = `story_${which}`;
  const note = el('span', { class: 'saved' }, state.view[key] ? '已保存' : '');
  const box = el('textarea', { rows: '2', placeholder: `${label}的话（可以留白）`, 'aria-label': `故事的${label}` });
  box.value = state.view[key];
  let timer = null;
  let saved = state.view[key];
  const save = async () => {
    clearTimeout(timer);
    const words = state.view[key];
    if (words === saved) return;
    note.replaceChildren('正在保存', dots());
    try {
      await post('/api/story-text', { trip: state.trip, which, words });
      saved = words;
      if (state.view[key] === words) note.textContent = '已保存';
    } catch (error) {
      note.textContent = '没存上';
      alarm(SAVE_FAILED(error));
    }
  };
  box.addEventListener('input', () => { state.view[key] = box.value; clearTimeout(timer); timer = setTimeout(save, 700); });
  box.addEventListener('change', save);
  return el('section', { class: 'story-end' }, el('div', { class: 'moment-head' }, el('span', {}, label), note), box, backPicker(which, label, chosen));
}

function backPicker(which, label, chosen) {
  const key = `story_${which}_photo`;
  const fallback = which === 'intro' ? chosen[0] : chosen.at(-1);
  const strip = el('div', { class: 'backs', role: 'radiogroup', 'aria-label': `${label}背后的照片` });
  const draw = () => {
    const picked = chosen.find((i) => i.id === state.view[key]) ?? fallback;
    fill(strip, ...chosen.map((item) => el('button', { type: 'button', role: 'radio', 'aria-checked': String(item === picked),
      'aria-label': item === fallback ? `${item.file}（默认）` : item.file, onclick: () => pick(item) },
      el('img', { alt: '', loading: 'lazy', decoding: 'async', src: item.thumb ? q('/thumb', item.id) : '' }),
      item === fallback && el('span', { class: 'chip' }, '默认'))));
  };
  const pick = async (item) => {
    const before = state.view[key];
    state.view[key] = item === fallback ? null : item.id;
    draw();
    try {
      await post('/api/story-back', { trip: state.trip, which, id: state.view[key] });
    } catch (error) {
      state.view[key] = before;
      draw();
      alarm(SAVE_FAILED(error));
    }
  };
  if (!chosen.length) return null;
  draw();
  return el('div', { class: 'backs-row' }, el('span', { class: 'note' }, '背景照片（网站上调暗铺满，字在上面）'), strip);
}

// One moment as the article will show it: its photo (or its group's photos, each of the later ones with a way out of
// the group), then a box for the words. From the second moment on, a button above it joins it to the one before.
function groupFor(members, k) {
  const [first] = members;
  const last = members.at(-1);
  const when = first.when ? clock(first.when) + (members.length > 1 && last.when && last.when !== first.when ? ` – ${clock(last.when).split(' ')[1]}` : '') : '没有拍摄时间';
  const moment = momentFor(first, members.length > 1
    ? el('div', { class: 'moment-photos' }, ...members.map((m, j) => el('div', { class: 'member' }, storyMedia(m),
      j > 0 && el('button', { type: 'button', class: 'pill-btn apart', onclick: () => joinStory(m, false) }, '拆开'))))
    : storyMedia(first), `${when}${members.length > 1 ? ` · ${members.length} 张一组` : ''}`);
  if (k === 0) return moment;
  return el('div', { class: 'moment-wrap' },
    el('button', { type: 'button', class: 'join', title: '和上面那段共用一段文字，在网站上一张接一张轮播', onclick: () => joinStory(first, true) }, '↑ 跟上一张合成一组'),
    moment);
}

function momentFor(item, media, label) {
  const note = el('span', { class: 'saved' }, item.words ? '已保存' : '');
  const box = el('textarea', { rows: '3', placeholder: '这张照片的故事……', 'aria-label': `${item.file} 的文字` });
  box.value = item.words;
  // The file object holds the words as typed, so the page drawn again (another tab and back) shows them even before
  // they are saved; `saved` is what the server has.
  item.saved ??= item.words;
  let timer = null;
  const save = async () => {
    clearTimeout(timer);
    const words = item.words;
    if (words === item.saved) return;
    note.replaceChildren('正在保存', dots());
    try {
      await post('/api/story', { trip: state.trip, id: item.id, words });
      item.saved = words;
      if (item.words === words) note.textContent = '已保存';
    } catch (error) {
      note.textContent = '没存上';
      alarm(SAVE_FAILED(error));
    }
  };
  box.addEventListener('input', () => { item.words = box.value; clearTimeout(timer); timer = setTimeout(save, 700); });
  // Leaving the box saves at once, so nothing waits on the timer when the page changes.
  box.addEventListener('change', save);
  return el('article', { class: 'moment' }, media, el('div', { class: 'moment-head' }, el('span', {}, label), note), placeBox(item, note), box);
}

// Where the moment was, shown over its words on the site with a pin; a group's is its first photo's.
function placeBox(item, note) {
  const input = el('input', { type: 'text', maxlength: '40', placeholder: '地点（可不填），比如 理想邦', 'aria-label': `${item.file} 的地点` });
  input.value = item.place;
  item.savedPlace ??= item.place;
  let timer = null;
  const save = async () => {
    clearTimeout(timer);
    const place = item.place;
    if (place === item.savedPlace) return;
    note.replaceChildren('正在保存', dots());
    try {
      await post('/api/story', { trip: state.trip, id: item.id, place });
      item.savedPlace = place;
      if (item.place === place) note.textContent = '已保存';
    } catch (error) {
      note.textContent = '没存上';
      alarm(SAVE_FAILED(error));
    }
  };
  input.addEventListener('input', () => { item.place = input.value; clearTimeout(timer); timer = setTimeout(save, 700); });
  input.addEventListener('change', save);
  return el('label', { class: 'place-box' }, el('span', { class: 'pin', 'aria-hidden': 'true' }), input);
}

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

// The video plays whole, silent, until its clip has been given a start or a sound (or is asked for); then it loops just
// the clip with that sound, so what plays is what will be exported.
function clipPlayer(item, video) {
  clipState.looping = item.clip.chosen || item.clip.sound !== 'mute';
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
  const { start, length: span, sound, music } = item.clip;
  const sounds = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': '声音' },
    ...[['mute', '静音'], ['original', '原声'], ['music', '音乐']].map(([key, label]) =>
      el('button', { type: 'button', role: 'radio', 'aria-checked': String(sound === key), onclick: () => saveClip(item, { sound: key }) }, label)));
  return [
    el('span', { class: 'note' }, `片段 ${seconds(start)} – ${seconds(start + span)}${item.clip.chosen ? '' : '（还没选，先用中间）'}`),
    el('button', { type: 'button', class: 'pill-btn', onclick: () => setClipStart(item) }, '从当前画面开始 S'),
    el('button', { type: 'button', class: 'pill-btn', onclick: () => playClip(item) }, '播放这一段'),
    el('span', { class: 'sep' }),
    sounds,
    ...(sound === 'music' ? songPicker(item, music) : []),
  ];
}

function songPicker(item, music) {
  if (!songs) {
    get('/api/music').then((answer) => { songs = answer; if (state.list[state.at] === item) info(item); });
    return [el('span', { class: 'note' }, '正在读取音乐…')];
  }
  if (!songs.songs.length) {
    return [el('span', { class: 'note' }, '音乐文件夹里还没有歌：', el('code', {}, songs.folder)),
      el('button', { type: 'button', class: 'pill-btn', onclick: () => { songs = null; info(item); } }, '重新读取')];
  }
  const pick = (name) => saveClip(item, { music: name || null, music_start: 0 });
  const select = el('select', { 'aria-label': '选一首歌', onchange: (e) => pick(e.target.value) },
    el('option', { value: '' }, '选一首歌…'),
    // The list shows names without the file type.
    ...songs.songs.map((name) => el('option', { value: name, selected: name === music }, name.replace(/\.[^.]+$/, ''))));
  // ‹ › step through the songs one by one, round the end, so trying each under the clip is one press.
  const at = songs.songs.indexOf(music);
  const step = (by) => pick(songs.songs[(at + by + songs.songs.length) % songs.songs.length]);
  const near = [el('button', { type: 'button', class: 'pill-btn', 'aria-label': '上一首', onclick: () => step(at < 0 ? 0 : -1) }, '‹'), select,
    el('button', { type: 'button', class: 'pill-btn', 'aria-label': '下一首', onclick: () => step(1) }, '›')];
  // The songs are 8 s pieces, cut to fit a 7 s clip, so the music always starts at its beginning.
  return near;
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
        members.length > 1 ? 'Shift+Z 只要这张 · ' : '', item.kind === 'photo' ? 'T 人像/风景 · 按住 O 看原图' : 'S 从当前画面开始', el('br'),
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
