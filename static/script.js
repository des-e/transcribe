// ── State ──────────────────────────────────────────────────────────────────
let currentFileId   = null;
let currentFilename = null;
let selectedModel   = 'medium';
let selectedLang    = 'ru';
let allSegments     = [];
let eventSource     = null;
let activityItems   = [];
let isCancelling    = false;

// ── Backend info ───────────────────────────────────────────────────────────
fetch('/info').then(r => r.json()).then(data => {
  const el = document.getElementById('backend-label');
  if (data.backend === 'mlx') {
    el.textContent = 'Apple Silicon · MLX';
    el.classList.remove('text-muted/40');
    el.classList.add('text-accent/60');
  } else {
    el.textContent = 'Whisper · CPU';
  }
}).catch(() => {});

// ── Models ─────────────────────────────────────────────────────────────────
const MODELS = [
  { id: 'tiny',   label: 'Tiny',   desc: 'очень быстро' },
  { id: 'base',   label: 'Base',   desc: 'быстро'       },
  { id: 'small',  label: 'Small',  desc: 'сбалансировано' },
  { id: 'medium', label: 'Medium', desc: 'рекомендуется' },
  { id: 'large',  label: 'Large',  desc: 'максимум точности' },
];

function renderModels() {
  document.getElementById('model-list').innerHTML = MODELS.map(m => {
    const a = m.id === selectedModel;
    return `
      <button onclick="selectModel('${m.id}')"
        class="w-full flex items-center justify-between px-3 py-2.5 rounded transition-all text-left
               ${a ? 'bg-surface border border-accent/25' : 'hover:bg-surface/30 border border-transparent'}">
        <div class="flex items-baseline gap-2">
          <span class="text-[11px] font-inter font-semibold ${a ? 'text-primary' : 'text-muted/70'}">${m.label}</span>
          <span class="text-[9px] font-inter text-muted/30">${m.desc}</span>
        </div>
        ${a ? '<span class="material-symbols-outlined icon-fill text-xs text-accent">check_circle</span>' : ''}
      </button>`;
  }).join('');
}

function selectModel(id) { selectedModel = id; renderModels(); }

// ── Languages ──────────────────────────────────────────────────────────────
const LANGS = [
  { id: 'ru',   label: 'RU'  },
  { id: 'en',   label: 'EN'  },
  { id: 'auto', label: 'Авто'},
];

function renderLangs() {
  document.getElementById('lang-list').innerHTML = LANGS.map(l => {
    const a = l.id === selectedLang;
    return `
      <button onclick="selectLang('${l.id}')"
        class="flex-1 py-2 rounded border text-[11px] font-inter font-semibold transition-all
               ${a ? 'border-accent/35 bg-surface text-primary' : 'border-border/20 text-muted/40 hover:text-muted/70 hover:bg-surface/20'}">
        ${l.label}
      </button>`;
  }).join('');
}

function selectLang(id) { selectedLang = id; renderLangs(); }

