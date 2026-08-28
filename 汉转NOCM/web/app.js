(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const clone = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value ?? '').replace(/[&<>"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'
  })[ch]);

  const MAP_SECTIONS = [
    ['tone', '声调'], ['coda', '韵尾'], ['nucleus', '韵核'],
    ['onset', '声母'], ['glide', '介音'], ['residual', '其余映射']
  ];
  const RULE_SECTIONS = [
    ['pre_normalize', '预处理'], ['residual_preprocess', '剩余项预处理'],
    ['residual_replace', '剩余项替换'], ['pharyngeal_relax', '咽化改善'],
    ['syllable_relax', '音节改善'], ['post_replace', '最终替换']
  ];
  const SECTION_NAMES = Object.fromEntries(MAP_SECTIONS);

  let api = null;
  let state = null;
  let editor = null;
  let inspectorCell = null;
  let richClipboard = null;
  let selectionCopyMode = 'raw';
  let visualNavX = null;
  let highlightMode = false;
  let search = { visible: false, query: '', scope: 'all', matches: [], index: 0 };
  let draftLibraryQuery = '';
  let exportMode = 'phon';
  let exportOptionsInitialized = false;
  let imageExport = { title: '正文', lines: [], hidden: new Set(), ready: false };
  let schemeDraft = null;
  let schemePickerId = null;
  let schemePickerFilter = 'active';
  let schemeTab = 'options';
  let schemeUndo = [];
  let schemeRedo = [];
  let lookupTarget = null;
  let mouseSelecting = false;
  let mouseMoved = false;
  let mouseDown = null;
  let composing = false;
  let dragPayload = null;
  let actionQueue = Promise.resolve();
  let maintenanceTab = 'about';
  let dataChangeView = {
    batches: [], batchTotal: 0, selected: null,
    entries: [], entryTotal: 0, query: '', loading: false, requestId: 0,
  };
  let dataChangeFocus = null;
  let dataChangeSearchTimer = null;
  let startupErrorReport = '';
  let availableUpdate = null;
  let downloadedUpdate = null;
  let automaticUpdateCheckStarted = false;
  let scrollSaveTimer = null;
  let imageResizeTimer = null;
  let backendLogTimer = null;
  let startupOutputTimer = null;
  let editorZoom = 1;
  let editorZoomSaveTimer = null;

  function toast(message, kind = '') {
    const node = document.createElement('div');
    node.className = `toast ${kind}`;
    node.textContent = message;
    $('#toast-stack').append(node);
    setTimeout(() => node.remove(), 2600);
  }

  function queue(task) {
    actionQueue = actionQueue.then(task).catch(error => {
      toast(error?.message || String(error), 'error');
      console.error(error);
    });
    return actionQueue;
  }

  async function invoke(method, ...args) {
    if (!api || typeof api[method] !== 'function') throw new Error(`API 不可用: ${method}`);
    return api[method](...args);
  }

  function createAndroidApi(bridge) {
    document.documentElement.dataset.platform = 'android';
    return new Proxy({}, {
      get(_target, method) {
        if (method === 'then') return undefined;
        return async (...args) => {
          const response = JSON.parse(bridge.invoke(String(method), JSON.stringify(args)));
          if (!response.ok) {
            const error = new Error(response.error || `Android API 调用失败: ${String(method)}`);
            error.details = response.details;
            throw error;
          }
          return response.value;
        };
      }
    });
  }

  function closeMobilePanels() {
    document.body.classList.remove('mobile-library-open', 'mobile-inspector-open');
  }

  function setUtilitybarVisible(visible) {
    if (visible && search.visible) setSearchVisible(false, false);
    $('#utilitybar').classList.toggle('hidden', !visible);
    $('#tools-button').setAttribute('aria-expanded', String(visible));
  }

  function setSearchVisible(visible, restoreFocus = true) {
    search.visible = visible;
    $('#searchbar').classList.toggle('hidden', !visible);
    if (visible) {
      setUtilitybarVisible(false);
      $('#search-input').focus();
      $('#search-input').select();
    } else {
      search.query = '';
      $('#search-input').value = '';
      renderEditor();
      if (restoreFocus) focusEditor();
    }
  }

  function closeSearch() {
    setSearchVisible(false);
  }

  function closeStartupOutput() {
    clearTimeout(startupOutputTimer);
    startupOutputTimer = null;
    $('#startup-output-card').classList.add('hidden');
    document.body.classList.remove('startup-output-visible');
  }

  function setDesktopWindowMaximized(maximized) {
    document.documentElement.classList.toggle('window-maximized', Boolean(maximized));
    $$('[data-window-action="maximize"]').forEach(button => {
      button.setAttribute('aria-label', maximized ? '还原窗口' : '最大化');
      button.title = maximized ? '还原' : '最大化';
    });
  }

  async function runWindowAction(action) {
    if (document.documentElement.dataset.platform === 'android') return;
    if (action === 'minimize') {
      await invoke('minimize_window');
    } else if (action === 'maximize') {
      const result = await invoke('toggle_maximize_window');
      setDesktopWindowMaximized(result?.maximized);
    } else if (action === 'close') {
      clearTimeout(editorZoomSaveTimer);
      editorZoomSaveTimer = null;
      await invoke('set_ui_preference', 'editor_zoom', editorZoom);
      await invoke('close_window');
    }
  }

  window.setDesktopWindowMaximized = setDesktopWindowMaximized;

  async function refreshBackendLogs() {
    const payload = await invoke('get_backend_logs');
    const output = $('#backend-log-output');
    const followsEnd = output.scrollHeight - output.scrollTop - output.clientHeight < 28;
    const text = String(payload?.text || '').trimEnd();
    output.textContent = text || '暂无后台输出';
    output.classList.toggle('empty', !text);
    $('#backend-log-meta').textContent = `本次运行开始于 ${formatDate(payload?.started_at) || '未知时间'} · ${Number(payload?.characters || 0).toLocaleString()} 字符`;
    if (followsEnd) output.scrollTop = output.scrollHeight;
    return payload;
  }

  async function openBackendLogs() {
    closeStartupOutput();
    setUtilitybarVisible(false);
    const dialog = $('#backend-log-dialog');
    if (!dialog.open) dialog.showModal();
    await refreshBackendLogs();
    clearInterval(backendLogTimer);
    backendLogTimer = setInterval(() => {
      if (!dialog.open) return clearInterval(backendLogTimer);
      refreshBackendLogs().catch(() => {});
    }, 900);
  }

  async function showStartupOutput() {
    try {
      const payload = await invoke('get_backend_logs');
      const text = String(payload?.text || '').trim();
      if (!text) return;
      const card = $('#startup-output-card');
      $('#startup-output-text').textContent = text;
      card.classList.remove('hidden');
      document.body.classList.add('startup-output-visible');
      $('#startup-output-text').scrollTop = $('#startup-output-text').scrollHeight;
      clearTimeout(startupOutputTimer);
      startupOutputTimer = setTimeout(closeStartupOutput, 15000);
    } catch (_) { /* logs remain optional during startup */ }
  }

  function setLibrarySearchVisible(visible) {
    $('.sidebar-heading').classList.toggle('searching', visible);
    $('#library-search').classList.toggle('hidden', !visible);
    if (visible) {
      $('#library-search-input').focus();
      $('#library-search-input').select();
    } else {
      draftLibraryQuery = '';
      $('#library-search-input').value = '';
      renderDraftTree();
    }
  }

  function applyResult(result) {
    if (!result) return;
    if (result.editor && result.drafts) {
      const previousDraft = editor?.current_draft;
      state = result;
      editor = result.editor;
      applyInspectorWidth(result.ui_preferences?.inspector_width);
      applyEditorZoom(result.ui_preferences?.editor_zoom);
      applyDebugMode(result.ui_preferences?.debug_mode);
      renderAll();
      if (previousDraft !== editor.current_draft || editor.scroll_top) {
        requestAnimationFrame(() => {
          $('#editor-scroll').scrollTop = editor.scroll_top || 0;
          positionInputCapture();
        });
      }
    } else if (result.lines) {
      const previousDraft = state?.editor?.current_draft;
      editor = result;
      if (state) state.editor = result;
      renderEditor();
      renderInspector();
      updateToolbar();
      syncCurrentDraftCompletion();
      if (state && previousDraft !== result.current_draft) {
        invoke('get_state').then(applyResult).catch(() => {});
      }
    } else if (result.state) {
      applyResult(result.state);
    }
  }

  function setTheme(theme, persist = false) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch (_) {}
    if (state) state.theme = theme;
    if ($('#image-export-dialog')?.open) renderImageCanvas();
    if (persist) queue(async () => invoke('set_theme', theme));
  }

  function applyInspectorWidth(value) {
    if (!value) return;
    const maxWidth = Math.max(230, Math.min(520, window.innerWidth - 560));
    const width = Math.max(230, Math.min(maxWidth, Number(value) || 286));
    $('.workspace')?.style.setProperty('--inspector-width', `${width}px`);
  }

  function applyEditorZoom(value) {
    const normalized = Math.max(.7, Math.min(2,
      Math.round((Number(value) || 1) * 10) / 10));
    editorZoom = normalized;
    document.documentElement.style.setProperty('--editor-zoom', String(normalized));
    const status = $('#editor-zoom-status');
    if (status) status.textContent = `${Math.round(normalized * 100)}%`;
    if (state) {
      state.ui_preferences ||= {};
      state.ui_preferences.editor_zoom = normalized;
    }
    return normalized;
  }

  function adjustEditorZoom(event) {
    if (!event.ctrlKey || !event.deltaY) return;
    event.preventDefault();
    const scroll = event.currentTarget;
    if (!scroll) return;
    const rect = scroll.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;
    const contentX = scroll.scrollLeft + localX;
    const contentY = scroll.scrollTop + localY;
    const previous = editorZoom;
    const next = Math.max(.7, Math.min(2,
      Math.round((previous + (event.deltaY < 0 ? .1 : -.1)) * 10) / 10));
    if (next === previous) return;
    applyEditorZoom(next);
    const ratio = next / previous;
    scroll.scrollLeft = contentX * ratio - localX;
    scroll.scrollTop = contentY * ratio - localY;
    clearTimeout(editorZoomSaveTimer);
    editorZoomSaveTimer = setTimeout(() => {
      invoke('set_ui_preference', 'editor_zoom', editorZoom).catch(() => {});
    }, 220);
  }

  function applyDebugMode(enabled) {
    document.body.classList.toggle('debug-mode', Boolean(enabled));
    if (state) {
      state.ui_preferences ||= {};
      state.ui_preferences.debug_mode = Boolean(enabled);
    }
  }

  const EXPORT_OPTION_INPUTS = {
    punct_split: '#punct-split',
    clean_line_breaks: '#clean-line-breaks',
    ignore_bracket_control_lines: '#ignore-bracket-control-lines',
    remove_pharyngeal: '#remove-pharyngeal',
    remove_tones: '#remove-tones',
    remove_glottal_tone: '#remove-glottal-tone',
    extra_h_voiceless_sonorant: '#extra-h-voiceless-sonorant',
    entry_before_glottal: '#entry-before-glottal',
    departing_before_glottal: '#departing-before-glottal',
  };

  function readExportOptions() {
    return Object.fromEntries(Object.entries(EXPORT_OPTION_INPUTS).map(
      ([key, selector]) => [key, Boolean($(selector)?.checked)]));
  }

  function applyExportOptionPreferences(preferences) {
    if (exportOptionsInitialized) return;
    Object.entries(EXPORT_OPTION_INPUTS).forEach(([key, selector]) => {
      const input = $(selector);
      if (input) input.checked = Boolean(preferences?.[key]);
    });
    exportOptionsInitialized = true;
  }

  function persistExportOptions() {
    const options = readExportOptions();
    if (state) {
      state.ui_preferences ||= {};
      state.ui_preferences.export_options = options;
    }
    return queue(async () => invoke('set_ui_preference', 'export_options', options));
  }

  function bindInspectorResize() {
    const handle = $('#inspector-resizer');
    let resizing = null;
    handle.addEventListener('mousedown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      resizing = {
        startX: event.clientX,
        startWidth: $('.inspector-shell').getBoundingClientRect().width,
      };
      handle.classList.add('dragging');
      document.body.classList.add('resizing-inspector');
    });
    window.addEventListener('mousemove', event => {
      if (!resizing) return;
      applyInspectorWidth(
        resizing.startWidth + resizing.startX - event.clientX);
    });
    window.addEventListener('mouseup', () => {
      if (!resizing) return;
      resizing = null;
      handle.classList.remove('dragging');
      document.body.classList.remove('resizing-inspector');
      const width = Math.round(
        $('.inspector-shell').getBoundingClientRect().width);
      invoke('set_ui_preference', 'inspector_width', width).catch(() => {});
    });
  }

  async function initialize() {
    $('#startup-retry').classList.add('hidden');
    $('#startup-copy-error').classList.add('hidden');
    $('#startup-details').classList.add('hidden');
    $('#startup-details').textContent = '';
    startupErrorReport = '';
    const poll = setInterval(async () => {
      try {
        const status = await invoke('get_startup_status');
        $('#startup-message').textContent = status.message || '正在准备数据...';
        $('#startup-progress').style.width = `${status.progress || 4}%`;
      } catch (_) { /* initialization owns the visible error */ }
    }, 180);
    const result = await invoke('initialize');
    clearInterval(poll);
    if (!result?.ok) {
      const message = result?.startup?.error || '启动失败';
      $('#startup-message').textContent = message;
      startupErrorReport = result?.startup?.details || '';
      if (startupErrorReport) {
        $('#startup-details').textContent = startupErrorReport;
        $('#startup-details').classList.remove('hidden');
        $('#startup-copy-error').classList.remove('hidden');
      }
      $('#startup-retry').classList.remove('hidden');
      return;
    }
    state = result;
    editor = result.editor;
    applyInspectorWidth(result.ui_preferences?.inspector_width);
    applyEditorZoom(result.ui_preferences?.editor_zoom);
    applyDebugMode(result.ui_preferences?.debug_mode);
    applyExportOptionPreferences(result.ui_preferences?.export_options);
    $('#startup-version').textContent = `v${result.version || ''}`;
    setTheme(result.theme || 'light');
    $('#startup').classList.add('hidden');
    $('#app').classList.remove('hidden');
    renderAll();
    focusEditor();
    showStartupOutput();
    if (!automaticUpdateCheckStarted
        && result.ui_preferences?.auto_check_updates !== false) {
      automaticUpdateCheckStarted = true;
      setTimeout(() => checkUpdates(true), 1400);
    }
  }

  function renderAll() {
    renderDraftTree();
    renderEditor();
    renderInspector();
    fillSchemes();
    updateToolbar();
  }

  function updateToolbar() {
    if (!editor) return;
    $('#document-title').textContent = editor.current_name || '未命名文稿';
    $('#undo-button').disabled = !editor.can_undo;
    $('#redo-button').disabled = !editor.can_redo;
    const highlightButton = $('#highlight-button');
    const highlightCount = editor.lines.reduce(
      (count, line) => count + line.filter(cell => cell.manual_hl).length, 0);
    highlightButton.classList.toggle('active', highlightMode);
    highlightButton.textContent = highlightMode ? '退出高亮' : '高亮';
    highlightButton.title = highlightMode ? '退出高亮模式 (Esc)' : '进入高亮模式';
    $('#highlight-mode-banner').classList.toggle('hidden', !highlightMode);
    $('#highlight-mode-count').textContent = `已标记 ${highlightCount} 字`;
    document.body.classList.toggle('highlight-mode-active', highlightMode);
    $('#save-state').textContent = editor.dirty ? '正在保存...' : '已自动保存';
    const [line, column] = editor.cursor;
    $('#cursor-status').textContent = `第 ${line + 1} 行，第 ${column + 1} 列`;
    const count = selectionCount(editor.selection);
    $('#selection-status').textContent = count ? `已选择 ${count} 个字` : '';
  }

  function setHighlightMode(enabled) {
    highlightMode = Boolean(enabled);
    updateToolbar();
    focusEditor();
  }

  function isInSelection(line, column) {
    if (!editor?.selection) return false;
    const [start, end] = editor.selection;
    const pos = [line, column];
    const compare = (a, b) => a[0] === b[0] ? a[1] - b[1] : a[0] - b[0];
    return compare(pos, start) >= 0 && compare(pos, end) < 0;
  }

  function selectionCount(selection) {
    if (!selection || !editor) return 0;
    const [[sl, sc], [el, ec]] = selection;
    if (sl === el) return ec - sc;
    let count = editor.lines[sl].length - sc + ec;
    for (let line = sl + 1; line < el; line++) count += editor.lines[line].length;
    return count;
  }

  function searchKey(line, column) { return `${line}:${column}`; }

  function recomputeSearch(render = false) {
    search.matches = [];
    const query = search.query.trim().toLowerCase();
    if (query && editor) {
      const seen = new Set();
      editor.lines.forEach((line, li) => {
        if (search.scope !== 'phon') {
          const raw = line.map(cell => cell.char).join('').toLowerCase();
          let start = 0;
          while (true) {
            const index = raw.indexOf(query, start);
            if (index < 0) break;
            seen.add(searchKey(li, index));
            start = index + Math.max(1, query.length);
          }
        }
        if (search.scope !== 'char') line.forEach((cell, ci) => {
          if (cell.phonetic.toLowerCase().includes(query)) seen.add(searchKey(li, ci));
        });
      });
      search.matches = [...seen].map(key => key.split(':').map(Number));
    }
    if (search.index >= search.matches.length) search.index = 0;
    $('#search-count').textContent = !query ? '' : search.matches.length
      ? `${search.index + 1}/${search.matches.length}` : '无匹配';
    if (render) renderEditor();
  }

  function renderEditor() {
    if (!editor) return;
    recomputeSearch(false);
    const hits = new Set(search.matches.map(([li, ci]) => searchKey(li, ci)));
    const currentHit = search.matches[search.index]
      ? searchKey(...search.matches[search.index]) : '';
    const root = $('#editor');
    root.innerHTML = '';
    editor.lines.forEach((line, li) => {
      const lineNode = document.createElement('div');
      const bracketOnly = line.length > 0 && line.every(cell => cell.in_bracket);
      lineNode.className = `editor-line${bracketOnly ? ' bracket-only' : ''}`;
      lineNode.dataset.line = li;
      line.forEach((cell, ci) => {
        if (editor.cursor[0] === li && editor.cursor[1] === ci) lineNode.append(makeCaret());
        const node = document.createElement('div');
        const key = searchKey(li, ci);
        node.className = [
          'cell', cell.is_poly ? 'poly' : '', cell.in_bracket ? 'bracket' : '',
          cell.missing_phonetic ? 'missing-phonetic' : '',
          cell.manual_hl ? 'manual-highlight' : '', cell.stale ? 'stale' : '',
          cell.selected !== 'none' ? `selected-${cell.selected}` : '',
          isInSelection(li, ci) ? 'in-selection' : '',
          hits.has(key) ? 'search-hit' : '', key === currentHit ? 'search-current' : ''
        ].filter(Boolean).join(' ');
        node.dataset.line = li;
        node.dataset.column = ci;
        node.innerHTML = `<span class="cell-char">${esc(cell.char)}</span><span class="cell-phon" title="${esc(cell.phonetic)}">${esc(cell.phonetic)}</span>`;
        lineNode.append(node);
      });
      if (editor.cursor[0] === li && editor.cursor[1] === line.length) lineNode.append(makeCaret());
      root.append(lineNode);
    });
    $('#empty-editor').classList.toggle('hidden', Boolean(editor.raw));
    positionInputCapture();
    updateToolbar();
  }

  function makeCaret() {
    const caret = document.createElement('span');
    caret.className = 'caret';
    return caret;
  }

  function positionInputCapture() {
    const caret = $('.caret');
    const capture = $('#input-capture');
    if (!caret) return;
    const outer = $('#editor-scroll').getBoundingClientRect();
    const rect = caret.getBoundingClientRect();
    capture.style.left = `${rect.left - outer.left + $('#editor-scroll').scrollLeft}px`;
    capture.style.top = `${rect.top - outer.top + $('#editor-scroll').scrollTop + 28}px`;
  }

  function focusEditor() {
    const capture = $('#input-capture');
    capture.value = '';
    capture.focus({ preventScroll: true });
    positionInputCapture();
  }

  async function setCaret(line, column, extend = false, preserveVisualX = false) {
    if (!preserveVisualX) visualNavX = null;
    const result = await invoke('set_caret', line, column, extend);
    applyResult(result);
  }

  function renderInspector() {
    const root = $('#inspector');
    if (!editor) return;
    if (editor.selection) {
      const count = selectionCount(editor.selection);
      root.innerHTML = `
        <div class="selection-summary">
          <div><span class="eyebrow">选区</span><div class="selection-count">${count} 个字</div></div>
          <div class="segmented" id="copy-mode"><button data-value="raw" class="${selectionCopyMode === 'raw' ? 'active' : ''}">原文</button><button data-value="phon" class="${selectionCopyMode === 'phon' ? 'active' : ''}">音标</button></div>
          <div class="inspector-actions">
            <button class="button" id="copy-selection">复制</button>
            <button class="button" id="cut-selection">剪切</button>
            <button class="button danger" id="delete-selection">删除</button>
          </div>
        </div>`;
      $('#copy-mode').addEventListener('click', event => {
        const button = event.target.closest('button');
        if (!button) return;
        selectionCopyMode = button.dataset.value;
        $$('#copy-mode button').forEach(item => item.classList.toggle('active', item === button));
      });
      $('#copy-selection').onclick = () => copySelection(selectionCopyMode);
      $('#cut-selection').onclick = () => cutSelection();
      $('#delete-selection').onclick = () => queue(async () => applyResult(await invoke('delete_selection')));
      return;
    }
    if (inspectorCell) {
      const { line, column } = inspectorCell;
      invoke('get_cell_details', line, column).then(details => {
        if (!details || editor.selection || !inspectorCell
            || inspectorCell.line !== line || inspectorCell.column !== column) return;
        inspectorCell = details;
        const options = details.options || [];
        const unrecorded = options.length === 0;
        const updatePanel = readingUpdateHtml(details);
        root.innerHTML = `
          <div class="inspector-title">
            <div><h2>${details.stale ? '读音更新待确认' : details.is_poly ? '选择读音' : '字词信息'}</h2><p class="${details.stale ? 'reading-stale' : ''}">${unrecorded ? '未收录' : esc(details.phonetic)}${details.stale ? ' · 文稿原读音' : ''}</p></div>
            <span class="inspector-char">${esc(details.char)}</span>
          </div>
          ${updatePanel}
          <div class="reading-list">${unrecorded ? '<div class="reading-empty">该字符不在数据库中</div>' : options.map(option => readingOptionHtml(option, details)).join('')}</div>`;
        $$('[data-reading-local]', root).forEach(button => button.onclick = () => applyReading(button.dataset.phonetic, false));
        $$('[data-update-reading]', root).forEach(button => button.onclick = () => reviewCellUpdate(
          button.dataset.updateReading, 'accept', button.dataset.phonetic));
        $$('[data-reading-global]', root).forEach(button => button.onclick = event => {
          event.stopPropagation();
          applyReading(button.dataset.phonetic, true);
        });
        $$('[data-update-keep]', root).forEach(button => button.onclick = () => reviewCellUpdate(
          button.dataset.updateKeep, 'keep'));
        $$('[data-update-view]', root).forEach(button => button.onclick = () => {
          const event = [...(details.pending_updates || []), ...(details.confirmed_updates || [])]
            .find(item => item.id === button.dataset.updateView);
          if (event) openDataChangeEvent(event);
        });
        $$('[data-update-reopen]', root).forEach(button => button.onclick = () => reopenCellUpdate(
          button.dataset.updateReopen, false));
        $$('[data-update-restore]', root).forEach(button => button.onclick = () => reopenCellUpdate(
          button.dataset.updateRestore, true));
      }).catch(error => toast(error.message, 'error'));
      return;
    }
    root.innerHTML = '<div class="inspector-placeholder"><strong>读音与字词信息</strong><span>点击正文中的字查看</span></div>';
  }

  function readingUpdateHtml(details) {
    const pending = details.pending_updates || [];
    const confirmed = details.confirmed_updates || [];
    const pendingHtml = pending.map(event => `<section class="reading-update-card pending">
      <div class="reading-update-heading"><strong>${esc(event.timestamp)} 的词库更新</strong><span>待确认</span></div>
      <p>${esc(event.summary || '当前文稿读音已不在新词库中。')}</p>
      <div class="reading-update-actions"><button class="button" data-update-keep="${esc(event.id)}">保留当前读音</button><button class="button subtle" data-update-view="${esc(event.id)}">查看完整更新</button></div>
    </section>`).join('');
    const confirmedHtml = confirmed.length ? `<details class="reading-update-history">
      <summary>已确认更新 ${confirmed.length}</summary>
      ${confirmed.map(event => {
        const review = event.review || {};
        const decision = review.status === 'accepted_new'
          ? `${esc(review.before)} → ${esc(review.after)}` : `保留 ${esc(review.after)}`;
        return `<section class="reading-update-card confirmed">
          <div class="reading-update-heading"><strong>${esc(event.timestamp || '历史更新')}</strong><span>已确认</span></div>
          <p>${decision}</p>
          <div class="reading-update-actions"><button class="button subtle" data-update-view="${esc(event.id)}">查看更新</button><button class="button subtle" data-update-reopen="${esc(event.id)}">重新审阅</button>${review.status === 'accepted_new' ? `<button class="button subtle" data-update-restore="${esc(event.id)}">恢复原读音</button>` : ''}</div>
        </section>`;
      }).join('')}
    </details>` : '';
    return pendingHtml || confirmedHtml ? `<div class="reading-updates">${pendingHtml}${confirmedHtml}</div>` : '';
  }

  function optionPhonetic(option) {
    return typeof option === 'string' ? option : option.phonetic || '';
  }

  function readingOptionHtml(option, details) {
    const phonetic = optionPhonetic(option);
    const note = typeof option === 'object'
      ? option.note || option.definition || option.gloss || option.fanqie || '' : '';
    const pending = (details.pending_updates || [])[0];
    const current = !pending && phonetic === details.phonetic;
    const selectable = details.is_poly || Boolean(pending);
    const localTag = selectable ? 'button' : 'span';
    const localAttr = pending
      ? `data-update-reading="${esc(pending.id)}" data-phonetic="${esc(phonetic)}"`
      : details.is_poly ? `data-reading-local data-phonetic="${esc(phonetic)}"` : '';
    const globalButton = details.is_poly && details.same_char_count > 1
      ? `<button class="reading-global" data-reading-global data-phonetic="${esc(phonetic)}">全局</button>` : '';
    return `<div class="reading-option ${current ? 'active' : ''}">
      <div class="reading-head"><${localTag} class="reading-local" ${localAttr}><span class="reading-phon">${esc(phonetic)}</span>${current ? '<span class="reading-current">已选</span>' : ''}</${localTag}>${globalButton}</div>
      ${note ? `<button class="reading-note" ${localAttr}>${formatReadingNote(note)}</button>` : ''}
    </div>`;
  }

  function formatReadingNote(value) {
    const text = String(value || '').trim().replace(
      /([^\n\d])(\d+)(?=[\u3400-\u9fff])/g, '$1\n$2');
    const pattern = /《[^》]*》|(?:^|\n)\d+(?=[\u3400-\u9fff])/g;
    let output = '';
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      output += esc(text.slice(cursor, match.index));
      const token = match[0];
      if (token.startsWith('《')) {
        output += `<span class="note-book">${esc(token)}</span>`;
      } else {
        const newline = token.startsWith('\n') ? '\n' : '';
        const number = token.slice(newline.length);
        output += `${newline}<span class="note-index">${esc(number)}</span> `;
      }
      cursor = match.index + token.length;
    }
    return output + esc(text.slice(cursor));
  }

  async function applyReading(phonetic, globalApply) {
    const { line, column } = inspectorCell;
    let overwrite = false;
    const skipped = [];
    if (globalApply) {
      const conflicts = await invoke('reading_conflicts', line, column, phonetic);
      for (let index = 0; index < conflicts.length; index += 1) {
        const choice = await readingConflictBox(
          conflicts[index], inspectorCell.char, phonetic, index + 1, conflicts.length);
        if (choice === 'cancel') return;
        if (choice === 'skip') skipped.push([
          conflicts[index].line, conflicts[index].column]);
      }
      overwrite = conflicts.length > 0;
    }
    applyResult(await invoke(
      'apply_reading', line, column, phonetic, globalApply, overwrite, skipped));
    inspectorCell = { line, column };
    renderInspector();
  }

  async function reviewCellUpdate(eventId, action, phonetic = null) {
    const { line, column } = inspectorCell;
    const result = await invoke(
      'review_cell_update', line, column, eventId, action, phonetic);
    applyResult(result);
    inspectorCell = { line, column };
    renderInspector();
  }

  async function reopenCellUpdate(eventId, restoreReading) {
    const { line, column } = inspectorCell;
    const result = await invoke(
      'reopen_cell_update', line, column, eventId, restoreReading);
    applyResult(result);
    inspectorCell = { line, column };
    renderInspector();
  }

  function readingConflictBox(conflict, char, phonetic, index, total) {
    const sentence = String(conflict.context || '');
    const column = Number(conflict.column || 0);
    const start = Math.max(0, column - 15);
    const end = Math.min(sentence.length, column + 16);
    const context = `${start ? '…' : ''}${sentence.slice(start, column)}【${char}】${sentence.slice(column + 1, end)}${end < sentence.length ? '…' : ''}`;
    return new Promise(resolve => {
      const dialog = $('#reading-conflict-dialog');
      $('#reading-conflict-message').textContent = `冲突 ${index}/${total} · 第 ${Number(conflict.line) + 1} 行\n${context}\n\n该处已手动选为 ${conflict.phonetic}，是否替换为 ${phonetic}？`;
      dialog.onclose = () => resolve(dialog.returnValue || 'cancel');
      dialog.showModal();
    });
  }

  async function copySelection(mode = 'raw') {
    let text;
    if (mode === 'phon') {
      text = await invoke('get_phonetic_text', true);
      richClipboard = null;
    } else {
      const payload = await invoke('get_copy_payload', true);
      text = payload?.text || '';
      richClipboard = payload;
    }
    if (text) {
      await writeClipboard(text);
      toast('已复制');
    }
  }

  async function cutSelection() {
    const payload = await invoke('get_copy_payload', true);
    if (!payload?.text || !editor.selection) return;
    richClipboard = payload;
    await writeClipboard(payload.text);
    applyResult(await invoke('delete_selection'));
    toast('已剪切');
  }

  async function writeClipboard(text) {
    try { await navigator.clipboard.writeText(text); }
    catch (_) {
      const area = document.createElement('textarea');
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
  }

  function normalizeClipboardText(text) {
    return String(text || '').replace(/\r\n?/g, '\n');
  }

  function renderDraftTree() {
    if (!state) return;
    const root = $('#draft-tree');
    const query = draftLibraryQuery.trim().toLocaleLowerCase();
    if (query) {
      const matches = state.drafts.filter(draft => [
        draft.name, draft.preview, draft.filename,
      ].some(value => String(value || '').toLocaleLowerCase().includes(query)));
      const results = matches.map(item => draftHtml(item, '', false, true)).join('');
      root.innerHTML = `<div class="tree-section-label">搜索结果 · ${matches.length}</div><div class="library-search-results">${results || '<div class="folder-empty">没有匹配的文稿</div>'}</div>`;
      bindDraftTree();
      return;
    }
    const draftMap = new Map(state.drafts.map(item => [item.filename, item]));
    const grouped = new Set();
    const groupHtml = groups => groups.map(group => {
      group.files.forEach(file => grouped.add(file));
      const children = groupHtml(group.children || []);
      const files = group.files.map(file => draftMap.has(file) ? draftHtml(draftMap.get(file), group.id) : '').join('');
      const empty = !files && !children ? '<div class="folder-empty">（空文件夹）</div>' : '';
      return `<div class="folder ${group.expanded ? '' : 'collapsed'}" data-group="${esc(group.id)}">
        <div class="folder-row" draggable="true" data-kind="group" data-id="${esc(group.id)}">
          <span class="folder-toggle" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"></path></svg></span>
          <span class="folder-icon" aria-hidden="true">
            <svg class="folder-icon-closed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"></path></svg>
            <svg class="folder-icon-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 7.5v-1a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1"></path><path d="M4.5 9.5h16.8l-2.2 8.3a2 2 0 0 1-1.9 1.5H5.8a2 2 0 0 1-1.9-2.5l1.9-6a2 2 0 0 1 1.9-1.3z"></path></svg>
          </span>
          <span class="folder-name">${esc(group.name)}</span>
          <button class="tree-menu" data-menu="group" title="文件夹操作" aria-label="文件夹操作">•••</button>
        </div>
        <div class="folder-children">${files}${children}${empty}</div>
      </div>`;
    }).join('');
    const groups = groupHtml(state.groups || []);
    const ungrouped = state.drafts.filter(item => !grouped.has(item.filename)).map(item => draftHtml(item, '')).join('');
    const recent = (state.recent_drafts || []).map(item => draftHtml(item, '', true)).join('');
    root.innerHTML = `${recent ? `<div class="tree-section-label">最近打开</div><div class="recent-drafts">${recent}</div>` : ''}${groups}<div class="tree-section-label">未分组</div><div class="ungrouped-drop">${ungrouped || '<div class="draft-preview" style="padding:8px">暂无文稿</div>'}</div>`;
    bindDraftTree();
  }

  function draftHtml(draft, groupId, recent = false, searchResult = false) {
    const active = draft.filename === editor?.current_draft ? 'active' : '';
    const pendingCount = Math.max(0, Number(draft.unselected_polyphonic) || 0);
    const completed = Boolean(draft.manually_completed);
    const statusClass = completed ? 'completed' : pendingCount ? 'incomplete' : '';
    const stale = draft.stale
      ? '<span class="draft-stale" role="img" aria-label="包含词库读音已更新的字" title="包含词库读音已更新的字"></span>' : '';
    return `<div class="draft-row ${active} ${statusClass} ${recent ? 'recent-row' : ''}" draggable="${recent || searchResult ? 'false' : 'true'}" data-kind="draft" data-id="${esc(draft.filename)}" data-group-id="${esc(groupId)}">
      <div class="draft-main"><div class="draft-name-row"><div class="draft-name">${esc(draft.name)}</div>${stale}</div><div class="draft-preview">${esc(draft.preview || '空文稿')}</div></div>
      <button class="tree-menu" data-menu="draft" title="文稿操作" aria-label="文稿操作">•••</button>
    </div>`;
  }

  function syncCurrentDraftCompletion() {
    if (!state || !editor?.current_draft) return;
    const pendingCount = editor.lines.reduce((total, line) => total + line.filter(
      cell => cell.is_poly && (cell.selected || 'none') === 'none').length, 0);
    let changed = false;
    for (const collection of [state.drafts || [], state.recent_drafts || []]) {
      const draft = collection.find(item => item.filename === editor.current_draft);
      if (draft && Number(draft.unselected_polyphonic || 0) !== pendingCount) {
        draft.unselected_polyphonic = pendingCount;
        changed = true;
      }
    }
    if (changed) renderDraftTree();
  }

  function bindDraftTree() {
    const root = $('#draft-tree');
    root.onclick = event => {
      const menu = event.target.closest('[data-menu]');
      if (menu) {
        event.stopPropagation();
        showTreeMenu(menu);
        return;
      }
      const folder = event.target.closest('.folder-row');
      if (folder) {
        if (event.detail > 1) return;
        queue(async () => applyResult(await invoke('toggle_group', folder.dataset.id)));
        return;
      }
      const draft = event.target.closest('.draft-row');
      if (draft) queue(async () => applyResult(await invoke('load_draft', draft.dataset.id)));
    };
    root.ondblclick = event => {
      if (event.target.closest('.folder-row, [data-menu]')) return;
      const row = event.target.closest('.draft-row, .folder-row');
      if (row) renameTreeItem(row.dataset.kind, row.dataset.id);
    };
    $$('[draggable="true"]', root).forEach(row => {
      row.addEventListener('dragstart', event => {
        dragPayload = { kind: row.dataset.kind, id: row.dataset.id };
        row.classList.add('dragging');
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', row.dataset.id);
      });
      row.addEventListener('dragend', () => {
        row.classList.remove('dragging');
        $$('.drag-over').forEach(item => item.classList.remove('drag-over'));
        dragPayload = null;
      });
      row.addEventListener('dragover', event => {
        if (!dragPayload || dragPayload.id === row.dataset.id) return;
        event.preventDefault();
        row.classList.add('drag-over');
      });
      row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
      row.addEventListener('drop', event => handleTreeDrop(event, row));
    });
    const ungrouped = $('.ungrouped-drop', root);
    ungrouped.ondragover = event => { if (dragPayload?.kind === 'draft') event.preventDefault(); };
    ungrouped.ondrop = event => {
      event.preventDefault();
      if (dragPayload?.kind === 'draft') queue(async () => applyResult(await invoke('move_draft', dragPayload.id, null, null)));
    };
  }

  function handleTreeDrop(event, target) {
    event.preventDefault();
    target.classList.remove('drag-over');
    if (!dragPayload || dragPayload.id === target.dataset.id) return;
    if (dragPayload.kind === 'draft') {
      const groupId = target.dataset.kind === 'group' ? target.dataset.id : target.dataset.groupId || null;
      const before = target.dataset.kind === 'draft' ? target.dataset.id : null;
      queue(async () => applyResult(await invoke('move_draft', dragPayload.id, groupId, before)));
    } else if (dragPayload.kind === 'group') {
      const parent = target.dataset.kind === 'group' ? target.dataset.id : target.dataset.groupId || null;
      queue(async () => applyResult(await invoke('move_group', dragPayload.id, parent, null)));
    }
  }

  function showTreeMenu(button) {
    $('.floating-menu')?.remove();
    const row = button.closest('.draft-row, .folder-row');
    const menu = document.createElement('div');
    menu.className = 'floating-menu';
    menu.style.cssText = 'position:fixed;z-index:30;left:0;top:0;visibility:hidden;display:grid;min-width:110px;padding:4px;background:var(--surface);border:1px solid var(--border);border-radius:5px;box-shadow:var(--shadow)';
    const draft = row.dataset.kind === 'draft'
      ? state.drafts.find(item => item.filename === row.dataset.id) : null;
    const completionAction = draft
      ? `<button class="button" data-action="completion" style="border:0;text-align:left">${draft.manually_completed ? '取消完成标记' : '标记为已完成'}</button>` : '';
    menu.innerHTML = `${completionAction}${draft ? '<button class="button" data-action="history" style="border:0;text-align:left">历史版本</button>' : ''}<button class="button" data-action="rename" style="border:0;text-align:left">重命名</button><button class="button" data-action="delete" style="border:0;text-align:left;color:var(--danger)">删除</button>`;
    menu.onclick = async event => {
      const action = event.target.dataset.action;
      menu.remove();
      if (action === 'rename') renameTreeItem(row.dataset.kind, row.dataset.id);
      if (action === 'delete') deleteTreeItem(row.dataset.kind, row.dataset.id);
      if (action === 'history') openDraftHistory(row.dataset.id);
      if (action === 'completion' && draft) queue(async () => applyResult(
        await invoke('set_draft_completed', row.dataset.id, !draft.manually_completed)));
    };
    document.body.append(menu);
    const buttonRect = button.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const edge = 8;
    const gap = 3;
    const left = Math.min(
      window.innerWidth - menuRect.width - edge,
      Math.max(edge, buttonRect.right - menuRect.width));
    const roomBelow = window.innerHeight - buttonRect.bottom - edge;
    const top = roomBelow >= menuRect.height + gap
      ? buttonRect.bottom + gap
      : Math.max(edge, buttonRect.top - menuRect.height - gap);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.style.visibility = 'visible';
    setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
  }

  async function renameTreeItem(kind, id) {
    const existing = kind === 'draft'
      ? state.drafts.find(item => item.filename === id)?.name
      : findGroup(state.groups, id)?.name;
    const name = await promptBox(kind === 'draft' ? '重命名文稿' : '重命名文件夹', '名称', existing || '');
    if (!name) return;
    queue(async () => applyResult(await invoke(kind === 'draft' ? 'rename_draft' : 'rename_group', id, name)));
  }

  async function deleteTreeItem(kind, id) {
    const ok = await confirmBox(kind === 'draft' ? '删除文稿' : '删除文件夹', kind === 'draft'
      ? '文稿将被永久删除。' : '文件夹会被删除，其中的文稿会移到未分组。', '删除');
    if (!ok) return;
    queue(async () => applyResult(await invoke(kind === 'draft' ? 'delete_draft' : 'delete_group', id)));
  }

  function findGroup(groups, id) {
    for (const group of groups || []) {
      if (group.id === id) return group;
      const found = findGroup(group.children, id);
      if (found) return found;
    }
    return null;
  }

  async function openDraftHistory(filename) {
    const items = await invoke('get_draft_history', filename);
    const root = $('#history-list');
    root.dataset.filename = filename;
    root.innerHTML = items.length ? items.map(item => `
      <div class="history-row" data-snapshot="${esc(item.id)}">
        <div><strong>${esc(formatDate(item.modified) || item.id)}</strong><div class="history-preview">${esc(item.preview || '空文稿')}</div><div class="history-meta">${esc(item.name)}</div></div>
        <button class="button" data-restore-version>恢复</button>
      </div>`).join('') : '<div class="history-empty">尚无历史版本；手动保存或持续编辑后会自动生成。</div>';
    $$('[data-restore-version]', root).forEach(button => button.onclick = async () => {
      const row = button.closest('.history-row');
      const confirmed = await confirmBox('恢复历史版本', '当前版本会先保存到历史记录，然后恢复所选版本。', '恢复');
      if (!confirmed) return;
      applyResult(await invoke('restore_draft_version', filename, row.dataset.snapshot));
      $('#history-dialog').close();
      toast('历史版本已恢复');
    });
    $('#history-dialog').showModal();
  }

  function formatDate(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
  }

  function fillSchemes() {
    if (!state) return;
    const availableSchemes = state.schemes.filter(item => !item.archived);
    const hasSchemes = Boolean(availableSchemes.length);
    if (!hasSchemes) {
      state.selected_scheme = null;
      if (exportMode === 'suno') exportMode = 'phon';
    }
    const select = $('#export-scheme');
    select.innerHTML = availableSchemes.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
    select.value = state.selected_scheme;
    const selected = availableSchemes.find(item => item.id === state.selected_scheme)
      || availableSchemes[0];
    $('#selected-scheme-name').textContent = selected?.name || '没有可用方案';
    $('#edit-scheme-button').disabled = !selected;
    $('[data-value="suno"]', $('#export-mode')).disabled = !hasSchemes;
  }

  function renderSchemePicker() {
    const archived = schemePickerFilter === 'archived';
    const schemes = (state?.schemes || []).filter(item => Boolean(item.archived) === archived);
    if (!schemes.some(item => item.id === schemePickerId)) {
      schemePickerId = (!archived && schemes.some(item => item.id === state?.selected_scheme))
        ? state.selected_scheme : schemes[0]?.id || null;
    }
    $('#scheme-picker-list').innerHTML = schemes.length ? schemes.map(item => `
      <div class="scheme-order-row ${item.id === schemePickerId ? 'active' : ''} ${item.id === state.selected_scheme ? 'current' : ''}" data-scheme-row="${esc(item.id)}">
        <button type="button" class="scheme-picker-main" data-pick-scheme="${esc(item.id)}">
          <span class="scheme-picker-copy">
            <span class="scheme-picker-title"><strong>${esc(item.name)}</strong><time>${esc(formatSchemeCreated(item.created_at))}</time></span>
            <small>${esc(item.description || '暂无备注')}</small>
          </span>
        </button>
        <span class="scheme-order-actions">
          ${archived ? '' : '<button type="button" class="button" data-edit-picked-scheme>编辑</button>'}
          <button type="button" class="button" data-toggle-scheme-archive="${archived ? 'false' : 'true'}">${archived ? '恢复' : '归档'}</button>
        </span>
      </div>`).join('') : `<div class="history-empty">${archived ? '没有已归档方案' : '没有可用方案'}</div>`;
    $$('#scheme-picker-filter button').forEach(button => button.classList.toggle(
      'active', button.dataset.schemeFilter === schemePickerFilter));
    $('#use-picked-scheme').disabled = archived || !schemePickerId;
  }

  function formatSchemeCreated(value) {
    if (!value) return '日期未知';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('zh-CN');
  }

  function openSchemePicker() {
    schemePickerFilter = 'active';
    schemePickerId = state.selected_scheme;
    renderSchemePicker();
    $('#scheme-picker-dialog').showModal();
  }

  async function toggleSchemeArchived(schemeId, archived) {
    if (archived) {
      const confirmed = await confirmBox('归档方案', '归档后会从可用方案列表隐藏，之后仍可在“已归档”中恢复。', '归档');
      if (!confirmed) return;
    }
    const result = await invoke('set_scheme_archived', schemeId, archived);
    state.schemes = result.schemes;
    state.selected_scheme = result.selected_scheme;
    schemePickerId = null;
    fillSchemes();
    renderSchemePicker();
    await refreshExport();
    toast(`方案已${archived ? '归档' : '恢复'}`);
  }

  async function usePickedScheme() {
    if (!schemePickerId) return;
    await invoke('select_scheme', schemePickerId);
    state.selected_scheme = schemePickerId;
    fillSchemes();
    await refreshExport();
    $('#scheme-picker-dialog').close();
    toast('已切换方案');
  }

  async function importSchemeFromPicker() {
    const result = await importSchemeFile();
    if (!result?.ok) return;
    state.schemes = result.schemes;
    state.selected_scheme = result.selected_scheme;
    schemePickerFilter = 'active';
    schemePickerId = result.selected_scheme;
    fillSchemes();
    renderSchemePicker();
    await refreshExport();
    toast(`已导入方案 ${result.selected_scheme}`);
  }

  function importSchemeFile() {
    if (document.documentElement.dataset.platform !== 'android') {
      return invoke('import_scheme_json', null);
    }
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'application/json,.json';
      input.hidden = true;
      input.onchange = async () => {
        try {
          const file = input.files?.[0];
          if (!file) return resolve({ ok: false, cancelled: true });
          resolve(await invoke('import_scheme_content', await file.text(), file.name));
        } catch (error) {
          reject(error);
        } finally {
          input.remove();
        }
      };
      document.body.append(input);
      input.click();
    });
  }

  async function refreshExport() {
    const hasSchemes = Boolean(state?.schemes?.some(item => !item.archived));
    if (!hasSchemes && exportMode === 'suno') exportMode = 'phon';
    const sunoOnly = exportMode === 'suno' && hasSchemes;
    $('.export-controls').classList.toggle('suno-mode', sunoOnly);
    $('#remove-pharyngeal').disabled = !sunoOnly;
    $('#remove-tones').disabled = !sunoOnly;
    $('#remove-glottal-tone').disabled = !sunoOnly || $('#remove-tones').checked;
    $('#extra-h-voiceless-sonorant').disabled = !sunoOnly;
    $('#entry-before-glottal').disabled = !sunoOnly;
    $('#departing-before-glottal').disabled = !sunoOnly;
    $('#export-output').value = await invoke(
      'export_text', exportMode, $('#export-scheme').value,
      $('#punct-split').checked, $('#entry-before-glottal').checked,
      $('#departing-before-glottal').checked,
      $('#remove-pharyngeal').checked, $('#remove-tones').checked,
      $('#clean-line-breaks').checked, $('#remove-glottal-tone').checked,
      $('#extra-h-voiceless-sonorant').checked,
      $('#ignore-bracket-control-lines').checked);
    $$('#export-mode button').forEach(button => button.classList.toggle('active', button.dataset.value === exportMode));
  }

  const imageLineText = line => line.cells.map(cell => cell.char).join('');

  function selectedImageLines() {
    return imageExport.lines.filter(
      line => !imageExport.hidden.has(Number(line.source_line)));
  }

  function updateImageExportSummary() {
    const kept = selectedImageLines().length;
    $('#image-export-summary').textContent = `保留 ${kept} / ${imageExport.lines.length} 行`;
    $('#save-image-export').disabled = !kept || !imageExport.ready;
    $('#copy-image-export').disabled = !kept || !imageExport.ready;
  }

  function renderImageLineList() {
    const root = $('#image-line-list');
    root.innerHTML = imageExport.lines.map(line => {
      const sourceLine = Number(line.source_line);
      const content = line.cells.map(cell => {
        const classes = [
          'image-line-mini-cell', cell.is_poly ? 'poly' : '',
          cell.missing_phonetic ? 'missing' : '',
          cell.selected && cell.selected !== 'none' ? `selected-${cell.selected}` : '',
          cell.manual_hl ? 'manual-highlight' : '', cell.stale ? 'stale' : '',
        ].filter(Boolean).join(' ');
        return `<span class="${classes}"><span>${esc(cell.char)}</span><small>${esc(cell.phonetic || '')}</small></span>`;
      }).join('') || '<em class="image-line-blank">空行</em>';
      return `<label class="image-line-row">
        <input type="checkbox" data-image-line="${sourceLine}" ${imageExport.hidden.has(sourceLine) ? '' : 'checked'}>
        <span class="image-line-number">${String(sourceLine + 1).padStart(2, '0')}</span>
        <span class="image-line-text" title="${esc(imageLineText(line))}">${content}</span>
      </label>`;
    }).join('');
    updateImageExportSummary();
  }

  function wrapImageLine(cells, maxCells) {
    const rows = [];
    for (let index = 0; index < cells.length; index += maxCells) {
      rows.push(cells.slice(index, index + maxCells));
    }
    return rows;
  }

  function imageThemeColors() {
    const style = getComputedStyle(document.documentElement);
    const color = name => style.getPropertyValue(`--${name}`).trim();
    return {
      surface: color('surface'), text: color('text'), text2: color('text-2'),
      orange: color('orange'), orangeSoft: color('orange-soft'),
      green: color('green'), greenSoft: color('green-soft'),
      blue: color('blue'), blueSoft: color('blue-soft'),
      pink: color('pink'), pinkSoft: color('pink-soft'),
      unknown: color('unknown'), unknownSoft: color('unknown-soft'),
      border: color('border'), muted: color('muted'),
    };
  }

  function canvasRoundRect(context, x, y, width, height, radius) {
    const right = x + width;
    const bottom = y + height;
    context.beginPath();
    context.moveTo(x + radius, y);
    context.lineTo(right - radius, y);
    context.quadraticCurveTo(right, y, right, y + radius);
    context.lineTo(right, bottom - radius);
    context.quadraticCurveTo(right, bottom, right - radius, bottom);
    context.lineTo(x + radius, bottom);
    context.quadraticCurveTo(x, bottom, x, bottom - radius);
    context.lineTo(x, y + radius);
    context.quadraticCurveTo(x, y, x + radius, y);
    context.closePath();
  }

  function fitCanvasText(context, value, maxWidth) {
    const text = String(value || '');
    if (context.measureText(text).width <= maxWidth) return text;
    const chars = Array.from(text);
    while (chars.length && context.measureText(`${chars.join('')}…`).width > maxWidth) chars.pop();
    return chars.length ? `${chars.join('')}…` : '…';
  }

  function drawImageCell(context, cell, x, y, spec, colors) {
    let background = '';
    if (cell.missing_phonetic) background = colors.unknownSoft;
    if (cell.selected === 'manual') background = colors.greenSoft;
    if (cell.selected === 'global' || cell.selected === 'global_recent') background = colors.blueSoft;
    if (cell.stale) background = colors.orangeSoft;
    if (cell.manual_hl) background = colors.pinkSoft;
    if (background) {
      canvasRoundRect(context, x, y, spec.cellWidth, spec.cellHeight, spec.radius);
      context.fillStyle = background;
      context.fill();
    }
    if (cell.missing_phonetic) {
      canvasRoundRect(context, x + 1, y + 1, spec.cellWidth - 2, spec.cellHeight - 2, spec.radius);
      context.globalAlpha = .48;
      context.strokeStyle = colors.unknown;
      context.lineWidth = 2;
      context.stroke();
      context.globalAlpha = 1;
    }
    if (cell.selected === 'global_recent') {
      canvasRoundRect(context, x + 4, y + 4, spec.cellWidth - 8, spec.cellHeight - 8, spec.radius - 2);
      context.strokeStyle = colors.blue;
      context.lineWidth = 2;
      context.stroke();
    }
    if (cell.stale) {
      context.beginPath();
      context.arc(x + spec.cellWidth - 8, y + 8, 5, 0, Math.PI * 2);
      context.fillStyle = colors.orange;
      context.fill();
    }
    let charColor = cell.is_poly ? colors.orange : colors.text;
    if (cell.missing_phonetic) charColor = colors.unknown;
    if (cell.selected === 'manual') charColor = colors.green;
    if (cell.selected === 'global' || cell.selected === 'global_recent') charColor = colors.blue;
    if (cell.manual_hl && !cell.is_poly && !cell.missing_phonetic
        && (!cell.selected || cell.selected === 'none')) charColor = colors.pink;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.font = `${spec.charSize}px "Microsoft YaHei UI", "Microsoft YaHei", sans-serif`;
    context.fillStyle = charColor;
    context.fillText(cell.char === '\t' ? '　' : cell.char, x + spec.cellWidth / 2, y + spec.charCenterY);

    context.font = `${spec.phonSize}px Cambria, "Times New Roman", serif`;
    context.fillStyle = cell.missing_phonetic ? colors.unknown : colors.text2;
    context.fillText(
      fitCanvasText(context, cell.phonetic, spec.cellWidth - 6),
      x + spec.cellWidth / 2, y + spec.phonCenterY);
  }

  function drawImageNotice(canvas, message) {
    const colors = imageThemeColors();
    canvas.width = 1600;
    canvas.height = 500;
    const context = canvas.getContext('2d');
    context.fillStyle = colors.surface;
    context.fillRect(0, 0, 1600, 500);
    context.fillStyle = colors.muted;
    context.font = '36px "Microsoft YaHei", sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(message, 800, 250);
    sizeImagePreview(canvas);
  }

  function setImagePreviewStatus(message, error = false) {
    const note = $('#image-preview-status');
    if (note) note.textContent = message;
    note?.closest('.image-preview-note')?.classList.toggle('error', error);
  }

  function sizeImagePreview(canvas) {
    const stage = $('#image-canvas-stage');
    const dpr = window.devicePixelRatio || 1;
    const available = Math.min(800, Math.max(280, (stage?.clientWidth || 848) - 48));
    const downsample = Math.max(1, Math.ceil(canvas.width / (available * dpr)));
    canvas.style.width = `${canvas.width / (downsample * dpr)}px`;
    canvas.style.height = `${canvas.height / (downsample * dpr)}px`;
  }

  function paintImageDocument(canvas, logicalHeight, groups, spec, colors) {
    canvas.width = spec.width;
    canvas.height = logicalHeight;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法创建图片画布');
    context.fillStyle = colors.surface;
    context.fillRect(0, 0, spec.width, logicalHeight);
    let y = spec.paddingY;
    groups.forEach((group, groupIndex) => {
      group.rows.forEach(row => {
        let x = spec.paddingX;
        row.forEach(cell => {
          drawImageCell(context, cell, x, y, spec, colors);
          x += spec.cellWidth;
        });
        y += spec.cellHeight + spec.rowGap;
      });
      if (groupIndex < groups.length - 1) y += spec.lineGap;
    });
  }

  function renderImageCanvas() {
    const canvas = $('#image-export-canvas');
    const included = selectedImageLines();
    imageExport.ready = false;
    if (!included.length) {
      drawImageNotice(canvas, '请至少保留一行正文');
      setImagePreviewStatus('没有可渲染的正文行', true);
      updateImageExportSummary();
      return;
    }

    const baseSpec = {
      width: 1600, paddingX: 96, paddingY: 84,
      cellWidth: 76, cellHeight: 112, rowGap: 0, lineGap: 12,
      charSize: 38, phonSize: 22, charCenterY: 31, phonCenterY: 82,
      radius: 8,
    };
    const safeHeight = 8000;
    const minimumScale = 0.62;
    const scaledLayout = scale => {
      const scaled = value => Math.max(1, Math.round(value * scale));
      const spec = {
        width: baseSpec.width,
        paddingX: scaled(baseSpec.paddingX),
        paddingY: scaled(baseSpec.paddingY),
        cellWidth: scaled(baseSpec.cellWidth),
        cellHeight: scaled(baseSpec.cellHeight),
        rowGap: 0,
        lineGap: scaled(baseSpec.lineGap),
        charSize: scaled(baseSpec.charSize),
        phonSize: scaled(baseSpec.phonSize),
        charCenterY: scaled(baseSpec.charCenterY),
        phonCenterY: scaled(baseSpec.phonCenterY),
        radius: scaled(baseSpec.radius),
      };
      const maxWidth = spec.width - spec.paddingX * 2;
      const maxCells = Math.max(1, Math.floor(maxWidth / spec.cellWidth));
      const groups = included.map(line => ({
        sourceLine: line.source_line,
        rows: line.blank ? [[]] : wrapImageLine(line.cells, maxCells),
      }));
      const widestRow = groups.reduce(
        (widest, group) => Math.max(
          widest, ...group.rows.map(row => row.length)), 1);
      spec.width = Math.min(
        baseSpec.width,
        spec.paddingX * 2 + widestRow * spec.cellWidth);
      const contentHeight = groups.reduce(
        (sum, group) => sum + group.rows.length * (spec.cellHeight + spec.rowGap) + spec.lineGap, 0) - spec.lineGap;
      return {
        spec,
        groups,
        height: Math.max(420, spec.paddingY * 2 + contentHeight),
      };
    };

    let scale = 1;
    let layout = scaledLayout(scale);
    for (let attempt = 0; layout.height > safeHeight && attempt < 4; attempt += 1) {
      scale = Math.max(minimumScale, Math.min(scale - 0.02, scale * safeHeight / layout.height * 0.98));
      layout = scaledLayout(scale);
      if (scale === minimumScale) break;
    }
    if (layout.height > safeHeight) {
      drawImageNotice(canvas, '图片过长，请在左侧隐藏部分行');
      setImagePreviewStatus(`图片高度 ${layout.height}px，超过安全上限 ${safeHeight}px`, true);
      updateImageExportSummary();
      return;
    }

    try {
      paintImageDocument(canvas, layout.height, layout.groups, layout.spec, imageThemeColors());
      sizeImagePreview(canvas);
      imageExport.ready = true;
      $('#image-preview-meta').textContent = `字符 + 音标 · PNG · ${canvas.width} × ${canvas.height} px`;
      setImagePreviewStatus(
        scale < 1 ? `长文稿已自动缩放至 ${Math.round(scale * 100)}%` : '样式与正文编辑器一致');
    } catch (error) {
      console.error(error);
      drawImageNotice(canvas, '图片预览失败，请重试');
      const details = error?.message || String(error);
      setImagePreviewStatus(`渲染失败：${details}`, true);
      toast(`图片预览失败：${details}`, 'error');
    }
    updateImageExportSummary();
  }

  function canvasPngBlob(canvas) {
    return new Promise((resolve, reject) => {
      canvas.toBlob(blob => {
        if (blob) resolve(blob);
        else reject(new Error('无法生成 PNG 图片数据'));
      }, 'image/png');
    });
  }

  async function copyImageCanvas() {
    if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
      throw new Error('当前 WebView2 不支持图片剪贴板，请更新 WebView2 Runtime');
    }
    const blob = canvasPngBlob($('#image-export-canvas'));
    await navigator.clipboard.write([
      new ClipboardItem({ 'image/png': blob }),
    ]);
  }

  async function openImageExport() {
    const result = await invoke('get_image_export_data');
    if (!result?.lines?.some(line => line.cells?.length)) {
      toast('删除中括号内容后没有可导出的正文');
      return;
    }
    imageExport = {
      title: result.title || '正文',
      lines: result.lines,
      hidden: new Set(),
      ready: false,
    };
    $('#export-dialog').close();
    $('#image-export-dialog').showModal();
    renderImageLineList();
    renderImageCanvas();
    try {
      await document.fonts?.ready;
      renderImageCanvas();
    } catch (_) { /* the fallback font is already rendered */ }
  }

  async function openSchemeEditor(schemeId = null) {
    if (!state?.schemes?.length) {
      toast('请先导入方案', 'error');
      openSchemePicker();
      return;
    }
    schemeDraft = clone(await invoke('get_scheme', schemeId || $('#export-scheme').value || state.selected_scheme));
    schemeUndo = [];
    schemeRedo = [];
    schemeTab = 'options';
    renderSchemeEditor();
    setSchemeSaveStatus('');
    $('#scheme-dialog').showModal();
  }

  function setSchemeSaveStatus(message, kind = '') {
    const status = $('#scheme-save-status');
    status.textContent = message;
    status.className = `scheme-save-status${kind ? ` ${kind}` : ''}`;
  }

  function markSchemeDirty() {
    setSchemeSaveStatus('未保存', 'dirty');
  }

  function schemeSnapshot() {
    return clone(schemeDraft);
  }

  function commitSchemeHistory() {
    schemeUndo.push(schemeSnapshot());
    if (schemeUndo.length > 200) schemeUndo.shift();
    schemeRedo = [];
    updateSchemeHistoryButtons();
  }

  function schemeHistory(direction) {
    const from = direction === 'undo' ? schemeUndo : schemeRedo;
    const to = direction === 'undo' ? schemeRedo : schemeUndo;
    if (!from.length) return;
    to.push(schemeSnapshot());
    schemeDraft = from.pop();
    renderSchemeEditor();
    markSchemeDirty();
  }

  function updateSchemeHistoryButtons() {
    $('#scheme-undo').disabled = !schemeUndo.length;
    $('#scheme-redo').disabled = !schemeRedo.length;
  }

  function renderSchemeEditor() {
    $('#scheme-id').value = schemeDraft.id || '';
    $('#scheme-name').value = schemeDraft.name || '';
    $('#scheme-description').value = schemeDraft.description || '';
    $$('#scheme-tabs button').forEach(button => button.classList.toggle('active', button.dataset.tab === schemeTab));
    if (schemeTab === 'options') renderSchemeOptions();
    if (schemeTab === 'maps') renderSchemeMaps();
    if (schemeTab === 'rules') renderSchemeRules();
    if (schemeTab === 'tools') renderSchemeTools();
    updateSchemeHistoryButtons();
  }

  function renderSchemeOptions() {
    const labels = { improve_pharyngeal: '改善咽化组合', improve_syllable: '改善特殊音节' };
    const options = schemeDraft.options ||= {};
    const definitions = schemeDraft.option_definitions || {};
    const keys = [...new Set([...Object.keys(labels), ...Object.keys(options), ...Object.keys(definitions)])];
    $('#scheme-content').innerHTML = `<div class="option-list">${keys.map(key => {
      const definition = definitions[key] || {};
      const enabled = Boolean(options[key]);
      const offLabel = definition.off_label;
      const onLabel = definition.on_label;
      return `<div class="option-row"><div class="option-copy"><strong>${esc(definition.label || labels[key] || key)}</strong>${definition.description ? `<div class="muted">${esc(definition.description)}</div>` : ''}</div>
        <div class="option-control">${offLabel ? `<span class="option-state ${enabled ? '' : 'active'}">${esc(offLabel)}</span>` : ''}<label class="switch"><input type="checkbox" data-option="${esc(key)}" ${enabled ? 'checked' : ''} aria-label="${esc(definition.label || labels[key] || key)}"><span></span></label>${onLabel ? `<span class="option-state ${enabled ? 'active' : ''}">${esc(onLabel)}</span>` : ''}</div></div>`;
    }).join('')}</div>`;
    $$('[data-option]', $('#scheme-content')).forEach(input => input.onchange = () => {
      commitSchemeHistory();
      schemeDraft.options[input.dataset.option] = input.checked;
      renderSchemeOptions();
      markSchemeDirty();
    });
  }

  function mapOrder(section) {
    const map = schemeDraft.maps?.[section] || {};
    const order = [...(schemeDraft.parse_order?.[section] || [])].filter(key => key in map);
    Object.keys(map).forEach(key => { if (!order.includes(key)) order.push(key); });
    return order;
  }

  function renderSchemeMaps() {
    schemeDraft.maps ||= {};
    schemeDraft.labels ||= {};
    schemeDraft.parse_order ||= {};
    $('#scheme-content').innerHTML = MAP_SECTIONS.map(([section, title]) => {
      const rows = mapOrder(section);
      return `<section class="scheme-section" data-map-section="${section}">
        <div class="section-heading"><h3>${title}</h3><button class="button" data-add-map="${section}">新增项</button></div>
        <div class="data-table"><div class="table-row map header"><span>PBOC 项</span><span>输出</span><span>中文说明</span><span>操作</span></div>
        ${rows.map((source, index) => mapRowHtml(section, source, index)).join('')}</div></section>`;
    }).join('');
    bindSchemeMapEvents();
  }

  function mapRowHtml(section, source, index) {
    const target = schemeDraft.maps?.[section]?.[source] || '';
    const label = schemeDraft.labels?.[section]?.[source] || '';
    return `<div class="table-row map" data-section="${section}" data-index="${index}" data-source="${esc(source)}">
      <label><input data-field="source" value="${esc(source)}"></label><label><input data-field="target" value="${esc(target)}"></label>
      <label><input data-field="label" value="${esc(label)}"></label><span class="order-actions"><button type="button" class="icon-button small drag-handle" data-drag-map title="拖动排序；聚焦后可用方向键" aria-label="拖动排序"><i aria-hidden="true"></i></button><button class="icon-button small" data-delete-map title="删除" aria-label="删除">×</button></span></div>`;
  }

  function bindOrderDragging(selector, getItems, setItems, rerender) {
    $$(selector).forEach(handle => {
      const moveByKeyboard = delta => {
        const row = handle.closest('.table-row');
        const section = row.dataset.section;
        const from = Number(row.dataset.index);
        const items = [...getItems(section)];
        const to = Math.max(0, Math.min(items.length - 1, from + delta));
        if (to === from) return;
        commitSchemeHistory();
        const [item] = items.splice(from, 1);
        items.splice(to, 0, item);
        setItems(section, items);
        rerender();
        markSchemeDirty();
        const sectionAttribute = selector.includes('drag-map')
          ? 'data-map-section' : 'data-rule-section';
        requestAnimationFrame(() => document.querySelector(
          `[${sectionAttribute}="${CSS.escape(section)}"]`)
          ?.querySelectorAll(selector)[to]?.focus());
      };
      handle.onkeydown = event => {
        if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
        event.preventDefault();
        moveByKeyboard(event.key === 'ArrowUp' ? -1 : 1);
      };
      handle.onpointerdown = event => {
        if (event.button !== 0) return;
        event.preventDefault();
        handle.focus();
        const row = handle.closest('.table-row');
        const container = row.parentElement;
        const section = row.dataset.section;
        const from = Number(row.dataset.index);
        let to = from;
        const scrollHost = handle.closest('.scheme-content');
        const clearMarkers = () => {
          $$('.table-row', container).forEach(item => item.classList.remove(
            'order-drop-before', 'order-drop-after'));
        };
        const onMove = moveEvent => {
          const rows = $$('.table-row:not(.header)', container);
          const rawSlot = rows.findIndex(item => {
            const rect = item.getBoundingClientRect();
            return moveEvent.clientY < rect.top + rect.height / 2;
          });
          const slot = rawSlot < 0 ? rows.length : rawSlot;
          to = Math.max(0, Math.min(rows.length - 1,
            slot > from ? slot - 1 : slot));
          clearMarkers();
          if (slot >= rows.length) rows.at(-1)?.classList.add('order-drop-after');
          else rows[slot]?.classList.add('order-drop-before');
          if (scrollHost) {
            const rect = scrollHost.getBoundingClientRect();
            if (moveEvent.clientY < rect.top + 36) scrollHost.scrollTop -= 18;
            else if (moveEvent.clientY > rect.bottom - 36) scrollHost.scrollTop += 18;
          }
        };
        const finish = () => {
          document.removeEventListener('pointermove', onMove);
          document.removeEventListener('pointerup', finish);
          document.removeEventListener('pointercancel', cancel);
          clearMarkers();
          row.classList.remove('order-dragging');
          if (to === from) return;
          const items = [...getItems(section)];
          commitSchemeHistory();
          const [item] = items.splice(from, 1);
          items.splice(to, 0, item);
          setItems(section, items);
          rerender();
          markSchemeDirty();
        };
        const cancel = () => {
          to = from;
          finish();
        };
        row.classList.add('order-dragging');
        handle.setPointerCapture(event.pointerId);
        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', finish);
        document.addEventListener('pointercancel', cancel);
      };
    });
  }

  function bindSchemeMapEvents() {
    bindOrderDragging('[data-drag-map]', section => mapOrder(section),
      (section, items) => { schemeDraft.parse_order[section] = items; },
      renderSchemeMaps);
    $$('[data-add-map]').forEach(button => button.onclick = () => {
      commitSchemeHistory();
      const section = button.dataset.addMap;
      schemeDraft.maps[section] ||= {};
      schemeDraft.labels[section] ||= {};
      schemeDraft.parse_order[section] ||= [];
      let key = '新项';
      let suffix = 2;
      while (key in schemeDraft.maps[section]) key = `新项${suffix++}`;
      schemeDraft.maps[section][key] = '';
      schemeDraft.parse_order[section].push(key);
      renderSchemeMaps();
      markSchemeDirty();
    });
    $$('[data-delete-map]').forEach(button => button.onclick = () => {
      const row = button.closest('.table-row');
      commitSchemeHistory();
      const { section, source } = row.dataset;
      delete schemeDraft.maps[section][source];
      delete schemeDraft.labels?.[section]?.[source];
      schemeDraft.parse_order[section] = mapOrder(section).filter(key => key !== source);
      renderSchemeMaps();
      markSchemeDirty();
    });
    $$('.table-row.map input').forEach(input => input.onchange = () => {
      const row = input.closest('.table-row');
      const { section } = row.dataset;
      const oldSource = row.dataset.source;
      const field = input.dataset.field;
      commitSchemeHistory();
      if (field === 'target') schemeDraft.maps[section][oldSource] = input.value;
      if (field === 'label') {
        schemeDraft.labels[section] ||= {};
        if (input.value) schemeDraft.labels[section][oldSource] = input.value;
        else delete schemeDraft.labels[section][oldSource];
      }
      if (field === 'source') {
        const source = input.value.trim();
        if (!source || source === oldSource) return;
        const order = mapOrder(section);
        const target = schemeDraft.maps[section][oldSource];
        const label = schemeDraft.labels?.[section]?.[oldSource];
        delete schemeDraft.maps[section][oldSource];
        delete schemeDraft.labels?.[section]?.[oldSource];
        schemeDraft.maps[section][source] = target;
        if (label) schemeDraft.labels[section][source] = label;
        schemeDraft.parse_order[section] = order.map(key => key === oldSource ? source : key);
        row.dataset.source = source;
      }
      markSchemeDirty();
    });
  }

  function renderSchemeRules() {
    schemeDraft.rules ||= {};
    $('#scheme-content').innerHTML = RULE_SECTIONS.map(([section, title]) => {
      const rules = schemeDraft.rules[section] ||= [];
      return `<section class="scheme-section" data-rule-section="${section}">
        <div class="section-heading"><h3>${title}</h3><button class="button" data-add-rule="${section}">新增规则</button></div>
        <div class="data-table"><div class="table-row rule header"><span>查找方式</span><span>查找</span><span>选择</span><span>替换为</span><span>操作</span></div>
        ${rules.map((rule, index) => ruleRowHtml(section, rule, index)).join('')}</div></section>`;
    }).join('');
    bindSchemeRuleEvents();
  }

  function ruleRowHtml(section, rule, index) {
    const old = rule?.[0] ?? '';
    const replacement = rule?.[1] ?? '';
    const mapped = typeof old === 'object' && old.type === 'map_concat';
    const lookup = mapped ? lookupPreview(old) : String(old);
    return `<div class="table-row rule" data-section="${section}" data-index="${index}">
      <label><select data-rule-field="mode"><option value="text" ${mapped ? '' : 'selected'}>硬编码文本</option><option value="map" ${mapped ? 'selected' : ''}>映射项拼接</option></select></label>
      <label><input data-rule-field="old" value="${esc(lookup)}" ${mapped ? 'readonly' : ''}></label>
      <span><button class="button" data-edit-lookup ${mapped ? '' : 'disabled'}>选择</button></span>
      <label><input data-rule-field="new" value="${esc(replacement)}"></label>
      <span class="order-actions"><button type="button" class="icon-button small drag-handle" data-drag-rule title="拖动排序；聚焦后可用方向键" aria-label="拖动排序"><i aria-hidden="true"></i></button><button class="icon-button small" data-delete-rule title="删除" aria-label="删除">×</button></span></div>`;
  }

  function bindSchemeRuleEvents() {
    bindOrderDragging('[data-drag-rule]',
      section => schemeDraft.rules[section] || [],
      (section, items) => { schemeDraft.rules[section] = items; },
      renderSchemeRules);
    $$('[data-add-rule]').forEach(button => button.onclick = () => {
      commitSchemeHistory();
      (schemeDraft.rules[button.dataset.addRule] ||= []).push(['', '']);
      renderSchemeRules();
      markSchemeDirty();
    });
    $$('[data-delete-rule]').forEach(button => button.onclick = () => {
      const row = button.closest('.table-row');
      commitSchemeHistory();
      schemeDraft.rules[row.dataset.section].splice(Number(row.dataset.index), 1);
      renderSchemeRules();
      markSchemeDirty();
    });
    $$('[data-rule-field]').forEach(input => input.onchange = () => {
      const row = input.closest('.table-row');
      const rule = schemeDraft.rules[row.dataset.section][Number(row.dataset.index)];
      commitSchemeHistory();
      if (input.dataset.ruleField === 'mode') {
        rule[0] = input.value === 'map' ? { type: 'map_concat', field: 'target', parts: [] } : '';
        renderSchemeRules();
      } else if (input.dataset.ruleField === 'old') rule[0] = input.value;
      else rule[1] = input.value;
      markSchemeDirty();
    });
    $$('[data-edit-lookup]').forEach(button => button.onclick = () => {
      const row = button.closest('.table-row');
      lookupTarget = { section: row.dataset.section, index: Number(row.dataset.index) };
      openLookupEditor();
    });
  }

  function renderSchemeTools() {
    const schemeOptions = (state.schemes || []).map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
    $('#scheme-content').innerHTML = `<div class="scheme-tools">
      <section class="tool-pane">
        <h3>结构校验</h3>
        <div id="validation-summary" class="validation-summary">正在检查...</div>
        <div id="validation-issues" class="issue-list"></div>
        <div class="diff-controls"><select id="diff-scheme" class="select">${schemeOptions}</select><button id="run-diff" class="button">比较方案</button></div>
        <div id="diff-list" class="diff-list"></div>
      </section>
      <section class="tool-pane">
        <h3>即时预览</h3>
        <textarea id="scheme-preview-input" class="preview-area" placeholder="输入 PBOC 音节，每个音节以空格分隔">kˤanʔ mra s-lə</textarea>
        <div class="maintenance-actions" style="margin-top:8px"><button id="run-preview" class="button primary">运行预览</button></div>
        <output id="scheme-preview-output" class="preview-output"></output>
      </section>
    </div>`;
    $('#diff-scheme').value = state.selected_scheme || state.schemes?.[0]?.id || '';
    $('#run-preview').onclick = runSchemePreview;
    $('#run-diff').onclick = runSchemeDiff;
    refreshSchemeValidation();
  }

  async function refreshSchemeValidation() {
    commitSchemeMeta();
    const issues = await invoke('validate_scheme', schemeDraft);
    if (schemeTab !== 'tools') return issues;
    const errors = issues.filter(item => item.severity === 'error').length;
    const warnings = issues.length - errors;
    $('#validation-summary').innerHTML = `<span>${errors} 个错误</span><span>${warnings} 个提醒</span>`;
    $('#validation-issues').innerHTML = issues.length ? issues.map(item => `
      <div class="issue ${item.severity}"><code>${esc(item.path || 'scheme')}</code>${esc(item.message)}</div>`).join('') : '<div class="muted">没有发现结构问题。</div>';
    return issues;
  }

  async function runSchemePreview() {
    commitSchemeMeta();
    const result = await invoke('preview_scheme', schemeDraft, $('#scheme-preview-input').value);
    $('#scheme-preview-output').textContent = result.ok ? (result.output || '（空输出）') : (result.message || '请先修复方案错误');
    await refreshSchemeValidation();
  }

  async function runSchemeDiff() {
    commitSchemeMeta();
    const result = await invoke('compare_scheme', schemeDraft, $('#diff-scheme').value);
    const items = result.differences || [];
    $('#diff-list').innerHTML = items.length ? `<div class="diff-row header"><span>类别</span><span>项目</span><span>当前</span><span>对比方案</span></div>${items.map(item => `
      <div class="diff-row"><span>${esc(item.category)}</span><span>${esc(item.key)}</span><span>${esc(displayValue(item.before))}</span><span>${esc(displayValue(item.after))}</span></div>`).join('')}` : '<div class="history-empty">两个方案没有差异。</div>';
  }

  function displayValue(value) {
    if (value === undefined || value === null) return '（无）';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function lookupPreview(expression) {
    const field = expression.field || 'target';
    return (expression.parts || []).map(([section, key]) => {
      if (field === 'source') return key;
      if (field === 'label') return schemeDraft.labels?.[section]?.[key] || '';
      return schemeDraft.maps?.[section]?.[key] || '';
    }).join('');
  }

  function openLookupEditor() {
    const rule = schemeDraft.rules[lookupTarget.section][lookupTarget.index];
    const expression = clone(rule[0]);
    $('#lookup-field').value = expression.field || 'target';
    $('#lookup-parts').innerHTML = '';
    (expression.parts?.length ? expression.parts : [['onset', mapOrder('onset')[0] || '']]).forEach(part => addLookupPart(part));
    refreshLookupPreview();
    $('#lookup-dialog').showModal();
  }

  function addLookupPart(part = ['onset', '']) {
    const row = document.createElement('div');
    row.className = 'lookup-part';
    row.innerHTML = `<select class="select lookup-section">${MAP_SECTIONS.map(([key, title]) => `<option value="${key}" ${key === part[0] ? 'selected' : ''}>${title}</option>`).join('')}</select><select class="select lookup-key"></select><button type="button" class="icon-button small" aria-label="删除">×</button>`;
    $('#lookup-parts').append(row);
    fillLookupKeys(row, part[1]);
    $('.lookup-section', row).onchange = () => { fillLookupKeys(row); refreshLookupPreview(); };
    $('.lookup-key', row).onchange = refreshLookupPreview;
    $('.icon-button', row).onclick = () => { row.remove(); refreshLookupPreview(); };
  }

  function fillLookupKeys(row, selected = '') {
    const section = $('.lookup-section', row).value;
    const keys = mapOrder(section);
    const select = $('.lookup-key', row);
    select.innerHTML = keys.map(key => `<option value="${esc(key)}">${esc(key)}</option>`).join('');
    if (keys.includes(selected)) select.value = selected;
  }

  function collectLookupExpression() {
    return {
      type: 'map_concat',
      field: $('#lookup-field').value,
      parts: $$('.lookup-part').map(row => [$('.lookup-section', row).value, $('.lookup-key', row).value]).filter(part => part[1])
    };
  }

  function refreshLookupPreview() {
    $('#lookup-preview').textContent = lookupPreview(collectLookupExpression()) || '（空）';
  }

  function promptBox(title, label, initial = '') {
    return new Promise(resolve => {
      const dialog = $('#prompt-dialog');
      const input = $('#prompt-input');
      let composing = false;
      let submitAfterComposition = false;
      $('#prompt-title').textContent = title;
      $('#prompt-label').textContent = label;
      input.value = initial;
      input.oncompositionstart = () => { composing = true; };
      input.oncompositionend = () => {
        composing = false;
        if (!submitAfterComposition) return;
        submitAfterComposition = false;
        setTimeout(() => {
          if (dialog.open && input.value.trim()) dialog.close('default');
        }, 0);
      };
      input.onkeydown = event => {
        if (event.key !== 'Enter') return;
        if (event.isComposing || composing || event.keyCode === 229) {
          submitAfterComposition = true;
          return;
        }
        event.preventDefault();
        if (input.value.trim()) dialog.close('default');
      };
      dialog.onclose = () => {
        input.oncompositionstart = null;
        input.oncompositionend = null;
        input.onkeydown = null;
        resolve(dialog.returnValue === 'default' ? input.value.trim() : null);
      };
      dialog.showModal();
      setTimeout(() => { input.focus(); input.select(); }, 0);
    });
  }

  function confirmBox(title, message, confirmLabel = '确定') {
    return new Promise(resolve => {
      const dialog = $('#confirm-dialog');
      $('#confirm-title').textContent = title;
      $('#confirm-message').textContent = message;
      $('#confirm-ok').textContent = confirmLabel;
      dialog.onclose = () => resolve(dialog.returnValue === 'default');
      dialog.showModal();
    });
  }

  async function openBatchEditor() {
    const items = await invoke('get_polyphonic_summary');
    const root = $('#batch-list');
    root.innerHTML = items.length ? `
      <label class="check-control" style="padding:10px 0 12px;border-bottom:1px solid var(--divider)"><input id="batch-overwrite" type="checkbox"><span>覆盖已经手动选择的不同读音</span></label>
      ${items.map((item, index) => {
        const readings = Object.entries(item.readings).map(([phon, count]) => `${phon} × ${count}`).join('，');
        const options = (item.options || []).map(option => optionPhonetic(option)).filter(Boolean);
        return `<div class="batch-row" data-char="${esc(item.char)}"><span class="batch-char">${esc(item.char)}</span><div><strong>${item.count} 处</strong><div class="batch-count">${esc(readings)}</div></div><select class="select batch-reading">${options.map(phon => `<option value="${esc(phon)}">${esc(phon)}</option>`).join('')}</select><button class="button" data-batch-apply>应用</button></div>`;
      }).join('')}` : '<div class="history-empty">当前正文没有多音字。</div>';
    $$('[data-batch-apply]', root).forEach(button => button.onclick = async () => {
      const row = button.closest('.batch-row');
      const phonetic = $('.batch-reading', row).value;
      const overwrite = Boolean($('#batch-overwrite')?.checked);
      applyResult(await invoke('batch_apply_reading', row.dataset.char, phonetic, overwrite));
      toast(`已批量应用「${row.dataset.char}」`);
      await openBatchEditor();
    });
    if (!$('#batch-dialog').open) $('#batch-dialog').showModal();
  }

  async function openMaintenance(tab = 'about') {
    if (tab !== 'data-changes') dataChangeFocus = null;
    maintenanceTab = tab;
    $('#about-version').textContent = `v${state.version || ''}`;
    renderMaintenance();
    $('#maintenance-dialog').showModal();
  }

  function openDataChangeEvent(event) {
    dataChangeFocus = event;
    openMaintenance('data-changes');
  }

  async function renderMaintenance() {
    $$('#maintenance-tabs button').forEach(button => button.classList.toggle('active', button.dataset.tab === maintenanceTab));
    const root = $('#maintenance-content');
    root.className = 'maintenance-content';
    if (maintenanceTab === 'about') {
      root.innerHTML = `<div class="about-hero"><div class="about-mark">漢</div><div><h3>汉字转 PBOC 音标</h3><p>版本 ${esc(state.version || '')}</p></div><button id="check-update" class="button">检查更新</button></div>
        <div id="update-result"></div>
        <section class="maintenance-section compact-section"><label class="check-control"><input id="auto-check-updates" type="checkbox" ${state.ui_preferences?.auto_check_updates !== false ? 'checked' : ''}><span>启动后自动检查更新</span></label></section>
        <section class="maintenance-section"><h3>制作信息</h3><dl class="about-credits">
          <dt>作者</dt><dd><a href="https://space.bilibili.com/129368153" data-external-url>Bilibili-@-凛武-</a></dd>
          <dt>拟音</dt><dd>知乎-@Nulll</dd>
          <dt>源数据</dt><dd><a href="https://zhuanlan.zhihu.com/p/12987993957" data-external-url>知乎专栏</a> · <a href="https://github.com/qwert-ly/xtext" data-external-url>qwert-ly/xtext</a></dd>
          <dt>测试</dt><dd><a href="https://space.bilibili.com/87432837" data-external-url>Bilibili-@Freegrep</a></dd>
        </dl></section>
        <section class="maintenance-section"><h3>调试</h3><label class="check-control"><input id="debug-mode-toggle" type="checkbox" ${state.ui_preferences?.debug_mode ? 'checked' : ''}><span>显示实验性导出选项</span></label><p class="muted">开启后显示“删除所有声调”以及喉塞音前声调调整选项。</p></section>
        <section class="maintenance-section"><h3>版本说明</h3>${(state.changelog || []).map(entry => `<div class="changelog-entry"><h4>v${esc(entry.version)} · ${esc(entry.title)}</h4><div class="muted">${esc(entry.date)}</div><ul>${entry.items.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>`).join('')}</section>`;
      $('#check-update').onclick = () => checkUpdates(false);
      $('#auto-check-updates').onchange = async event => {
        state.ui_preferences ||= {};
        state.ui_preferences.auto_check_updates = event.target.checked;
        await invoke('set_ui_preference', 'auto_check_updates', event.target.checked);
      };
      if (availableUpdate) renderUpdateResult(availableUpdate);
      $('#debug-mode-toggle').onchange = async event => {
        const enabled = event.target.checked;
        applyDebugMode(enabled);
        await invoke('set_ui_preference', 'debug_mode', enabled);
        toast(`调试模式已${enabled ? '开启' : '关闭'}`);
      };
      $$('[data-external-url]', root).forEach(link => link.onclick = event => {
        event.preventDefault();
        invoke('open_source_url', link.href);
      });
      return;
    }
    if (maintenanceTab === 'guide') {
      root.innerHTML = `<section class="maintenance-section"><h3>基本操作</h3><ol class="guide-list">
          <li>直接在编辑区输入或粘贴汉字，正文会实时显示注音。</li>
          <li>点击正文中的字，在右侧查看读音和释义；多音字可选择当前读音。</li>
          <li>同一个字出现多次时，可在读音右侧点击“全局”，逐处处理已有的手动选择。</li>
          <li>拖动、Shift+点击或 Shift+方向键可以选择文本；选区可复制原文或音标。</li>
          <li>导出支持 PBOC、Suno、原文及组合内容，也可转换标点或清除无效换行；Suno 模式还可删除咽化、在清响音前额外添加 h。实验性声调选项可在“关于”的调试模式中开启。</li>
          <li>方括号 [] 内的内容保持原样，不参与转写。</li>
        </ol></section>
        <section class="maintenance-section"><h3>正文状态</h3><div class="state-legend">
          <span><i class="legend-swatch unselected"></i>橙色：多音字尚未手动选择</span>
          <span><i class="legend-swatch manual"></i>绿色：已手动选择读音</span>
          <span><i class="legend-swatch global"></i>蓝色：由全局应用选择</span>
          <span><i class="legend-swatch recent"></i>蓝色边框：最近一次全局应用</span>
          <span><i class="legend-swatch stale"></i>琥珀色：词库更新后读音有变化</span>
          <span><i class="legend-swatch highlight"></i>粉色：手动高亮</span>
        </div></section>
        <section class="maintenance-section"><h3>查找与高亮</h3><p class="muted">Ctrl+F 打开查找；Enter 跳到下一个，Shift+Enter 返回上一个，Esc 关闭。进入高亮模式后点击正文中的字可添加或取消高亮，再次点击高亮按钮或按 Esc 退出。</p></section>`;
      return;
    }
    if (maintenanceTab === 'backup') {
      root.innerHTML = `<section class="maintenance-section"><h3>完整备份</h3><div class="maintenance-actions"><button id="export-backup" class="button primary">导出备份</button><button id="open-backups" class="button">打开备份目录</button></div></section>
        <section class="maintenance-section"><h3>恢复与迁移</h3><div class="maintenance-actions"><button id="import-backup" class="button">从备份恢复</button><button id="import-old-library" class="button">导入旧资料库</button></div></section><div id="backup-result" class="update-result hidden"></div>`;
      $('#export-backup').onclick = async () => {
        const result = await invoke('export_backup', null);
        if (result.ok) {
          $('#backup-result').classList.remove('hidden');
          $('#backup-result').textContent = `已备份 ${result.files} 个文件：${result.path}`;
        }
      };
      $('#open-backups').onclick = () => invoke('open_location', 'backups');
      $('#import-backup').onclick = async () => {
        const confirmed = await confirmBox('恢复完整备份', '恢复前会自动备份当前数据，然后用所选备份替换草稿、方案和偏好。', '选择备份');
        if (!confirmed) return;
        const result = await invoke('import_backup', null, true);
        if (result.ok) {
          applyResult(result.state);
          $('#maintenance-dialog').close();
          toast(`已恢复 ${result.restored} 个文件`);
        }
      };
      $('#import-old-library').onclick = async () => {
        const result = await invoke('import_old_library', null);
        if (!result.ok) return;
        applyResult(result.state);
        renderMaintenance();
        const holder = $('#backup-result');
        holder.classList.remove('hidden');
        holder.textContent = `已导入 ${result.imported} 篇，跳过 ${result.skipped} 篇，自动改名 ${result.renamed} 篇${result.errors.length ? `；${result.errors.length} 个文件未导入` : ''}。`;
      };
      return;
    }
    if (maintenanceTab === 'data-changes') {
      root.classList.add('data-changes-content');
      root.innerHTML = '<div class="history-empty">正在建立变更索引...</div>';
      await openDataChangeViewer();
      return;
    }
    if (maintenanceTab === 'diagnostics') {
      root.innerHTML = '<div class="history-empty">正在读取诊断信息...</div>';
      const info = await invoke('get_diagnostics');
      if (maintenanceTab !== 'diagnostics') return;
      const rows = [
        ['应用版本', info.app_version], ['草稿格式', info.draft_schema_version],
        ['方案格式', info.scheme_schema_version], ['Python', info.python],
        ['WebView', info.webview], ['运行模式', info.runtime_mode || (info.frozen ? '单文件 EXE' : '源码')],
        ['草稿数量', info.draft_count], ['方案数量', info.scheme_count],
        ['程序目录', info.app_dir], ['草稿目录', info.draft_dir], ['方案目录', info.scheme_dir]
      ];
      root.innerHTML = `<dl class="diagnostic-grid">${rows.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join('')}</dl>
        <section class="maintenance-section"><h3>位置</h3><div class="maintenance-actions"><button class="button" data-open-location="app">程序目录</button><button class="button" data-open-location="drafts">草稿目录</button><button class="button" data-open-location="schemes">方案目录</button><button class="button" data-open-location="log">更新日志</button></div></section>`;
      $$('[data-open-location]', root).forEach(button => button.onclick = () => invoke('open_location', button.dataset.openLocation));
      return;
    }
    root.innerHTML = `<div class="shortcut-grid"><span>撤回</span><kbd>Ctrl Z</kbd><span>重做</span><kbd>Ctrl Y</kbd><span>复制</span><kbd>Ctrl C</kbd><span>剪切</span><kbd>Ctrl X</kbd><span>粘贴</span><kbd>Ctrl V</kbd><span>查找</span><kbd>Ctrl F</kbd><span>保存</span><kbd>Ctrl S</kbd><span>全选</span><kbd>Ctrl A</kbd><span>正文字号</span><kbd>Ctrl 滚轮</kbd></div>`;
  }

  function renderDataChangeBatches() {
    const trigger = $('#data-change-batch-trigger');
    const label = $('#data-change-batch-label');
    const menu = $('#data-change-batch-menu');
    if (!trigger || !label || !menu) return;
    const selected = dataChangeView.batches.find(
      batch => batch.id === dataChangeView.selected) || dataChangeView.batches[0];
    const batchText = batch => {
      const name = batch.filename.replace('.json.gz', '');
      return `${name} · ${batch.timestamp} · ${batch.count} 项`;
    };
    label.textContent = selected ? batchText(selected) : '选择批次';
    menu.innerHTML = dataChangeView.batches.map(batch => `
      <button type="button" role="option" aria-selected="${batch.id === dataChangeView.selected}" class="data-change-batch-option ${batch.id === dataChangeView.selected ? 'active' : ''}" data-change-batch="${esc(batch.id)}">
        <strong>${esc(batch.filename.replace('.json.gz', ''))}</strong><span>${esc(batch.timestamp)}</span><b>${batch.count} 项</b>
      </button>`).join('');
    const closeMenu = () => {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    };
    trigger.onclick = () => {
      const opening = menu.hidden;
      menu.hidden = !opening;
      trigger.setAttribute('aria-expanded', String(opening));
      if (opening) requestAnimationFrame(() => menu.querySelector('.active')?.focus());
    };
    menu.onclick = async event => {
      const option = event.target.closest('[data-change-batch]');
      if (!option || option.dataset.changeBatch === dataChangeView.selected) {
        closeMenu();
        trigger.focus();
        return;
      }
      dataChangeFocus = null;
      dataChangeView.selected = option.dataset.changeBatch;
      dataChangeView.query = '';
      $('#data-change-search').value = '';
      closeMenu();
      renderDataChangeBatches();
      await loadDataChangeEntries(true);
    };
    menu.onkeydown = event => {
      const options = $$('[data-change-batch]', menu);
      const index = options.indexOf(document.activeElement);
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        options[(index + direction + options.length) % options.length]?.focus();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closeMenu();
        trigger.focus();
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        options[event.key === 'Home' ? 0 : options.length - 1]?.focus();
      }
    };
    const more = $('#more-data-change-batches');
    if (more) more.hidden = dataChangeView.batches.length >= dataChangeView.batchTotal;
  }

  function flattenDataChangeValue(value, output = []) {
    if (Array.isArray(value)) {
      value.forEach(item => flattenDataChangeValue(item, output));
    } else if (value && typeof value === 'object') {
      Object.entries(value).forEach(([key, item]) => {
        const nested = [];
        flattenDataChangeValue(item, nested);
        output.push(`${key}: ${nested.join('；')}`);
      });
    } else if (value !== null && value !== undefined && String(value).trim()) {
      output.push(String(value));
    }
    return output;
  }

  function renderDataChangeTextDiff(value, counterpart, side) {
    let prefix = 0;
    while (prefix < value.length && prefix < counterpart.length
        && value[prefix] === counterpart[prefix]) prefix++;
    let suffix = 0;
    while (suffix < value.length - prefix && suffix < counterpart.length - prefix
        && value[value.length - 1 - suffix] === counterpart[counterpart.length - 1 - suffix]) suffix++;
    const end = value.length - suffix;
    const marked = `${esc(value.slice(0, prefix))}<mark>${esc(value.slice(prefix, end) || '无')}</mark>${esc(value.slice(end))}`;
    if (value.length <= 180) return `<span class="data-change-${side}">${marked}</span>`;
    const contextStart = Math.max(0, prefix - 42);
    const contextEnd = Math.min(value.length, end + 42);
    const context = `${contextStart ? '…' : ''}${esc(value.slice(contextStart, prefix))}<mark>${esc(value.slice(prefix, end) || '无')}</mark>${esc(value.slice(end, contextEnd))}${contextEnd < value.length ? '…' : ''}`;
    return `<details class="data-change-${side}"><summary>${context}</summary><p>${marked}</p></details>`;
  }

  function renderDataChangeValue(value, counterpart, side) {
    if (value === null || value === undefined || value === '') return '<em>无</em>';
    const items = flattenDataChangeValue(value);
    if (!items.length) return '<em>空</em>';
    const otherItems = flattenDataChangeValue(counterpart);
    if (items.length === 1 && otherItems.length === 1 && items[0] !== otherItems[0]) {
      return renderDataChangeTextDiff(items[0], otherItems[0], side);
    }
    if (items.length === 1 && items[0].length <= 130) return `<span>${esc(items[0])}</span>`;
    if (items.length <= 3 && items.every(item => item.length <= 130)) {
      return `<ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`;
    }
    const preview = items[0].length > 54 ? `${items[0].slice(0, 54)}…` : items[0];
    return `<details><summary>${esc(preview)}${items.length > 1 ? ` · 共 ${items.length} 条` : ''}</summary><ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul></details>`;
  }

  function renderDataChangeFields(entry) {
    if (!entry.changes?.length) return entry.details.length
      ? `<pre>${esc(entry.details.join('\n'))}</pre>` : '';
    return `<div class="data-change-fields">${entry.changes.map(change => `
      <section class="data-change-field ${change.status === '新增' ? 'added' : change.status === '删除' ? 'removed' : 'modified'}">
        <header><strong>${esc(change.field)}</strong><span>${esc(change.status)}</span></header>
        <div class="data-change-values">
          <div><b>旧</b>${renderDataChangeValue(change.old, change.new, 'old')}</div>
          <div><b>新</b>${renderDataChangeValue(change.new, change.old, 'new')}</div>
        </div>
      </section>`).join('')}</div>`;
  }

  function renderDataChangeEntries() {
    const batch = dataChangeView.batches.find(item => item.id === dataChangeView.selected);
    const meta = $('#data-change-meta');
    const list = $('#data-change-entries');
    if (!batch || !meta || !list) return;
    meta.textContent = dataChangeView.query ? `找到 ${dataChangeView.entryTotal} 项` : '';
    list.innerHTML = dataChangeView.entries.length ? dataChangeView.entries.map(entry => `
      <article class="data-change-entry ${entry.kind === '新增' ? 'added' : entry.kind === '删除' ? 'removed' : 'modified'} ${dataChangeFocus?.id && dataChangeFocus.id === entry.event_id ? 'focused' : ''}" data-change-event="${esc(entry.event_id || '')}">
        <span class="data-change-kind">${esc(entry.kind)}</span>
        <strong>${esc(entry.display_label || entry.label)}</strong>
        <p>${entry.changes?.length ? `${entry.changes.length} 个字段变化${entry.unchanged_count ? ` · ${entry.unchanged_count} 个未变` : ''}` : esc(entry.summary || '')}</p>
        ${renderDataChangeFields(entry)}
      </article>`).join('') : `<div class="history-empty">${dataChangeView.query ? '没有匹配的变更。' : '这个批次没有可显示的明细。'}</div>`;
    if (dataChangeView.entries.length < dataChangeView.entryTotal) {
      list.insertAdjacentHTML('beforeend', '<button id="more-data-change-entries" class="button data-change-more">载入更多</button>');
      $('#more-data-change-entries').onclick = () => loadDataChangeEntries(false);
    }
    const focused = list.querySelector('.data-change-entry.focused');
    if (focused) requestAnimationFrame(() => focused.scrollIntoView({ block: 'center' }));
  }

  async function loadDataChangeEntries(reset) {
    if (!dataChangeView.selected || (dataChangeView.loading && !reset)) return;
    dataChangeView.loading = true;
    const requestId = reset
      ? ++dataChangeView.requestId : dataChangeView.requestId;
    const offset = reset ? 0 : dataChangeView.entries.length;
    if (reset) {
      dataChangeView.entries = [];
      $('#more-data-change-entries')?.remove();
      $('#data-change-entries').innerHTML = '<div class="history-empty">正在读取变更...</div>';
    }
    try {
      const selected = dataChangeView.selected;
      const query = dataChangeView.query;
      const result = await invoke('get_data_change_entries', selected, offset, 80, query);
      if (maintenanceTab !== 'data-changes' || selected !== dataChangeView.selected
          || query !== dataChangeView.query || requestId !== dataChangeView.requestId) return;
      dataChangeView.entries = reset ? result.items : [...dataChangeView.entries, ...result.items];
      dataChangeView.entryTotal = result.total;
      renderDataChangeEntries();
    } finally {
      if (requestId === dataChangeView.requestId) dataChangeView.loading = false;
    }
  }

  async function loadMoreDataChangeBatches() {
    const result = await invoke('get_data_change_batches', dataChangeView.batches.length, 40);
    dataChangeView.batches.push(...result.items);
    dataChangeView.batchTotal = result.total;
    renderDataChangeBatches();
  }

  async function openDataChangeViewer() {
    const result = await invoke('get_data_change_batches', 0, 40);
    if (maintenanceTab !== 'data-changes') return;
    const root = $('#maintenance-content');
    if (!result.exists || !result.items.length) {
      root.innerHTML = '<div class="history-empty">还没有数据变更记录。数据文件更新后会在这里显示。</div>';
      return;
    }
    const batches = [...result.items];
    if (dataChangeFocus && !batches.some(item => item.id === dataChangeFocus.batch_id)) {
      batches.unshift({
        id: dataChangeFocus.batch_id,
        timestamp: dataChangeFocus.timestamp,
        filename: dataChangeFocus.filename,
        count: dataChangeFocus.batch_count || 0,
      });
    }
    dataChangeView = {
      batches, batchTotal: Math.max(result.total, batches.length),
      selected: dataChangeFocus?.batch_id || batches[0].id,
      entries: [], entryTotal: 0,
      query: dataChangeFocus?.char || '', loading: false, requestId: 0,
    };
    root.innerHTML = `<div class="data-change-controls">
        <div class="data-change-batch-picker"><span>批次</span><div class="data-change-batch-popover">
          <button id="data-change-batch-trigger" type="button" class="data-change-batch-trigger" aria-haspopup="listbox" aria-expanded="false"><span id="data-change-batch-label"></span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"></path></svg></button>
          <div id="data-change-batch-menu" class="data-change-batch-menu" role="listbox" aria-label="更新批次" hidden></div>
        </div></div>
        <button id="more-data-change-batches" class="button data-change-batch-more" title="载入更早的批次">更早</button>
        <span id="data-change-meta" class="data-change-meta"></span>
        <label class="data-change-search"><span>搜索</span><input id="data-change-search" class="text-input" placeholder="汉字、音标或序号"></label>
      </div>
      <div id="data-change-entries" class="data-change-entries"></div>`;
    renderDataChangeBatches();
    $('#more-data-change-batches').onclick = loadMoreDataChangeBatches;
    const searchInput = $('#data-change-search');
    searchInput.value = dataChangeView.query;
    searchInput.oninput = () => {
      dataChangeFocus = null;
      clearTimeout(dataChangeSearchTimer);
      dataChangeSearchTimer = setTimeout(() => {
        dataChangeView.query = searchInput.value.trim();
        loadDataChangeEntries(true);
      }, 280);
    };
    await loadDataChangeEntries(true);
  }

  function renderUpdateResult(result) {
    const holder = $('#update-result');
    if (!holder) return;
    holder.className = 'update-result';
    if (!result.ok) {
      holder.innerHTML = `${esc(result.message)} <button id="open-releases" class="button">打开发布页</button>`;
    } else if (result.available) {
      const action = result.can_install
        ? `<button id="install-update" class="button primary">${downloadedUpdate?.version === result.latest ? '继续安装' : '下载并更新'}</button>`
        : '<button id="open-releases" class="button">打开下载页</button>';
      holder.innerHTML = `<strong>发现 v${esc(result.latest)}</strong>${result.notes ? `<p>${esc(result.notes)}</p>` : ''}<div class="maintenance-actions">${action}</div>`;
    } else {
      holder.textContent = `当前已是最新版本 v${result.current}。`;
    }
    $('#open-releases')?.addEventListener('click', () => invoke('open_releases_page'));
    $('#install-update')?.addEventListener('click', installAvailableUpdate);
  }

  function updateAvailableIndicator(result) {
    const button = $('#help-button');
    if (!button) return;
    const available = Boolean(result?.ok && result.available);
    button.classList.toggle('update-available', available);
    const label = available ? `发现新版本 v${result.latest}，打开关于与维护` : '关于与维护';
    button.title = label;
    button.setAttribute('aria-label', label);
  }

  async function checkUpdates(silent = false) {
    const holder = $('#update-result');
    if (holder && !silent) {
      holder.className = 'update-result';
      holder.textContent = '正在检查更新...';
    }
    try {
      const result = await invoke('check_for_updates');
      availableUpdate = result;
      updateAvailableIndicator(result);
      if (!result.available || downloadedUpdate?.version !== result.latest) downloadedUpdate = null;
      if (result.available && silent) toast(`发现新版本 v${result.latest}`);
      if (holder || !silent) renderUpdateResult(result);
    } catch (error) {
      const result = { ok: false, message: error.message || '检查更新失败' };
      if (!silent) renderUpdateResult(result);
    }
  }

  async function installAvailableUpdate() {
    const button = $('#install-update');
    if (button) button.disabled = true;
    try {
      const downloaded = downloadedUpdate || await downloadAvailableUpdate(button);
      downloadedUpdate = downloaded;
      const confirmed = await confirmBox(
        `安装 v${downloaded.version}`,
        downloaded.platform === 'android'
          ? '安装包已通过校验。接下来将打开 Android 系统安装界面。'
          : '更新包已通过校验。程序将关闭、替换并自动重新启动。',
        '立即安装');
      if (!confirmed) {
        if (availableUpdate) renderUpdateResult(availableUpdate);
        return;
      }
      const installed = await invoke('install_downloaded_update', downloaded.path);
      if (installed?.permission_required) {
        toast('请允许此应用安装更新，然后返回并点击“继续安装”');
        if (availableUpdate) renderUpdateResult(availableUpdate);
      }
    } catch (error) {
      toast(error.message || '更新失败', 'error');
      if (availableUpdate) renderUpdateResult(availableUpdate);
    }
  }

  function formatDownloadSize(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderDownloadProgress(button, status) {
    const actions = button?.closest('.maintenance-actions') || $('#update-result .maintenance-actions');
    if (!actions) return;
    const total = Number(status.total) || 0;
    const downloaded = Number(status.downloaded) || 0;
    const percent = total ? Math.min(100, Math.round(downloaded * 100 / total)) : Number(status.progress) || 0;
    const detail = total
      ? `${percent}% · ${formatDownloadSize(downloaded)} / ${formatDownloadSize(total)}`
      : (status.phase === 'checking' ? '请稍候' : formatDownloadSize(downloaded));
    actions.innerHTML = `<div class="update-download-status" role="status" aria-live="polite">
      <div class="update-download-copy"><span>${esc(status.message || '正在下载安装包…')}</span><span>${esc(detail)}</span></div>
      <div class="update-download-track ${total ? '' : 'indeterminate'}"><span style="width:${total ? percent : 38}%"></span></div>
    </div>`;
  }

  async function downloadAvailableUpdate(button) {
    let status = await invoke('start_update_download', availableUpdate?.latest || '');
    while (!['ready', 'error'].includes(status.phase)) {
      renderDownloadProgress(button, status);
      await new Promise(resolve => setTimeout(resolve, 220));
      status = await invoke('get_update_download_status');
    }
    renderDownloadProgress(button, status);
    if (status.phase === 'error') throw new Error(status.error || '更新下载失败');
    if (!status.result?.path) throw new Error('下载完成但没有找到安装包');
    return status.result;
  }

  function bindEvents() {
    $$('[data-window-action]').forEach(button => {
      button.onclick = () => queue(() => runWindowAction(button.dataset.windowAction));
    });
    $('#app-titlebar').ondblclick = event => {
      if (event.target.closest('button, input, a, nav')) return;
      queue(() => runWindowAction('maximize'));
    };
    $$('[data-resize-edge]').forEach(handle => {
      handle.onpointerdown = event => {
        if (event.button !== 0
            || document.documentElement.dataset.platform === 'android') return;
        invoke('start_window_resize', handle.dataset.resizeEdge).catch(() => {});
      };
    });
    $('#startup-retry').onclick = initialize;
    document.addEventListener('pointerdown', event => {
      const openMenu = $('.data-change-batch-menu:not([hidden])');
      if (openMenu && !event.target.closest('.data-change-batch-popover')) {
        openMenu.hidden = true;
        $('#data-change-batch-trigger')?.setAttribute('aria-expanded', 'false');
      }
    });
    $('#startup-copy-error').onclick = async () => {
      if (!startupErrorReport) return;
      await writeClipboard(startupErrorReport);
      const button = $('#startup-copy-error');
      button.textContent = '已复制';
      setTimeout(() => { button.textContent = '复制错误报告'; }, 1200);
    };
    $('#theme-button').onclick = () => setTheme((state?.theme || 'light') === 'light' ? 'dark' : 'light', true);
    $('#mobile-library-button').onclick = () => {
      const opening = !document.body.classList.contains('mobile-library-open');
      closeMobilePanels();
      document.body.classList.toggle('mobile-library-open', opening);
    };
    $('#mobile-inspector-button').onclick = () => {
      const opening = !document.body.classList.contains('mobile-inspector-open');
      closeMobilePanels();
      document.body.classList.toggle('mobile-inspector-open', opening);
    };
    document.addEventListener('pointerdown', event => {
      if (!window.matchMedia('(max-width: 700px)').matches
          || !document.body.classList.contains('mobile-inspector-open')) return;
      if (event.target.closest?.('.inspector-shell, #mobile-inspector-button, .cell')) return;
      document.body.classList.remove('mobile-inspector-open');
    });
    $('#library-search-button').onclick = () => setLibrarySearchVisible(true);
    $('#library-search-close').onclick = () => setLibrarySearchVisible(false);
    $('#library-search-input').oninput = event => {
      draftLibraryQuery = event.target.value;
      renderDraftTree();
    };
    $('#library-search-input').onkeydown = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setLibrarySearchVisible(false);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        $('.library-search-results .draft-row')?.click();
      }
    };
    $('#tools-button').onclick = () => setUtilitybarVisible(
      $('#utilitybar').classList.contains('hidden'));
    $('#highlight-button').onclick = () => {
      setHighlightMode(!highlightMode);
      setUtilitybarVisible(false);
    };
    $('#exit-highlight-mode').onclick = () => setHighlightMode(false);
    $('#batch-button').onclick = () => {
      setUtilitybarVisible(false);
      openBatchEditor();
    };
    $('#undo-button').onclick = () => editAction('undo');
    $('#redo-button').onclick = () => editAction('redo');
    $('#save-button').onclick = () => {
      setUtilitybarVisible(false);
      queue(async () => {
        const result = await invoke('save_current');
        if (!result.ok) toast(result.message, 'error'); else { applyResult(result); toast('文稿已保存'); }
      });
    };
    $('#backend-log-button').onclick = openBackendLogs;
    $('#close-backend-log').onclick = () => $('#backend-log-dialog').close();
    $('#backend-log-dialog').addEventListener('close', () => {
      clearInterval(backendLogTimer);
      backendLogTimer = null;
    });
    $('#refresh-backend-log').onclick = () => refreshBackendLogs();
    $('#copy-backend-log').onclick = async () => {
      const payload = await invoke('get_backend_logs');
      await writeClipboard(payload?.text || '');
      toast('后台输出已复制');
    };
    $('#clear-backend-log').onclick = async () => {
      await invoke('clear_backend_logs');
      await refreshBackendLogs();
    };
    $('#startup-output-close').onclick = closeStartupOutput;
    $('#startup-output-open').onclick = openBackendLogs;
    $('#restart-button').onclick = async () => {
      const confirmed = await confirmBox(
        '重启应用', '当前内容已自动保存。应用将使用当前启动参数重新启动。', '立即重启');
      if (!confirmed) return;
      await actionQueue;
      await invoke('restart_app');
    };
    $('#new-draft-button').onclick = () => queue(async () => applyResult(await invoke('new_draft')));
    $('#new-folder-button').onclick = async () => {
      const name = await promptBox('新建文件夹', '文件夹名称', '新建文件夹');
      if (name) queue(async () => applyResult(await invoke('create_group', name, null)));
    };
    $('#help-button').onclick = () => openMaintenance();
    $('#close-maintenance').onclick = () => $('#maintenance-dialog').close();
    $('#close-history').onclick = () => $('#history-dialog').close();
    $('#close-batch').onclick = () => $('#batch-dialog').close();
    $('#maintenance-tabs').onclick = event => {
      const button = event.target.closest('button');
      if (!button) return;
      maintenanceTab = button.dataset.tab;
      renderMaintenance();
    };
    $('#export-button').onclick = async () => {
      if (!editor?.raw) return toast('没有可导出的内容');
      fillSchemes();
      $('#export-dialog').showModal();
      await refreshExport();
    };
    document.addEventListener('pointerdown', event => {
      const details = $('.export-experimental[open]');
      if (details && !details.contains(event.target)) details.open = false;
    });
    $('#open-scheme-picker').onclick = openSchemePicker;
    $('#import-scheme-picker').onclick = importSchemeFromPicker;
    $('#close-scheme-picker').onclick = () => $('#scheme-picker-dialog').close();
    $('#scheme-picker-filter').onclick = event => {
      const button = event.target.closest('[data-scheme-filter]');
      if (!button) return;
      schemePickerFilter = button.dataset.schemeFilter;
      schemePickerId = null;
      renderSchemePicker();
    };
    $('#scheme-picker-list').onclick = async event => {
      const row = event.target.closest('[data-scheme-row]');
      if (!row) return;
      const schemeId = row.dataset.schemeRow;
      const archive = event.target.closest('[data-toggle-scheme-archive]');
      if (archive) {
        await toggleSchemeArchived(schemeId, archive.dataset.toggleSchemeArchive === 'true');
        return;
      }
      if (event.target.closest('[data-edit-picked-scheme]')) {
        $('#export-scheme').value = schemeId;
        $('#scheme-picker-dialog').close();
        openSchemeEditor(schemeId);
        return;
      }
      const pick = event.target.closest('[data-pick-scheme]');
      if (!pick) return;
      schemePickerId = pick.dataset.pickScheme;
      renderSchemePicker();
    };
    $('#use-picked-scheme').onclick = usePickedScheme;
    $('#export-mode').onclick = async event => {
      const button = event.target.closest('button');
      if (!button) return;
      exportMode = button.dataset.value;
      await refreshExport();
    };
    Object.values(EXPORT_OPTION_INPUTS).forEach(selector => {
      $(selector).onchange = () => {
        persistExportOptions();
        refreshExport();
      };
    });
    $('#copy-export-button').onclick = async () => { await writeClipboard($('#export-output').value); richClipboard = null; toast('导出内容已复制'); };
    $('#open-image-export-button').onclick = openImageExport;
    $('#close-image-export').onclick = () => $('#image-export-dialog').close();
    $('#cancel-image-export').onclick = () => $('#image-export-dialog').close();
    $('#image-line-list').onchange = event => {
      const input = event.target.closest('[data-image-line]');
      if (!input) return;
      const sourceLine = Number(input.dataset.imageLine);
      if (input.checked) imageExport.hidden.delete(sourceLine);
      else imageExport.hidden.add(sourceLine);
      renderImageCanvas();
    };
    $('#image-select-all').onclick = () => {
      imageExport.hidden.clear();
      renderImageLineList();
      renderImageCanvas();
    };
    $('#image-clear-all').onclick = () => {
      imageExport.hidden = new Set(
        imageExport.lines.map(line => Number(line.source_line)));
      renderImageLineList();
      renderImageCanvas();
    };
    $('#copy-image-export').onclick = async () => {
      if (!imageExport.ready) return;
      const button = $('#copy-image-export');
      const original = button.textContent;
      button.disabled = true;
      button.textContent = '复制中…';
      try {
        await copyImageCanvas();
        toast('图片已复制到剪贴板');
      } catch (error) {
        const details = error?.message || String(error);
        toast(`复制图片失败：${details}`, 'error');
        console.error(error);
      } finally {
        button.textContent = original;
        updateImageExportSummary();
      }
    };
    $('#save-image-export').onclick = async () => {
      if (!imageExport.ready) return;
      const button = $('#save-image-export');
      const original = button.textContent;
      button.disabled = true;
      button.textContent = '正在保存…';
      try {
        const dataUrl = $('#image-export-canvas').toDataURL('image/png');
        const result = await invoke('export_image', dataUrl, imageExport.title, null);
        if (result?.ok) toast(`图片已导出：${result.path}`);
      } finally {
        button.textContent = original;
        updateImageExportSummary();
      }
    };
    $('#edit-scheme-button').onclick = () => openSchemeEditor();
    $('#close-scheme-button').onclick = () => $('#scheme-dialog').close();
    $('#scheme-undo').onclick = () => schemeHistory('undo');
    $('#scheme-redo').onclick = () => schemeHistory('redo');
    $('#import-scheme-button').onclick = async () => {
      const result = await importSchemeFile();
      if (!result.ok) return;
      schemeDraft = clone(result.scheme);
      state.schemes = result.schemes;
      state.selected_scheme = result.selected_scheme;
      schemeUndo = [];
      schemeRedo = [];
      fillSchemes();
      renderSchemeEditor();
      setSchemeSaveStatus('已导入', 'success');
      toast(`已导入方案 ${result.selected_scheme}`);
    };
    $('#export-scheme-button').onclick = async () => {
      commitSchemeMeta();
      const result = await invoke('export_scheme_json', schemeDraft, null);
      if (result.ok) toast(`方案已导出：${result.path}`);
    };
    $('#clone-scheme-button').onclick = async () => {
      const button = $('#clone-scheme-button');
      button.disabled = true;
      button.textContent = '复制中…';
      try {
        commitSchemeMeta();
        const sourceScheme = clone(schemeDraft);
        const copiedScheme = await invoke('clone_scheme', sourceScheme);
        if (JSON.stringify(schemeDraft) !== JSON.stringify(sourceScheme)) {
          setSchemeSaveStatus('复制未应用', 'dirty');
          toast('复制期间方案又有修改，请再次点击另存副本', 'error');
          return;
        }
        schemeDraft = clone(copiedScheme);
        schemeUndo = [];
        schemeRedo = [];
        renderSchemeEditor();
        markSchemeDirty();
        toast('已准备副本，保存后写入文件');
      } catch (error) {
        toast(`复制方案失败：${error?.message || String(error)}`, 'error');
        console.error(error);
      } finally {
        button.disabled = false;
        button.textContent = '另存副本';
      }
    };
    $('#save-scheme-button').onclick = async () => {
      const button = $('#save-scheme-button');
      button.disabled = true;
      button.textContent = '保存中…';
      setSchemeSaveStatus('正在保存', 'saving');
      try {
        commitSchemeMeta();
        const submittedScheme = clone(schemeDraft);
        const issues = await invoke('validate_scheme', submittedScheme);
        if (issues.some(item => item.severity === 'error')) {
          schemeTab = 'tools';
          renderSchemeEditor();
          setSchemeSaveStatus('存在错误', 'error');
          toast('方案存在错误，请先修复', 'error');
          return;
        }
        const result = await invoke('save_scheme', submittedScheme);
        const editedWhileSaving = JSON.stringify(schemeDraft) !== JSON.stringify(submittedScheme);
        if (!editedWhileSaving) schemeDraft = clone(result.scheme);
        state.schemes = result.schemes;
        state.selected_scheme = result.selected_scheme;
        fillSchemes();
        renderSchemeEditor();
        await refreshExport();
        if (editedWhileSaving) {
          setSchemeSaveStatus('已保存 · 有新修改', 'dirty');
          toast('方案已保存，仍有未保存的新修改');
        } else {
          const savedAt = new Date().toLocaleTimeString('zh-CN', { hour12: false });
          setSchemeSaveStatus(`已保存 ${savedAt}`, 'success');
          toast('方案已保存');
        }
      } catch (error) {
        setSchemeSaveStatus('保存失败', 'error');
        toast(`方案保存失败：${error?.message || String(error)}`, 'error');
        console.error(error);
      } finally {
        button.disabled = false;
        button.textContent = '保存方案';
      }
    };
    $('#scheme-tabs').onclick = event => {
      const button = event.target.closest('button');
      if (!button) return;
      commitSchemeMeta();
      schemeTab = button.dataset.tab;
      renderSchemeEditor();
    };
    ['scheme-id', 'scheme-name', 'scheme-description'].forEach(id => {
      $(`#${id}`).onchange = () => { commitSchemeHistory(); commitSchemeMeta(); markSchemeDirty(); };
    });
    $('#add-lookup-part').onclick = () => addLookupPart();
    $('#lookup-field').onchange = refreshLookupPreview;
    $('#lookup-dialog').addEventListener('close', () => {
      if ($('#lookup-dialog').returnValue !== 'default' || !lookupTarget) return;
      commitSchemeHistory();
      schemeDraft.rules[lookupTarget.section][lookupTarget.index][0] = collectLookupExpression();
      renderSchemeRules();
      markSchemeDirty();
    });
    bindSearchEvents();
    bindEditorEvents();
    bindInspectorResize();
  }

  function commitSchemeMeta() {
    if (!schemeDraft) return;
    schemeDraft.id = $('#scheme-id').value.trim();
    schemeDraft.name = $('#scheme-name').value.trim() || schemeDraft.id;
    schemeDraft.description = $('#scheme-description').value.trim();
  }

  function bindSearchEvents() {
    $('#search-button').onclick = () => setSearchVisible(!search.visible);
    $('#search-close').onclick = closeSearch;
    $('#search-input').oninput = event => { search.query = event.target.value; search.index = 0; recomputeSearch(true); };
    $('#search-scope').onclick = event => {
      const button = event.target.closest('button');
      if (!button) return;
      search.scope = button.dataset.value;
      $$('#search-scope button').forEach(item => item.classList.toggle('active', item === button));
      search.index = 0;
      recomputeSearch(true);
    };
    const jump = direction => {
      if (!search.matches.length) return;
      search.index = (search.index + direction + search.matches.length) % search.matches.length;
      renderEditor();
      const [li, ci] = search.matches[search.index];
      $(`.cell[data-line="${li}"][data-column="${ci}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    };
    $('#search-prev').onclick = () => jump(-1);
    $('#search-next').onclick = () => jump(1);
    $('#search-input').onkeydown = event => {
      const ctrl = event.ctrlKey || event.metaKey;
      if (ctrl && event.key.toLowerCase() === 'f') {
        event.preventDefault();
        closeSearch();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        jump(event.shiftKey ? -1 : 1);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closeSearch();
      }
    };
    const replace = async replaceAll => {
      if (!search.query) return toast('请先输入查找内容');
      const current = search.matches[search.index] || editor.cursor;
      const scope = search.scope === 'phon' ? 'phon' : 'char';
      const result = await invoke(
        'replace_text', search.query, $('#replace-input').value,
        replaceAll, scope, current[0], current[1]);
      applyResult(result.editor);
      search.index = 0;
      recomputeSearch(true);
      toast(result.count ? `已替换 ${result.count} 处` : '没有可替换的匹配');
    };
    $('#replace-one').onclick = () => replace(false);
    $('#replace-all').onclick = async () => {
      if (!search.query) return toast('请先输入查找内容');
      const ok = await confirmBox('全部替换', `将正文中的匹配内容替换为「${$('#replace-input').value}」。`, '全部替换');
      if (ok) replace(true);
    };
  }

  function editAction(action, extend = false) {
    queue(async () => applyResult(await invoke('editor_action', action, extend)));
  }

  function collectVisualCaretPositions() {
    const positions = [];
    $$('.editor-line').forEach(lineNode => {
      const line = Number(lineNode.dataset.line);
      const cells = $$('.cell', lineNode);
      cells.forEach((cell, column) => {
        const rect = cell.getBoundingClientRect();
        positions.push({ line, column, x: rect.left, y: rect.top });
      });
      if (cells.length) {
        const rect = cells[cells.length - 1].getBoundingClientRect();
        positions.push({
          line, column: cells.length, x: rect.right, y: rect.top
        });
      } else {
        const rect = lineNode.getBoundingClientRect();
        positions.push({ line, column: 0, x: rect.left, y: rect.top });
      }
    });
    return positions;
  }

  function moveCaretVisual(direction, extend) {
    const positions = collectVisualCaretPositions();
    const current = positions.find(position =>
      position.line === editor.cursor[0] && position.column === editor.cursor[1]);
    if (!current) {
      editAction(direction < 0 ? 'Up' : 'Down', extend);
      return;
    }
    const rowTops = [];
    positions.map(position => position.y).sort((a, b) => a - b).forEach(top => {
      if (!rowTops.some(existing => Math.abs(existing - top) < 3)) rowTops.push(top);
    });
    const rowIndex = rowTops.findIndex(top => Math.abs(top - current.y) < 3);
    const targetTop = rowTops[rowIndex + direction];
    if (rowIndex < 0 || targetTop === undefined) return;
    if (visualNavX === null) visualNavX = current.x;
    const candidates = positions.filter(position => Math.abs(position.y - targetTop) < 3);
    const target = candidates.reduce((best, position) =>
      Math.abs(position.x - visualNavX) < Math.abs(best.x - visualNavX)
        ? position : best, candidates[0]);
    queue(async () => {
      await setCaret(target.line, target.column, extend, true);
      requestAnimationFrame(() => $('.caret')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
    });
  }

  function bindEditorEvents() {
    const root = $('#editor');
    const capture = $('#input-capture');
    const scroll = $('#editor-scroll');
    scroll.addEventListener('wheel', adjustEditorZoom, { passive: false });
    $('#export-output').addEventListener(
      'wheel', adjustEditorZoom, { passive: false });
    scroll.addEventListener('click', event => { if (!event.target.closest('.cell')) focusEditor(); });
    root.addEventListener('mousedown', event => {
      const cell = event.target.closest('.cell');
      const lineNode = event.target.closest('.editor-line');
      if (!lineNode || event.button !== 0) return;
      event.preventDefault();
      mouseSelecting = false;
      mouseMoved = false;
      const line = Number(lineNode.dataset.line);
      const column = cell ? Number(cell.dataset.column) : null;
      const rightHalf = cell
        ? event.clientX > cell.getBoundingClientRect().left + cell.offsetWidth / 2
        : false;
      const caretColumn = cell
        ? column + (rightHalf ? 1 : 0)
        : editor.lines[line].length;
      mouseDown = {
        x: event.clientX, y: event.clientY, line, column,
        caretColumn,
        shiftKey: event.shiftKey
      };
      queue(async () => setCaret(line, caretColumn, event.shiftKey));
    });
    window.addEventListener('mousemove', event => {
      if (!mouseDown || !(event.buttons & 1)) return;
      const distance = Math.hypot(
        event.clientX - mouseDown.x, event.clientY - mouseDown.y);
      if (!mouseSelecting && distance < 7) return;
      mouseSelecting = true;
      mouseMoved = true;
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const cell = target?.closest?.('.cell');
      const lineNode = target?.closest?.('.editor-line');
      if (!lineNode) return;
      const line = Number(lineNode.dataset.line);
      let column = editor.lines[line].length;
      if (cell) {
        const rect = cell.getBoundingClientRect();
        column = Number(cell.dataset.column)
          + (event.clientX > rect.left + rect.width / 2 ? 1 : 0);
      }
      queue(async () => setCaret(line, column, true));
    });
    window.addEventListener('mouseup', async event => {
      if (!mouseDown) return;
      const clickInfo = mouseDown;
      mouseDown = null;
      mouseSelecting = false;
      const cell = event.target.closest?.('.cell');
      if (cell && clickInfo.column !== null && !mouseMoved && !clickInfo.shiftKey) {
        const line = clickInfo.line;
        const column = clickInfo.column;
        const data = editor.lines[line][column];
        if (highlightMode && !data.in_bracket) {
          queue(async () => applyResult(await invoke('toggle_highlight', line, column)));
        } else if (!data.in_bracket) {
          inspectorCell = { line, column };
          renderInspector();
          if (window.matchMedia('(max-width: 700px)').matches) {
            closeMobilePanels();
            document.body.classList.add('mobile-inspector-open');
          }
        }
      }
      focusEditor();
    });
    capture.addEventListener('compositionstart', () => { composing = true; });
    capture.addEventListener('compositionend', event => {
      composing = false;
      visualNavX = null;
      const text = event.target.value;
      event.target.value = '';
      if (text) queue(async () => applyResult(await invoke('insert_text', text, null)));
    });
    capture.addEventListener('input', event => {
      if (composing || event.isComposing) return;
      visualNavX = null;
      const text = event.target.value;
      event.target.value = '';
      if (text) queue(async () => applyResult(await invoke('insert_text', text, null)));
    });
    capture.addEventListener('paste', event => {
      event.preventDefault();
      visualNavX = null;
      const text = normalizeClipboardText(event.clipboardData.getData('text/plain'));
      const payload = richClipboard
        && normalizeClipboardText(richClipboard.text) === text
        ? richClipboard : null;
      queue(async () => applyResult(await invoke('insert_text', text, payload)));
    });
    capture.addEventListener('keydown', event => handleEditorKey(event));
    $('#editor-scroll').addEventListener('scroll', () => {
      positionInputCapture();
      clearTimeout(scrollSaveTimer);
      scrollSaveTimer = setTimeout(() => invoke(
        'save_editor_view', $('#editor-scroll').scrollTop).catch(() => {}), 250);
    });
  }

  function handleEditorKey(event) {
    if (event.isComposing || event.key === 'Process') return;
    const ctrl = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (ctrl) {
      visualNavX = null;
      if (key === 'z') { event.preventDefault(); editAction(event.shiftKey ? 'redo' : 'undo'); }
      else if (key === 'y') { event.preventDefault(); editAction('redo'); }
      else if (key === 'a') { event.preventDefault(); editAction('select_all'); }
      else if (key === 'c') { event.preventDefault(); copySelection(editor.selection ? selectionCopyMode : 'raw'); }
      else if (key === 'x') { event.preventDefault(); cutSelection(); }
      else if (key === 'f') { event.preventDefault(); $('#search-button').click(); }
      else if (key === 's') { event.preventDefault(); $('#save-button').click(); }
      return;
    }
    const nav = { ArrowLeft: 'Left', ArrowRight: 'Right', ArrowUp: 'Up', ArrowDown: 'Down', Home: 'Home', End: 'End' };
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      moveCaretVisual(event.key === 'ArrowUp' ? -1 : 1, event.shiftKey);
    } else if (nav[event.key]) {
      event.preventDefault();
      visualNavX = null;
      editAction(nav[event.key], event.shiftKey);
    }
    else if (event.key === 'Backspace') { event.preventDefault(); visualNavX = null; editAction('backspace'); }
    else if (event.key === 'Delete') { event.preventDefault(); visualNavX = null; editAction('delete'); }
    else if (event.key === 'Enter') { event.preventDefault(); visualNavX = null; editAction('newline'); }
    else if (event.key === 'Escape') { event.preventDefault(); visualNavX = null; if (highlightMode) setHighlightMode(false); else editAction('escape'); }
  }

  function bindGlobalShortcuts() {
    document.addEventListener('keydown', event => {
      if (!$('#scheme-dialog').open) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      if (key === 'z') { event.preventDefault(); schemeHistory(event.shiftKey ? 'redo' : 'undo'); }
      if (key === 'y') { event.preventDefault(); schemeHistory('redo'); }
    });
  }

  function createMockApi() {
    const controlLine = [...'[Verse,clear male vocal]'].map(char => ({
      char, phonetic: char, is_poly: false, selected: 'none',
      manual_hl: false, stale: false, in_bracket: true,
    }));
    let mockGroupExpanded = true;
    let mockBackendLog = '[11:20:01] 汉字转 PBOC 音标 v0.12.8 正在启动\n正在检查 base.json.gz ...\n数据准备完成';
    const mockUpdate = {
      id: 'mock-reading-update', batch_id: 'b1',
      timestamp: '2026-08-22 23:55:03', filename: 'base.json.gz',
      batch_count: 98, kind: '修改', char: '之',
      summary: '移除 tə; 新增 tə-new', removed: ['tə'], added: ['tə-new'],
    };
    let mock = {
      lines: [controlLine, [
        { char: '关', phonetic: 'kˤro[n]', is_poly: false, selected: 'none', manual_hl: false, stale: false, in_bracket: false },
        { char: '关', phonetic: 'kˤro[n]s', is_poly: true, selected: 'manual', manual_hl: false, stale: false, in_bracket: false },
        { char: '雎', phonetic: 'tsa', is_poly: false, selected: 'none', manual_hl: false, stale: false, in_bracket: false }
      ], [
        { char: '在', phonetic: 'dzˤəʔ', is_poly: true, selected: 'global_recent', manual_hl: false, stale: false, in_bracket: false },
        { char: '河', phonetic: 'gˤaj', is_poly: false, selected: 'none', manual_hl: true, stale: false, in_bracket: false },
        { char: '之', phonetic: 'tə', is_poly: false, selected: 'none', manual_hl: false, stale: true, in_bracket: false },
        { char: '洲', phonetic: 'tu', is_poly: false, selected: 'none', manual_hl: false, stale: false, in_bracket: false }
      ]], cursor: [1, 0], selection: null, dirty: false, current_draft: 'demo.json', current_name: '关雎', can_undo: true, can_redo: false, raw: '[Verse,clear male vocal]\n关关雎\n在河之洲'
    };
    const schemes = [
      { id: 'current_suno', name: '当前 Suno 方案', description: '默认混合文字转写方案', created_at: '2026-07-01T08:00:00Z', archived: false },
      { id: 'arb', name: '阿文强化', description: '强化阿文发音，2026.7.2', created_at: '2026-07-02T08:00:00Z', archived: false },
      { id: 'dg', name: '浊音修改', description: '浊音调整，260801', created_at: '2026-08-01T08:00:00Z', archived: false },
    ];
    const scheme = {
      id: 'current_suno', name: '清响音修改', description: '浏览器预览数据',
      options: { improve_pharyngeal: true, improve_syllable: false, english_voiced_stops: false },
      option_definitions: {
        english_voiced_stops: {
          label: '浊塞音拼写', description: '鼻音诱导：mб / nд / ŋг；英美：б / ντ / γκ。',
          off_label: '鼻音诱导', on_label: '英美',
          when_false: { maps: { onset: { b: 'mб', d: 'nд', g: 'ŋг' } } },
          when_true: { maps: { onset: { b: 'б', d: 'ντ', g: 'γκ' } } },
        },
      },
      maps: { onset: { k: 'к', t: 'т', b: 'mб', d: 'nд', g: 'ŋг' }, glide: { r: 'р' }, nucleus: { a: 'α' }, coda: { n: 'n' }, tone: { s: 's' }, residual: {} },
      labels: {}, parse_order: {}, rules: { pre_normalize: [['ʰ', 'h']], residual_preprocess: [], residual_replace: [], pharyngeal_relax: [], syllable_relax: [], post_replace: [] }
    };
    const mockDrafts = [{ filename: 'demo.json', name: '关雎', preview: '关关雎在河之洲', stale: true, unselected_polyphonic: 2, manually_completed: false }, { filename: 'notes.json', name: '风雅笔记', preview: '采采卷耳', stale: false, unselected_polyphonic: 0, manually_completed: true }];
    const previewChangelog = [
      { version: '0.12.8', date: '2026-08-28', title: 'PBOC 更名与界面整理', items: ['软件对外名称由 NOCM 改为 PBOC。', '应用采用蓝底白色“漢”字图标；加载标志和应用顶栏图标会跟随深浅主题变化，Windows 任务栏使用浅蓝底版本。', '文稿库以橙色左侧标识尚有多音字未选的文稿，以绿色左侧标识手动标记完成的文稿。', '文稿库标题栏新增搜索，可按文稿名称、正文摘要或文件名实时筛选。', '文稿与文件夹操作菜单会避开窗口边缘，靠近底部时自动向上展开。', 'Windows 正式版在无终端窗口模式下收集后台输出；可从“更多工具”查看，启动完成后也会在右下角显示本次启动输出。', 'Windows 原生标题栏整合进应用顶栏，图标与窗口控制集中在同一行，并保留拖动、双击最大化与边缘缩放。', '正文编辑区和文本导出页支持按住 Ctrl 滚动鼠标滚轮调整字号，缩放比例会自动保存。', '精简导出与确认弹窗，移除重复标题和无意义分隔线，并将实验性导出规则收纳到独立入口。', '查找、撤回、重做、高亮、批量与保存集中到可展开的“更多工具”行；查找范围位于左侧，查找与替换输入框位于右侧。', '作者与测试人员名称增加 Bilibili 主页链接。', '移动端下载更新时显示实时进度和文件大小。', '发现新版本后，问号按钮会持续显示更新提示色。', '深色模式从应用启动和加载界面开始生效。'] },
      { version: '0.12.7', date: '2026-08-27', title: '方案解析顺序编辑', items: ['映射表新增拖动排序，表格顺序就是实际检测顺序。', '替换规则同样支持拖动排序，并严格按照界面顺序执行。', '编辑映射项、输出或中文说明时保留原位置，不会把修改项移到末尾。'] },
      { version: '0.12.6', date: '2026-08-26', title: '应用自动更新与一键发布', items: ['启动后可自动检查更新，并直接下载适用于当前平台的安装包。', '更新包会进行 SHA-256 校验；Windows 自动替换重启，Android 交由系统安装。', '新增一键 GitHub Release 发布脚本。', '调整数据变更页批次与搜索控件，并移除诊断列表顶部多余的分隔线。', '批次选择改为软件统一样式的浮层菜单。'] },
      { version: '0.12.5', date: '2026-08-25', title: '数据变更查看器', items: ['维护页面新增可解析大体积日志的数据变更查看器，支持按批次分页、字段级新旧值对照和内容搜索。', '维护窗口合并标题与页面导航，数据变更页取消批次侧栏和重复标题栏，正文区域在宽窄窗口中都能获得更多空间。', '读音更新改为逐文稿、逐位置确认，可采用新读音、保留原读音、重新审阅或恢复确认前读音。', '文稿库文件夹增加开合图标并优化层级缩进；单击整行即可展开或折叠。'] },
      { version: '0.12.4', date: '2026-08-08', title: 'Windows 安装包文件名统一', items: ['Windows 发布程序改为“汉转PBOC-版本号.exe”，单独取出后也能识别版本。'] },
      { version: '0.12.3', date: '2026-08-08', title: 'Android 启动加载页修复', items: ['Android 会先显示匹配系统主题的 HTML 加载页，再等待 Python 后端和词库，消除启动白屏。'] },
      { version: '0.12.2', date: '2026-08-08', title: 'Android 覆盖安装兼容修复', items: ['系统栏隐藏改用 Android 7 起支持的兼容方式，并隔离厂商系统异常，避免覆盖安装后启动退出。'] },
      { version: '0.12.1', date: '2026-08-08', title: 'Android 横屏与运行模式', items: ['Android 强制横屏并隐藏系统状态栏，横屏保留原有桌面布局，诊断页运行模式显示为 Android APK。'] },
      { version: '0.12.0', date: '2026-08-07', title: 'Android 应用预览版', items: ['新增 Android WebView 与 Python 桥接、手机端文稿库和读音信息抽屉，并支持从系统文件选择器导入方案。'] },
      { version: '0.11.7', date: '2026-08-06', title: '关闭图标对齐', items: ['所有查找栏和弹窗的关闭按钮统一使用居中的 SVG 叉号。'] },
      { version: '0.11.6', date: '2026-08-06', title: '界面层级与工具栏整理', items: ['合并方案弹窗标题栏、移除多余箭头，并整理导出选项和工具图标。'] },
      { version: '0.11.5', date: '2026-08-06', title: '忽略方括号控制行', items: ['文本导出可选择删除整行由 [] 包裹的控制标签。'] },
      { version: '0.11.4', date: '2026-08-04', title: '历史更新公告整理', items: ['将原先集中记录在 v0.10.0 的功能按对话时间拆分为 v0.9.1 至 v0.9.6。'] },
      { version: '0.11.3', date: '2026-08-04', title: '方案归档与调试选项', items: ['方案按创建时间排列并支持归档；实验性导出规则移入调试模式。'] },
      { version: '0.11.2', date: '2026-08-04', title: '清响音增强选项', items: ['Suno 导出新增在清响音转写结果前额外添加 h 的选项。'] },
      { version: '0.11.1', date: '2026-08-04', title: '空方案初始状态', items: ['打包程序不再内嵌默认方案，并完善零方案时的导入入口。'] },
      { version: '0.11.0', date: '2026-08-04', title: '方案选择与排序界面', items: ['新增显示备注、修改备注和持久化排序的方案选择弹窗。'] },
      { version: '0.10.7', date: '2026-08-04', title: '喉塞音声调导出选项', items: ['Suno 导出新增仅删除声调后缀中喉塞音 ʔ 的选项。'] },
      { version: '0.10.6', date: '2026-08-04', title: '图片裁剪与剪贴板完善', items: ['图片按正文实际宽度导出，并支持直接复制 PNG 到系统剪贴板。'] },
      { version: '0.10.5', date: '2026-08-04', title: '图片预览容器修复', items: ['修复预览容器选择器不一致导致所有图片绘制完成后仍显示渲染失败的问题。'] },
      { version: '0.10.4', date: '2026-08-04', title: '中文名称输入修复', items: ['修复使用中文输入法输入文件夹或文稿名称后，回车无法确认的问题。'] },
      { version: '0.10.3', date: '2026-08-04', title: '长图渲染与文稿恢复修复', items: ['长文稿图片自适应安全高度，并在启动时恢复上次打开的文稿。'] },
      { version: '0.10.2', date: '2026-08-04', title: '图片预览空白修复', items: ['恢复兼容 WebView2 的图片渲染，并增加明确错误提示。'] },
      { version: '0.10.1', date: '2026-08-04', title: '图片预览与标签排版修复', items: ['优化控制行间距、导出列表留白和高 DPI 图片预览。'] },
      { version: '0.10.0', date: '2026-08-03', title: '正文图片导出', items: ['加入可保留音标、主题和编辑状态样式的正文图片导出。'] },
      { version: '0.9.6', date: '2026-08-02', title: 'Suno 导出工具完善', items: ['完善标点换行、换行清理、去咽化、去声调和喉塞音前声调调整。'] },
      { version: '0.9.5', date: '2026-08-01', title: '读音提示与词库更新标记', items: ['恢复读音义项样式、缺音警告和文稿库词库更新提示。'] },
      { version: '0.9.4', date: '2026-07-29', title: '富状态剪贴与正文编辑', items: ['剪切、复制和跨行粘贴可保留手动选择的多音字读音。'] },
      { version: '0.9.3', date: '2026-07-26', title: '方案编辑与保存完善', items: ['加入映射项拼接、保存反馈、撤回重做、另存副本和方案选择持久化。'] },
      { version: '0.9.2', date: '2026-07-23', title: '资料迁移与维护工具', items: ['加入旧资料库导入、备份恢复、重启和下载错误报告。'] },
      { version: '0.9.1', date: '2026-07-20', title: 'HTML 界面全面调整', items: ['全面调整读音面板、拖动交互、滚动条和弹窗布局。'] },
      { version: '0.9.0', date: '2026-07-16', title: 'HTML 桌面界面预览版', items: ['界面迁移到 HTML 与 WebView2。'] },
    ];
    const full = () => ({ ok: true, editor: clone(mock), drafts: mockDrafts, recent_drafts: [mockDrafts[0]], groups: [{ id: 'g1', name: '诗经', expanded: mockGroupExpanded, files: ['demo.json'], children: [] }], schemes, selected_scheme: 'current_suno', theme: 'light', version: '0.12.8', ui_preferences: { inspector_width: 320, debug_mode: false }, changelog: previewChangelog });
    return new Proxy({
      initialize: async () => full(), get_startup_status: async () => ({ message: '准备就绪', progress: 100 }),
      get_cell_details: async (li, ci) => {
        const cell = mock.lines[li][ci];
        const sameCharCount = mock.lines.reduce(
          (count, line) => count + line.filter(item => item.char === cell.char).length, 0);
        const pending = cell.stale ? [mockUpdate] : [];
        return { line: li, column: ci, char: cell.char, ...cell, same_char_count: sameCharCount, pending_updates: pending, confirmed_updates: cell.confirmed_updates || [], options: cell.stale ? [{ phonetic: 'tə-new', note: '1甲《新词库》更新后的读音' }] : [{ phonetic: cell.phonetic, note: '1甲《诗经》当前读音2乙《广韵》补充说明' }, { phonetic: 'kˤron', note: '1甲《说文》备选读音' }] };
      },
      get_scheme: async () => clone(scheme), clone_scheme: async value => ({ ...clone(value), id: `${value.id}_copy`, name: `${value.name} 副本` }),
      save_scheme: async value => ({ ok: true, scheme: value, schemes, selected_scheme: value.id }),
      import_scheme_json: async () => ({ ok: true, scheme: clone(scheme), schemes, selected_scheme: scheme.id }),
      export_scheme_json: async () => ({ ok: true, path: '预览目录/current_suno.json' }),
      validate_scheme: async () => [], preview_scheme: async (_value, text) => ({ ok: true, issues: [], output: text }),
      compare_scheme: async () => ({ other: schemes[0], differences: [] }),
      export_text: async mode => mode === 'raw' ? mock.raw : 'kˤro[n] kˤro[n]s tsa\ndzˤəʔ gˤaj tə tu',
      get_image_export_data: async () => ({
        ok: true,
        title: mock.current_name,
        lines: mock.lines.map((line, sourceLine) => {
          const cells = line.filter(cell => !cell.in_bracket).map(cell => ({
            char: cell.char,
            phonetic: cell.phonetic,
            is_poly: cell.is_poly,
            selected: cell.selected,
            manual_hl: cell.manual_hl,
            stale: cell.stale,
            missing_phonetic: cell.missing_phonetic,
          }));
          const blank = !cells.some(cell => cell.char.trim());
          return { source_line: sourceLine, cells: blank ? [] : cells, blank };
        }),
      }),
      export_image: async () => ({ ok: true, path: '预览目录/关雎.png' }),
      set_caret: async (li, ci, extend) => { if (extend && !mock.selection) mock.selection = [clone(mock.cursor), [li, ci]]; else if (extend) mock.selection[1] = [li, ci]; else mock.selection = null; mock.cursor = [li, ci]; return clone(mock); },
      editor_action: async () => clone(mock), get_copy_payload: async () => ({ text: mock.raw, buffer: [], cell_info: [] }), get_phonetic_text: async () => 'kˤro[n]',
      reading_conflicts: async () => [], apply_reading: async () => clone(mock),
      review_cell_update: async (li, ci, _eventId, action, phonetic) => {
        const cell = mock.lines[li][ci];
        const before = cell.phonetic;
        if (action === 'accept') cell.phonetic = phonetic;
        cell.stale = false;
        cell.confirmed_updates = [{ ...mockUpdate, review: { status: action === 'accept' ? 'accepted_new' : 'kept_current', before, after: cell.phonetic } }];
        return full();
      },
      reopen_cell_update: async (li, ci, _eventId, restore) => {
        const cell = mock.lines[li][ci];
        const review = cell.confirmed_updates?.[0]?.review;
        if (restore && review) cell.phonetic = review.before;
        cell.confirmed_updates = [];
        cell.stale = true;
        return full();
      },
      set_draft_completed: async (filename, completed) => {
        const draft = mockDrafts.find(item => item.filename === filename);
        if (draft) draft.manually_completed = Boolean(completed);
        return full();
      },
      toggle_group: async () => { mockGroupExpanded = !mockGroupExpanded; return full(); },
      toggle_highlight: async (li, ci) => {
        mock.lines[li][ci].manual_hl = !mock.lines[li][ci].manual_hl;
        return clone(mock);
      },
      get_polyphonic_summary: async () => [{ char: '关', count: 2, readings: { 'kˤro[n]s': 1, 'kˤro[n]': 1 }, options: [{ phonetic: 'kˤro[n]s' }, { phonetic: 'kˤro[n]' }] }],
      batch_apply_reading: async () => clone(mock), get_draft_history: async () => [{ id: 'demo.json', name: '关雎', modified: '2026-07-16T12:00:00', preview: '关关雎在河之洲' }],
      get_diagnostics: async () => ({ app_version: '0.12.8', draft_schema_version: 3, scheme_schema_version: 2, python: '3.13', webview: '6.2.1', frozen: false, runtime_mode: '源码预览', draft_count: 2, scheme_count: 3, app_dir: '预览目录', draft_dir: '预览目录/drafts', scheme_dir: '预览目录/schemes' }),
      get_backend_logs: async () => ({ text: mockBackendLog, started_at: '2026-08-28T11:20:01+08:00', characters: mockBackendLog.length }),
      clear_backend_logs: async () => { mockBackendLog = ''; return { text: '', started_at: '2026-08-28T11:20:01+08:00', characters: 0 }; },
      import_old_library: async () => ({ ok: true, imported: 2, skipped: 1, renamed: 0, errors: [], state: full() }),
      check_for_updates: async () => ({ ok: true, current: '0.12.8', latest: '0.12.8', available: false }),
      start_update_download: async () => ({ phase: 'ready', progress: 100, downloaded: 1024, total: 1024, result: { ok: true, version: '0.12.8', platform: 'windows', path: 'preview-update.exe' } }),
      get_update_download_status: async () => ({ phase: 'ready', progress: 100, downloaded: 1024, total: 1024, result: { ok: true, version: '0.12.8', platform: 'windows', path: 'preview-update.exe' } }),
      install_downloaded_update: async () => ({ ok: true, scheduled: true }),
      get_data_change_batches: async () => ({ ok: true, exists: true, file_size: 77729928, total: 2, items: [
        { id: 'b2', timestamp: '2026-08-22 23:55:12', filename: 'extra.json.gz', count: 10427 },
        { id: 'b1', timestamp: '2026-08-22 23:55:03', filename: 'base.json.gz', count: 98 },
      ] }),
      get_data_change_entries: async (batchId, offset = 0, limit = 80, query = '') => {
        const fixtures = batchId === mockUpdate.batch_id ? [{
          event_id: mockUpdate.id, kind: mockUpdate.kind,
          label: mockUpdate.char, summary: mockUpdate.summary, details: [],
        }] : [
          batchId === 'b2'
            ? { kind: '修改', label: '#18', display_label: '夫 · #18', summary: '', details: [], unchanged_count: 7, changes: [{ field: '总出现次数', status: '修改', old: 5277, new: 5360 }] }
            : { kind: '修改', label: '关', summary: '移除 kˤron; 新增 kˤro[n]', details: [] },
          batchId === 'b2'
            ? { kind: '新增', label: '#19', display_label: '雎 · #19', summary: '', details: [], unchanged_count: 0, changes: [{ field: '字头', status: '新增', old: null, new: '雎' }, { field: '释义', status: '新增', old: null, new: ['', ['鸟名。雎鸠，常见于《诗经·关雎》。', '亦作水鸟名。']] }] }
            : { kind: '新增', label: '雎', summary: 'tsa', details: [] },
        ];
        const needle = query.trim().toLowerCase();
        const filtered = needle ? fixtures.filter(item =>
          JSON.stringify(item).toLowerCase().includes(needle)) : fixtures;
        return { ok: true, total: filtered.length, items: filtered.slice(offset, offset + limit) };
      },
      reorder_schemes: async ids => { schemes.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id)); return { ok: true, schemes: clone(schemes) }; },
      update_scheme_description: async (id, description) => { const item = schemes.find(value => value.id === id); if (item) item.description = description.trim(); return { ok: true, scheme: clone(item), schemes: clone(schemes) }; },
      set_scheme_archived: async (id, archived) => { const item = schemes.find(value => value.id === id); if (item) item.archived = archived; const selected = archived && id === 'current_suno' ? schemes.find(value => !value.archived)?.id || null : 'current_suno'; return { ok: true, schemes: clone(schemes), selected_scheme: selected }; },
      select_scheme: async () => ({ ok: true }), get_theme_preference: async () => ({ theme: document.documentElement.dataset.theme || 'light' }), set_theme: async theme => ({ theme }), set_ui_preference: async (_key, value) => ({ ok: true, value }), save_editor_view: async () => ({ ok: true }), open_source_url: async () => ({ ok: true }), restart_app: async () => ({ ok: true }), get_window_state: async () => ({ maximized: false }), minimize_window: async () => ({ ok: true }), toggle_maximize_window: async () => ({ ok: true, maximized: document.documentElement.classList.toggle('window-maximized') }), close_window: async () => ({ ok: true })
    }, { get(target, prop) { return target[prop] || (async () => full()); } });
  }

  bindEvents();
  bindGlobalShortcuts();
  window.addEventListener('unhandledrejection', event => {
    toast(event.reason?.message || String(event.reason || '操作失败'), 'error');
  });
  window.addEventListener('resize', () => {
    if (!$('#image-export-dialog').open) return;
    clearTimeout(imageResizeTimer);
    imageResizeTimer = setTimeout(renderImageCanvas, 100);
  });
  window.handleAndroidBack = () => {
    const dialogs = $$('dialog[open]');
    if (dialogs.length) {
      dialogs[dialogs.length - 1].close();
      return true;
    }
    if ($('.sidebar-heading').classList.contains('searching')) {
      setLibrarySearchVisible(false);
      return true;
    }
    if (document.body.classList.contains('mobile-library-open')
        || document.body.classList.contains('mobile-inspector-open')) {
      closeMobilePanels();
      return true;
    }
    if (highlightMode) {
      setHighlightMode(false);
      return true;
    }
    if (search.visible) {
      closeSearch();
      return true;
    }
    if (!$('#utilitybar').classList.contains('hidden')) {
      setUtilitybarVisible(false);
      return true;
    }
    return false;
  };
  let apiStarted = false;
  const startApi = candidate => {
    if (apiStarted || !candidate
        || typeof candidate.initialize !== 'function') return false;
    apiStarted = true;
    api = candidate;
    (async () => {
      await new Promise(resolve => requestAnimationFrame(
        () => requestAnimationFrame(resolve)));
      try {
        const preference = await invoke('get_theme_preference');
        if (preference?.theme) setTheme(preference.theme);
      } catch (_) { /* keep the system theme until initialization completes */ }
      try {
        const windowState = await invoke('get_window_state');
        setDesktopWindowMaximized(windowState?.maximized);
      } catch (_) { /* Android does not expose desktop window controls */ }
      initialize();
    })();
    return true;
  };
  const androidApi = window.AndroidApi ? createAndroidApi(window.AndroidApi) : null;
  window.addEventListener('pywebviewready', () => {
    startApi(window.pywebview?.api);
  }, { once: true });
  if (!startApi(androidApi) && !startApi(window.pywebview?.api)) {
    const bridgePoll = setInterval(() => {
      const candidate = window.AndroidApi
        ? createAndroidApi(window.AndroidApi)
        : window.pywebview?.api;
      if (startApi(candidate)) clearInterval(bridgePoll);
    }, 50);
    setTimeout(() => {
      clearInterval(bridgePoll);
      if (!apiStarted) startApi(createMockApi());
    }, 1800);
  }
})();