// ── Activity log ───────────────────────────────────────────────────────────
function addActivity(msg) {
  const t = new Date().toLocaleTimeString('ru-RU', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
  activityItems.unshift({ msg, t });
  if (activityItems.length > 7) activityItems.pop();

  const el = document.getElementById('activity-log');
  el.innerHTML = activityItems.map((item, i) => `
    <div class="flex items-start gap-2.5 transition-opacity ${i > 0 ? 'opacity-25' : ''}">
      <span class="w-1.5 h-1.5 rounded-full shrink-0 mt-1.5 ${i === 0 ? 'bg-accent' : 'bg-border'}"></span>
      <div>
        <p class="text-[10px] font-inter text-primary leading-snug">${escHtml(item.msg)}</p>
        <p class="text-[9px] font-inter text-muted/30 mt-0.5">${item.t}</p>
      </div>
    </div>`).join('');
}

// ── File upload ────────────────────────────────────────────────────────────
const dropZone  = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('border-accent/60', 'bg-surface/30');
});
dropZone.addEventListener('dragleave', () => {
  dropZone.classList.remove('border-accent/60', 'bg-surface/30');
});
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('border-accent/60', 'bg-surface/30');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  document.getElementById('upload-progress').classList.remove('hidden');
  document.getElementById('drop-zone').classList.add('opacity-40', 'pointer-events-none');

  const xhr = new XMLHttpRequest();
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      document.getElementById('upload-percent').textContent = pct + '%';
      document.getElementById('upload-bar').style.width = pct + '%';
    }
  };

  xhr.onload = () => {
    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('drop-zone').classList.remove('opacity-40', 'pointer-events-none');

    if (xhr.status === 200) {
      const data = JSON.parse(xhr.responseText);
      currentFileId   = data.file_id;
      currentFilename = data.filename;

      const audioExts = new Set(['mp3','m4a','wav','ogg','aac','flac','opus','wma']);
      const ext = data.filename.split('.').pop().toLowerCase();
      document.getElementById('file-icon').textContent = audioExts.has(ext) ? 'audiotrack' : 'movie';
      document.getElementById('file-name').textContent = data.filename;
      document.getElementById('file-size').textContent = data.size + ' · готов';
      document.getElementById('file-card').classList.remove('hidden');
      document.getElementById('header-filename').textContent = data.filename;
      document.getElementById('extract-wrapper').style.display = data.is_audio ? 'none' : '';

      addActivity(`Загружен: ${data.filename}`);
    } else {
      const msg = xhr.status === 413 ? 'Файл > 2 GB — слишком большой' : `Ошибка загрузки (${xhr.status})`;
      addActivity(msg);
      setStatus('error', msg);
    }
  };

  xhr.onerror = () => {
    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('drop-zone').classList.remove('opacity-40', 'pointer-events-none');
    addActivity('Ошибка сети');
  };

  xhr.open('POST', '/upload');
  xhr.send(formData);
}

function clearFile() {
  if (currentFileId) {
    if (eventSource) stopTranscription();
    fetch(`/clear/${currentFileId}`, { method: 'POST' }).catch(() => {});
  }
  currentFileId   = null;
  currentFilename = null;
  hidePlayer();
  document.getElementById('file-card').classList.add('hidden');
  document.getElementById('header-filename').textContent = 'не выбран';
  document.getElementById('extract-wrapper').style.display = '';
  fileInput.value = '';
}

// ── Transcription ──────────────────────────────────────────────────────────
function startTranscription() {
  if (!currentFileId) { addActivity('Сначала загрузи файл'); return; }
  isCancelling = false;
  if (eventSource)    { eventSource.close(); eventSource = null; }

  allSegments = [];
  document.getElementById('segments-container').innerHTML = '';
  document.getElementById('segments-container').classList.add('hidden');
  document.getElementById('empty-state').classList.remove('hidden');
  document.getElementById('download-section').classList.add('hidden');
  setBtnState('loading');
  setStatus('processing', 'Запуск...');
  addActivity('Транскрибация запущена');

  const url = `/stream?file_id=${currentFileId}&model=${selectedModel}`
            + `&extract_audio=${document.getElementById('extract-toggle').checked}`
            + `&language=${selectedLang}`
            + `&filename=${encodeURIComponent(currentFilename || 'transcript')}`;

  eventSource = new EventSource(url);
  eventSource.onmessage = e => {
    const data = JSON.parse(e.data);

    if (data.type === 'status') {
      setStatus('processing', data.message);
      addActivity(data.message);

    } else if (data.type === 'segment') {
      if (!allSegments.length) {
        document.getElementById('empty-state').classList.add('hidden');
        document.getElementById('segments-container').classList.remove('hidden');
      }
      allSegments.push(data);
      appendSegment(data);
      const spd = data.speed ? ` · ${data.speed}` : '';
      setStatus('processing', `${allSegments.length} сегм.${spd}`);

    } else if (data.type === 'done') {
      const spd = data.speed ? ` · ${data.speed}` : '';
      setStatus('done', `${data.language} · ${data.segments} сегм.${spd}`);
      document.getElementById('download-section').classList.remove('hidden');
      setBtnState('idle');
      eventSource.close();
      addActivity(`Готово — ${data.segments} сегм., ${data.speed} real-time`);
      showPlayer(currentFileId);

    } else if (data.type === 'cancelled') {
      isCancelling = false;
      setStatus('idle', '');
      setBtnState('idle');
      eventSource.close();
      addActivity('Транскрибация отменена');

    } else if (data.type === 'error') {
      setStatus('error', data.message);
      setBtnState('idle');
      eventSource.close();
      addActivity(`Ошибка: ${data.message}`);
    }
  };

  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) {
      if (isCancelling) {
        isCancelling = false;
        setBtnState('idle');
        setStatus('idle', '');
        eventSource = null;
        addActivity('Транскрибация отменена');
      }
      return;
    }
    setStatus('error', 'Ошибка соединения');
    setBtnState('idle');
    eventSource.close();
    eventSource = null;
    addActivity('Соединение разорвано');
  };
}

function stopTranscription() {
  if (!currentFileId) return;
  isCancelling = true;
  fetch(`/cancel?file_id=${currentFileId}`, { method: 'POST' });
  document.getElementById('btn-label').textContent = 'Отменяю...';
  document.getElementById('btn-icon').textContent  = 'hourglass_empty';
  document.getElementById('action-btn').disabled   = true;
}

// ── Append segment ─────────────────────────────────────────────────────────
function appendSegment(seg) {
  const idx = allSegments.length - 1;
  const container = document.getElementById('segments-container');
  const div = document.createElement('div');
  div.className = 'seg-row group flex gap-4 items-start py-2.5';
  div.dataset.startS = seg.start_s;
  div.dataset.endS   = seg.end_s;
  div.dataset.idx    = idx;
  div.innerHTML = `
    <button class="copy-btn mt-0.5 p-1.5 rounded shrink-0
                   opacity-0 group-hover:opacity-100 transition-all
                   text-muted/40 hover:text-primary hover:bg-surface
                   border border-transparent hover:border-border/20" title="Копировать">
      <span class="material-symbols-outlined text-sm">content_copy</span>
    </button>
    <div class="seg-ts w-20 shrink-0 pt-px select-none" title="Перейти к этому моменту">
      <span class="text-[10px] font-inter font-medium text-muted/35 tracking-widest block">${seg.start}</span>
      <span class="text-[10px] font-inter text-muted/20 block mt-0.5">${seg.end}</span>
    </div>
    <div class="flex-1 min-w-0">
      <p class="seg-text text-[15px] leading-relaxed font-light text-primary/85 selection:bg-accent/20"
         title="Нажми для редактирования">${escHtml(seg.text)}</p>
    </div>`;

  div.querySelector('.seg-ts').addEventListener('click', () => seekToSegment(seg.start_s));
  div.querySelector('.seg-text').addEventListener('click', e => {
    e.stopPropagation();
    startEdit(div, parseInt(div.dataset.idx));
  });
  div.querySelector('.copy-btn').addEventListener('click', () => {
    const i = parseInt(div.dataset.idx);
    navigator.clipboard.writeText(allSegments[i].text).then(() => {
      const btn  = div.querySelector('.copy-btn');
      const icon = btn.querySelector('.material-symbols-outlined');
      icon.textContent = 'check';
      btn.style.color  = '#6B7D73';
      setTimeout(() => {
        icon.textContent = 'content_copy';
        btn.style.color  = '';
      }, 1500);
    });
  });

  container.appendChild(div);
  const area = document.getElementById('transcript-area');
  area.scrollTo({ top: area.scrollHeight, behavior: 'smooth' });
}

// ── Edit segment ───────────────────────────────────────────────────────────
let _editingIdx = null;

function startEdit(div, idx) {
  if (_editingIdx !== null) return;
  _editingIdx = idx;

  const p        = div.querySelector('.seg-text');
  const original = allSegments[idx].text;
  let   done     = false;

  p.contentEditable = 'true';
  p.classList.add('seg-text-editing');
  p.focus();

  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(p);
  sel.removeAllRanges();
  sel.addRange(range);

  function commit() {
    if (done) return;
    done = true;
    const newText = p.textContent.trim();
    p.contentEditable = 'false';
    p.classList.remove('seg-text-editing');
    allSegments[idx].text = newText || original;
    p.innerHTML = escHtml(allSegments[idx].text);
    if (newText && newText !== original) {
      p.classList.add('flash-saved');
      p.addEventListener('animationend', () => p.classList.remove('flash-saved'), { once: true });
    }
    _editingIdx = null;
    cleanup();
  }

  function revert() {
    if (done) return;
    done = true;
    p.contentEditable = 'false';
    p.classList.remove('seg-text-editing');
    p.innerHTML = escHtml(original);
    _editingIdx = null;
    cleanup();
  }

  function onKeydown(e) {
    if (e.key === 'Enter')  { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { e.preventDefault(); revert(); }
  }

  function cleanup() {
    p.removeEventListener('blur',    commit);
    p.removeEventListener('keydown', onKeydown);
  }

  p.addEventListener('blur',    commit);
  p.addEventListener('keydown', onKeydown);
}

// ── Status badge ───────────────────────────────────────────────────────────
function setStatus(type, message) {
  const badge = document.getElementById('status-badge');
  const info  = document.getElementById('status-info');

  const cfg = {
    processing: { cls: 'border-accent/30 bg-surface text-accent',        icon: 'autorenew',       spin: true,  label: 'Обработка' },
    done:       { cls: 'border-accent/40 bg-surface text-accent',         icon: 'check_circle',    spin: false, label: 'Готово'    },
    error:      { cls: 'border-red-800/30 bg-red-950/20 text-red-500/70', icon: 'error',           spin: false, label: 'Ошибка'    },
    idle:       { cls: 'border-border/20 bg-surface text-muted',          icon: 'hourglass_empty', spin: false, label: 'Ожидание'  },
  }[type] || { cls: 'border-border/20 bg-surface text-muted', icon: 'hourglass_empty', spin: false, label: 'Ожидание' };

  badge.className = `flex items-center gap-2 px-3 py-2 rounded border text-[10px] font-inter font-bold uppercase tracking-widest w-full justify-center ${cfg.cls}`;
  badge.innerHTML = `<span class="material-symbols-outlined text-xs${cfg.spin ? ' spin' : ''}">${cfg.icon}</span>${cfg.label}`;
  info.textContent = message || '';
}

// ── Button state ───────────────────────────────────────────────────────────
const BTN_BASE = 'w-full py-3 rounded text-sm font-bold flex items-center justify-center gap-2 transition-all active:scale-[0.98]';

function setBtnState(state) {
  const btn   = document.getElementById('action-btn');
  const icon  = document.getElementById('btn-icon');
  const label = document.getElementById('btn-label');

  if (state === 'loading') {
    btn.onclick       = stopTranscription;
    btn.className     = BTN_BASE + ' bg-red-950/50 text-red-400/80 border border-red-900/30 hover:bg-red-950/70';
    icon.textContent  = 'stop_circle';
    label.textContent = 'Остановить';
    btn.disabled      = false;
  } else {
    btn.onclick       = startTranscription;
    btn.className     = BTN_BASE + ' bg-accent text-bg hover:bg-accent/90';
    icon.textContent  = 'play_circle';
    label.textContent = 'Транскрибировать';
    btn.disabled      = false;
  }
}

// ── Download ───────────────────────────────────────────────────────────────
function downloadTXT() {
  if (!allSegments.length) return;
  triggerDownload(
    allSegments.map(s => `[${s.start} --> ${s.end}]\n${s.text}`).join('\n\n'),
    baseName() + '.txt'
  );
  addActivity('TXT сохранён');
}

function downloadSRT() {
  if (!allSegments.length) return;
  triggerDownload(
    allSegments.map((s, i) => `${i+1}\n${toSrtTime(s.start_s)} --> ${toSrtTime(s.end_s)}\n${s.text}`).join('\n\n'),
    baseName() + '.srt'
  );
  addActivity('SRT сохранён');
}

function downloadAudio() {
  if (!currentFileId) return;
  const a = document.createElement('a');
  a.href = `/audio/${currentFileId}`;
  a.download = baseName();
  a.click();
  addActivity('Аудио сохранено');
}

function triggerDownload(text, filename) {
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' })),
    download: filename,
  });
  a.click();
  URL.revokeObjectURL(a.href);
}

function baseName() {
  return currentFilename ? currentFilename.replace(/\.[^/.]+$/, '') : 'transcript';
}

function toSrtTime(s) {
  const ms = Math.round((s % 1) * 1000);
  const ss = Math.floor(s) % 60;
  const mm = Math.floor(s / 60) % 60;
  const hh = Math.floor(s / 3600);
  return `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
}

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Audio player ───────────────────────────────────────────────────────────
const audioEl       = document.getElementById('audio-el');
const progressFill  = document.getElementById('progress-fill');
const progressThumb = document.getElementById('progress-thumb');
const audioTimeEl   = document.getElementById('audio-time');

audioEl.addEventListener('play',  () => { document.querySelector('#play-btn .material-symbols-outlined').textContent = 'pause'; });
audioEl.addEventListener('pause', () => { document.querySelector('#play-btn .material-symbols-outlined').textContent = 'play_arrow'; });
audioEl.addEventListener('ended', () => { document.querySelector('#play-btn .material-symbols-outlined').textContent = 'play_arrow'; });

audioEl.addEventListener('timeupdate', () => {
  const pct = audioEl.duration ? (audioEl.currentTime / audioEl.duration * 100) : 0;
  progressFill.style.width = pct + '%';
  progressThumb.style.left = pct + '%';
  audioTimeEl.textContent  = fmtTime(audioEl.currentTime) + ' / ' + fmtTime(audioEl.duration || 0);
  highlightSegment(audioEl.currentTime);
});

document.getElementById('progress-track').addEventListener('mouseenter', () => { progressThumb.style.opacity = '1'; });
document.getElementById('progress-track').addEventListener('mouseleave', () => { progressThumb.style.opacity = '0'; });

function togglePlay() {
  if (!audioEl.src) return;
  audioEl.paused ? audioEl.play() : audioEl.pause();
}

function seekAudio(e) {
  if (!audioEl.duration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  audioEl.currentTime = ((e.clientX - rect.left) / rect.width) * audioEl.duration;
  audioEl.play();
}

function seekToSegment(startS) {
  if (!audioEl.src) return;
  audioEl.currentTime = startS;
  audioEl.play();
}

let _lastActiveRow = null;
function highlightSegment(t) {
  const rows = document.querySelectorAll('.seg-row');
  let found = null;
  for (const row of rows) {
    if (t >= parseFloat(row.dataset.startS) && t < parseFloat(row.dataset.endS)) { found = row; break; }
  }
  if (found === _lastActiveRow) return;
  if (_lastActiveRow) _lastActiveRow.classList.remove('seg-active');
  if (found) {
    found.classList.add('seg-active');
    const area = document.getElementById('transcript-area');
    const top  = found.offsetTop;
    if (top < area.scrollTop + 80 || top > area.scrollTop + area.clientHeight - 120) {
      area.scrollTo({ top: top - area.clientHeight / 2, behavior: 'smooth' });
    }
  }
  _lastActiveRow = found;
}

function showPlayer(fileId) {
  audioEl.src = `/audio/${fileId}`;
  document.getElementById('audio-player').classList.remove('hidden');
}

function hidePlayer() {
  audioEl.pause();
  audioEl.src              = '';
  progressFill.style.width = '0%';
  progressThumb.style.left = '0%';
  audioTimeEl.textContent  = '0:00 / 0:00';
  document.querySelector('#play-btn .material-symbols-outlined').textContent = 'play_arrow';
  if (_lastActiveRow) { _lastActiveRow.classList.remove('seg-active'); _lastActiveRow = null; }
  document.getElementById('audio-player').classList.add('hidden');
}

function fmtTime(s) {
  if (!s || isNaN(s)) return '0:00';
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

// ── Theme ──────────────────────────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const goLight = html.classList.contains('dark');
  html.classList.toggle('dark',  !goLight);
  html.classList.toggle('light',  goLight);
  localStorage.setItem('theme', goLight ? 'light' : 'dark');
  document.getElementById('theme-icon').textContent = goLight ? 'dark_mode' : 'light_mode';
}

// ── View switching ─────────────────────────────────────────────────────────
const NAV_ACTIVE   = 'text-primary bg-surface/50 border-l-2 border-accent';
const NAV_INACTIVE = 'text-muted/50 border-l-2 border-transparent hover:text-primary hover:bg-surface/30';

const VIEWS = ['transcribe', 'history', 'analysis'];

function showView(name) {
  VIEWS.forEach(v => {
    document.getElementById(`view-${v}`).classList.toggle('hidden', v !== name);
    const nav  = document.getElementById(`nav-${v}`);
    const icon = nav.querySelector('.material-symbols-outlined');
    nav.className = `flex items-center gap-3 py-2.5 px-3 rounded text-sm font-semibold transition-all ${v === name ? NAV_ACTIVE : NAV_INACTIVE}`;
    icon.classList.toggle('text-accent', v === name);
  });

  if (name === 'analysis') renderAnalysisView();
  if (name === 'history')  loadHistoryView();
  return false;
}

// ── История транскрибаций ──────────────────────────────────────────────────
async function loadHistoryView() {
  const list    = document.getElementById('history-list');
  const empty   = document.getElementById('history-empty');
  const spinner = document.getElementById('history-spinner');

  list.innerHTML = '';
  empty.classList.add('hidden');
  spinner.classList.remove('hidden');

  try {
    const r    = await fetch('/history');
    const data = await r.json();
    spinner.classList.add('hidden');

    if (!data.length) {
      empty.classList.remove('hidden');
      return;
    }

    list.innerHTML = data.map(e => `
      <div class="flex items-center justify-between py-3 px-4 rounded border border-border/15
                  bg-surface/20 hover:bg-surface/40 transition-colors group gap-3">
        <div class="flex items-center gap-3 min-w-0">
          <span class="material-symbols-outlined text-muted/30 text-base shrink-0">audio_file</span>
          <div class="min-w-0">
            <p class="text-[12px] font-inter font-semibold text-primary truncate">${escHtml(e.filename)}</p>
            <p class="text-[9px] font-inter text-muted/30 mt-0.5">${e.date} · ${e.language} · ${e.segments} сегм.</p>
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <a href="/history/${e.id}/txt"
             class="px-2.5 py-1.5 rounded border border-border/20 text-[10px] font-inter font-semibold
                    text-muted/50 hover:text-primary hover:border-accent/40 hover:bg-surface transition-all"
             download>TXT</a>
          <a href="/history/${e.id}/srt"
             class="px-2.5 py-1.5 rounded border border-border/20 text-[10px] font-inter font-semibold
                    text-muted/50 hover:text-primary hover:border-accent/40 hover:bg-surface transition-all"
             download>SRT</a>
          ${e.has_audio ? `
          <a href="/history/${e.id}/audio"
             class="px-2.5 py-1.5 rounded border border-border/20 text-[10px] font-inter font-semibold
                    text-muted/50 hover:text-primary hover:border-accent/40 hover:bg-surface transition-all"
             download>Аудио</a>` : ''}
          <button onclick="deleteHistoryEntry('${e.id}', this)"
                  class="ml-1 p-1.5 rounded opacity-0 group-hover:opacity-100 transition-all
                         hover:bg-red-950/30 hover:text-red-400/70 text-muted/30"
                  title="Удалить">
            <span class="material-symbols-outlined text-sm">delete</span>
          </button>
        </div>
      </div>`).join('');

  } catch {
    spinner.classList.add('hidden');
    empty.classList.remove('hidden');
    document.getElementById('history-empty-text').textContent = 'Ошибка загрузки истории';
  }
}

async function deleteHistoryEntry(id, btn) {
  const row = btn.closest('div.flex');
  await fetch(`/history/${id}`, { method: 'DELETE' });
  row.remove();
  const list = document.getElementById('history-list');
  if (!list.children.length) {
    document.getElementById('history-empty').classList.remove('hidden');
  }
}

// ── Analysis: auth ─────────────────────────────────────────────────────────
const SUMMARY_API = 'https://effective-resolved-gauntlet.ngrok-free.dev';
const SUMMARY_HEADERS = { 'ngrok-skip-browser-warning': '1' };
let anUserKey  = localStorage.getItem('an_user_key')  || '';
let anUserName = localStorage.getItem('an_user_name') || '';
let anOptions  = { participants: '2', meeting_type: 'team', goal: 'tasks', mode: 'full' };
let anSourceId = null; // null = текущая сессия, string = history entry id

function renderAnalysisView() {
  if (anUserKey) {
    showAnalysisMain();
  } else {
    document.getElementById('analysis-auth').classList.remove('hidden');
    document.getElementById('analysis-main').classList.add('hidden');
  }
}

async function authSubmit() {
  const key = document.getElementById('auth-key-input').value.trim();
  if (!key) return;

  const icon  = document.getElementById('auth-btn-icon');
  const label = document.getElementById('auth-btn-label');
  const err   = document.getElementById('auth-error');
  icon.classList.add('spin'); label.textContent = 'Проверяю...'; err.classList.add('hidden');

  try {
    const r = await fetch(`${SUMMARY_API}/validate`, {
      method: 'POST', headers: { ...SUMMARY_HEADERS, 'X-User-Key': key }
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      anUserKey  = key;
      anUserName = data.name;
      localStorage.setItem('an_user_key',     key);
      localStorage.setItem('an_user_name',    data.name);
      localStorage.setItem('an_tokens_used',  data.tokens_used);
      localStorage.setItem('an_tokens_limit', data.tokens_limit);
      showAnalysisMain();
    } else {
      err.textContent = data.detail || 'Неверный ключ';
      err.classList.remove('hidden');
    }
  } catch {
    err.textContent = 'Нет соединения с сервером';
    err.classList.remove('hidden');
  }
  icon.classList.remove('spin'); label.textContent = 'Войти';
}

function showAnalysisMain() {
  document.getElementById('analysis-auth').classList.add('hidden');
  document.getElementById('analysis-main').classList.remove('hidden');
  document.getElementById('analysis-user-name').textContent = anUserName;
  const used  = parseInt(localStorage.getItem('an_tokens_used')  || 0);
  const limit = parseInt(localStorage.getItem('an_tokens_limit') || 0);
  document.getElementById('analysis-tokens').textContent = limit
    ? `${used.toLocaleString('ru')} / ${limit.toLocaleString('ru')}`
    : `${used.toLocaleString('ru')}`;
  renderHistory();
  loadAnalysisSources();
}

async function loadAnalysisSources() {
  const select = document.getElementById('an-source-select');
  if (!select) return;

  const prevVal = select.value;
  select.innerHTML = '<option value="">— Текущая транскрибация —</option>';

  try {
    const r       = await fetch('/history');
    const entries = await r.json();
    entries.forEach(e => {
      const opt = document.createElement('option');
      opt.value       = e.id;
      opt.textContent = `${e.filename}  ·  ${e.date}`;
      select.appendChild(opt);
    });
    // Восстанавливаем выбор если запись ещё есть
    if (prevVal && [...select.options].some(o => o.value === prevVal)) {
      select.value = prevVal;
    }
  } catch {}
}

function anSourceChanged(select) {
  anSourceId = select.value || null;
  // Автозаполнение названия из имени файла (только если поле пустое)
  if (anSourceId) {
    const label = select.options[select.selectedIndex].textContent;
    const fname = label.split('·')[0].trim().replace(/\.[^/.]+$/, '');
    const titleEl = document.getElementById('an-title');
    if (!titleEl.value) titleEl.value = fname;
  }
}

function authLogout() {
  anUserKey = ''; anUserName = '';
  ['an_user_key','an_user_name','an_tokens_used','an_tokens_limit'].forEach(k => localStorage.removeItem(k));
  document.getElementById('auth-key-input').value = '';
  document.getElementById('analysis-main').classList.add('hidden');
  document.getElementById('analysis-auth').classList.remove('hidden');
}

// ── Analysis: option selector ──────────────────────────────────────────────
const AN_ACTIVE   = ['border-accent/35', 'bg-surface', 'text-primary'];
const AN_INACTIVE = ['border-border/20', 'text-muted/40', 'hover:text-muted/70', 'hover:bg-surface/20'];

function anSelect(group, value, btn) {
  anOptions[group] = value;
  document.querySelectorAll(`.an-opt-${group}`).forEach(b => {
    const active = b === btn;
    AN_ACTIVE.forEach(c   => b.classList.toggle(c, active));
    AN_INACTIVE.forEach(c => b.classList.toggle(c, !active));
  });
}

function anStepParticipants(delta) {
  const input = document.getElementById('an-participants-input');
  const val = Math.max(2, Math.min(50, (parseInt(input.value) || 2) + delta));
  input.value = val;
  anOptions.participants = val;
}

// ── Analysis: generate ─────────────────────────────────────────────────────
async function generateAnalysis() {
  const status = document.getElementById('an-status');
  let transcript = '';

  if (anSourceId) {
    // Загружаем TXT из истории
    try {
      const r = await fetch(`/history/${anSourceId}/txt`);
      if (!r.ok) throw new Error();
      transcript = await r.text();
    } catch {
      status.textContent = 'Не удалось загрузить транскрипт из истории';
      return;
    }
  } else {
    transcript = allSegments.length
      ? allSegments.map(s => `[${s.start} --> ${s.end}]\n${s.text}`).join('\n\n')
      : '';
  }

  if (!transcript) {
    status.textContent = 'Выбери транскрипт: текущую сессию или файл из истории';
    return;
  }

  const title        = document.getElementById('an-title').value.trim() || 'Анализ созвона';
  const customPrompt = document.getElementById('an-custom-prompt').value.trim();
  const btn          = document.getElementById('an-submit-btn');
  const icon         = document.getElementById('an-btn-icon');
  const label        = document.getElementById('an-btn-label');

  btn.disabled = true;
  icon.classList.add('spin'); label.textContent = 'Анализирую...';
  status.textContent = 'Отправляю транскрипт, это займёт ~30 секунд...';

  try {
    const r = await fetch(`${SUMMARY_API}/summarize`, {
      method: 'POST',
      headers: { ...SUMMARY_HEADERS, 'Content-Type': 'application/json', 'X-User-Key': anUserKey },
      body: JSON.stringify({
        transcript,
        title,
        participants:  parseInt(anOptions.participants),
        meeting_type:  anOptions.meeting_type,
        goal:          anOptions.goal,
        mode:          anOptions.mode,
        custom_prompt: customPrompt,
      }),
    });

    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      status.textContent = err.detail || `Ошибка ${r.status}`;
      return;
    }

    const html = await r.text();
    status.textContent = 'Готово — скачиваю файл';

    const filename = title.replace(/[^а-яёА-ЯЁa-zA-Z0-9 _-]/g, '').trim() || 'Анализ';
    const a = document.createElement('a');
    a.href     = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    a.download = `${filename}.html`;
    a.click();
    URL.revokeObjectURL(a.href);

    saveHistory({ title, date: new Date().toLocaleDateString('ru-RU'), html });
    renderHistory();

    fetch(`${SUMMARY_API}/validate`, { method: 'POST', headers: { ...SUMMARY_HEADERS, 'X-User-Key': anUserKey } })
      .then(r => r.json()).then(d => {
        if (d.ok) {
          localStorage.setItem('an_tokens_used',  d.tokens_used);
          localStorage.setItem('an_tokens_limit', d.tokens_limit);
          const used  = d.tokens_used;
          const limit = d.tokens_limit;
          document.getElementById('analysis-tokens').textContent = limit
            ? `${used.toLocaleString('ru')} / ${limit.toLocaleString('ru')}`
            : `${used.toLocaleString('ru')}`;
        }
      }).catch(() => {});

    setTimeout(() => { status.textContent = ''; }, 4000);

  } catch {
    status.textContent = 'Нет соединения с сервером';
  } finally {
    btn.disabled = false;
    icon.classList.remove('spin'); label.textContent = 'Сформировать анализ';
  }
}

// ── Analysis: history (localStorage) ──────────────────────────────────────
const HISTORY_KEY   = 'an_history';
const HISTORY_LIMIT = 20;

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; }
}

function saveHistory(entry) {
  const list = loadHistory();
  list.unshift({ id: Date.now(), ...entry });
  if (list.length > HISTORY_LIMIT) list.length = HISTORY_LIMIT;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(list));
}

function clearHistory() {
  if (!confirm('Очистить всю историю анализов?')) return;
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
}

function renderHistory() {
  const list    = loadHistory();
  const section = document.getElementById('an-history-section');
  const ul      = document.getElementById('an-history-list');
  if (!list.length) { section.classList.add('hidden'); return; }
  section.classList.remove('hidden');
  ul.innerHTML = list.map(e => `
    <div class="flex items-center justify-between py-2 px-3 rounded hover:bg-surface/30 transition-colors group">
      <div class="flex items-center gap-2.5 min-w-0">
        <span class="material-symbols-outlined text-sm text-muted/30 shrink-0">description</span>
        <div class="min-w-0">
          <p class="text-[11px] font-inter font-medium text-primary/70 truncate">${escHtml(e.title)}</p>
          <p class="text-[9px] font-inter text-muted/30">${e.date}</p>
        </div>
      </div>
      <button onclick="redownload(${e.id})"
              class="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded hover:bg-surface shrink-0"
              title="Скачать снова">
        <span class="material-symbols-outlined text-sm text-muted/40">download</span>
      </button>
    </div>`).join('');
}

function redownload(id) {
  const entry = loadHistory().find(e => e.id === id);
  if (!entry) return;
  const filename = entry.title.replace(/[^а-яёА-ЯЁa-zA-Z0-9 _-]/g, '').trim() || 'Анализ';
  const a = document.createElement('a');
  a.href     = URL.createObjectURL(new Blob([entry.html], { type: 'text/html;charset=utf-8' }));
  a.download = `${filename}.html`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Init ───────────────────────────────────────────────────────────────────
renderModels();
renderLangs();

(function () {
  const saved = localStorage.getItem('theme');
  if (saved === 'light') {
    document.documentElement.classList.replace('dark', 'light');
    document.getElementById('theme-icon').textContent = 'dark_mode';
  }
})();
