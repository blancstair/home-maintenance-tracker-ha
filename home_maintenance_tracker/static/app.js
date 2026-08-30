const state = {
  data: null,
  page: 'dashboard',
  selectedAsset: null,
  assetView: 'tree',
  maintenanceView: 'agenda',
  calendarDate: new Date(),
  report: 'upcoming',
  reportData: [],
  expanded: new Set(),
  setupStep: 0,
  notifyServices: [],
  meters: [],
  showArchivedMeters: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value = '') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const today = () => new Date().toISOString().slice(0, 10);
const fmtDate = value => value ? new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'}) : 'Not yet';
const fmtMoney = value => value == null ? '—' : new Intl.NumberFormat(undefined, {style:'currency', currency:'USD'}).format(value);
const fmtSize = bytes => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1048576).toFixed(1)} MB`;
const storageGet = key => { try { return localStorage.getItem(key); } catch (_) { return null; } };
const storageSet = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };

function companionNavigateUrl(panelPath, route, id) {
  if (!panelPath) throw new Error('Home Assistant Companion QR labels require the Home Assistant app panel.');
  const separator=panelPath.includes('?')?'&':'?';
  return `homeassistant://navigate${panelPath}${separator}${route}=${encodeURIComponent(id)}&server=default`;
}

async function api(url, options = {}) {
  const init = {...options, headers: {...(options.headers || {})}};
  if (init.body && !(init.body instanceof FormData) && typeof init.body !== 'string') {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(init.body);
  }
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({error: response.statusText}));
    throw new Error(detail.error || 'Request failed');
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
}

function toast(message, type = 'success') {
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = message;
  $('#toastRegion').append(element);
  setTimeout(() => element.remove(), 3800);
}

async function refresh({quiet = false} = {}) {
  try {
    state.data = await api('api/bootstrap');
    $('#version').textContent = `Version ${state.data.version}`;
    $('#loading').classList.add('hidden');
    $('#errorState').classList.add('hidden');
    renderAll();
    if (!state.data.settings.setup_complete && !quiet) startSetup();
  } catch (error) {
    $('#loading').classList.add('hidden');
    $('#errorState').classList.remove('hidden');
    $('#errorMessage').textContent = error.message;
  }
}

function navigate(page) {
  state.page = page;
  $$('.page').forEach(el => el.classList.toggle('active', el.id === `page-${page}`));
  $$('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  const names = {
    dashboard: ['OVERVIEW', 'Dashboard'], assets: ['MATERIAL HISTORY', 'Assets'], maintenance: ['SCHEDULING', 'Maintenance'],
    meters: ['USAGE TRACKING', 'Meter Readings'], reports: ['ANALYSIS', 'Reports'], help: ['REFERENCE', 'Help'], settings: ['APPLICATION', 'Settings']
  };
  $('#pageEyebrow').textContent = names[page][0];
  $('#pageTitle').textContent = names[page][1];
  $('#pageHelp').dataset.help=HELP_SCREEN_MAP[page];
  $('#pageHelp').setAttribute('aria-label',`Help for ${names[page][1]}`);
  $('#pageHelp').title=`Help for ${names[page][1]}`;
  $('#quickAdd').textContent = page === 'maintenance' ? '＋ Add Task' : page === 'meters' ? '＋ Update Readings' : '＋ Add Item';
  if (page === 'assets') renderAssets();
  if (page === 'maintenance') renderMaintenance();
  if (page === 'meters') renderMeters();
  if (page === 'reports') renderReports();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function stateLabel(task) {
  if (task.state === 'red') return '<span class="badge red">ESCALATED</span>';
  if (task.state === 'overdue') return '<span class="badge red">OVERDUE</span>';
  if (task.state === 'snoozed') return '<span class="badge blue">SNOOZED</span>';
  if (task.state === 'upcoming') return '<span class="badge amber">UPCOMING</span>';
  return '<span class="badge green">CURRENT</span>';
}

function taskDueText(task) {
  const bits = [];
  if (task.calendar_due) bits.push(fmtDate(task.calendar_due));
  if (task.meter_due != null) bits.push(`${Number(task.meter_due).toLocaleString()} ${task.meter_definition?.unit || ''}`);
  return bits.join(' / ') || 'Manual trigger';
}

function renderTaskRows(tasks, limit = null) {
  const rows = limit ? tasks.slice(0, limit) : tasks;
  if (!rows.length) return '<div class="empty-state"><span>✓</span><h2>Nothing needs attention</h2><p>No maintenance tasks match this view.</p></div>';
  return `<div class="task-list">${rows.map(task => `
    <div class="task-row" data-state="${task.state}" data-task-id="${task.id}" tabindex="0">
      <span class="state-dot"></span>
      <div><div class="task-title">${task.outcome === 'higher_authority' ? '⇧ ' : ''}${esc(task.title)}</div><div class="subtle">${esc(task.asset_name)}</div></div>
      <div class="task-due"><div>${esc(taskDueText(task))}</div><div>${stateLabel(task)}</div></div>
      <div class="task-actions"><button class="button small primary" data-complete="${task.id}">Complete</button></div>
    </div>`).join('')}</div>`;
}

function renderDashboard() {
  const d = state.data.dashboard;
  $('#page-dashboard').innerHTML = `
    <div class="stats-grid">
      <div class="stat-card red"><small>ESCALATED</small><strong>${d.red}</strong><span class="subtle">Past 1.5× periodicity</span></div>
      <div class="stat-card amber"><small>OVERDUE</small><strong>${d.overdue}</strong><span class="subtle">Includes escalated tasks</span></div>
      <div class="stat-card"><small>IN VIEW</small><strong>${d.upcoming}</strong><span class="subtle">Next ${state.data.settings.dashboard_window_days} days</span></div>
      <div class="stat-card"><small>ACTIVE ITEMS</small><strong>${d.active_assets}</strong><span class="subtle">Across the full hierarchy</span></div>
    </div>
    <div class="dashboard-grid">
      <div class="card"><div class="card-header"><div class="section-title"><h2>Maintenance Requiring Attention</h2>${helpButton('dashboard-attention')}</div><button class="button small ghost" data-go="maintenance">View All →</button></div><div class="card-body flush">${renderTaskRows(d.due_tasks, 10)}</div></div>
      <div class="stack">
        <div class="card"><div class="card-header"><div class="section-title"><h3>Quick Actions</h3>${helpButton('dashboard-quick')}</div></div><div class="card-body toolbar-group">
          <button class="button" data-action="new-asset">＋ Item</button><button class="button" data-action="new-task">＋ Task</button><button class="button" data-action="readings">⌁ Readings</button>
        </div></div>
        <div class="card"><div class="card-header"><div class="section-title"><h3>Recently Completed</h3>${helpButton('dashboard-recent')}</div></div><div class="card-body flush">
          ${d.recent.length ? d.recent.slice(0,6).map(item => `<div class="task-row"><span class="state-dot"></span><div><div class="task-title">${item.outcome === 'higher_authority' ? '⇧ ' : ''}${esc(item.title)}</div><div class="subtle">${esc(item.asset_name || 'General')} · ${fmtDate(item.completion_date)}</div></div><div>${item.outcome === 'skipped' ? '<span class="badge amber">SKIPPED</span>' : '<span class="badge green">DONE</span>'}</div></div>`).join('') : '<div class="empty-state"><p>No completed maintenance yet.</p></div>'}
        </div></div>
        <div class="card"><div class="card-header"><div class="section-title"><h3>Warranty Dates</h3>${helpButton('dashboard-warranty')}</div><button class="button small ghost" data-report="warranties">Report →</button></div><div class="card-body flush">
          ${d.warranties.length ? d.warranties.slice(0,5).map(item => `<div class="task-row" data-asset-id="${item.asset_id}"><span class="state-dot"></span><div><div class="task-title">${esc(item.name)}</div><div class="subtle">Expires ${fmtDate(item.expiration)}</div></div></div>`).join('') : '<div class="empty-state"><p>No warranty dates entered.</p></div>'}
        </div></div>
      </div>
    </div>`;
}

function assetChildren(parentId, includeArchived = false) {
  return state.data.assets.filter(asset => (asset.parent_id || null) === (parentId || null) && (includeArchived || !asset.archived)).sort((a,b) => a.name.localeCompare(b.name));
}

function treeMarkup(parentId = null, filter = '', includeArchived = false) {
  let children = assetChildren(parentId, includeArchived);
  if (filter) {
    const matches = new Set(state.data.assets.filter(a => a.name.toLowerCase().includes(filter)).map(a => a.id));
    const addParents = id => {
      const item = state.data.assets.find(a => a.id === id);
      if (item?.parent_id && !matches.has(item.parent_id)) { matches.add(item.parent_id); addParents(item.parent_id); }
    };
    [...matches].forEach(addParents);
    children = children.filter(a => matches.has(a.id));
  }
  if (!children.length) return '';
  return `<ul class="tree">${children.map(asset => {
    const hasChildren = assetChildren(asset.id, includeArchived).length > 0;
    const expanded = filter || state.expanded.has(asset.id);
    return `<li data-tree-id="${asset.id}">
      <div class="tree-node-row ${state.selectedAsset === asset.id ? 'selected' : ''}" draggable="true" data-drag-id="${asset.id}" data-drop-id="${asset.id}">
        <button class="tree-toggle" data-toggle-node="${asset.id}">${hasChildren ? (expanded ? '▾' : '▸') : '·'}</button>
        <button class="tree-label ${asset.archived ? 'archived' : ''}" data-select-asset="${asset.id}">${esc(asset.name)}</button>
      </div>
      ${hasChildren && expanded ? treeMarkup(asset.id, filter, includeArchived) : ''}
    </li>`;
  }).join('')}</ul>`;
}

function renderAssets() {
  const search = $('#assetSearch')?.value || '';
  const archived = $('#showArchived')?.checked || false;
  const page = $('#page-assets');
  page.innerHTML = `
    <div class="toolbar">
      <div class="segmented"><button class="${state.assetView==='tree'?'active':''}" data-asset-view="tree">Tree & cards</button><button class="${state.assetView==='table'?'active':''}" data-asset-view="table">Dense table</button></div>
      <button class="button primary" data-action="new-asset">＋ Add item</button>
    </div>
    ${state.assetView === 'table' ? renderAssetTable(archived) : `<div class="asset-workspace ${state.selectedAsset ? 'detail-open' : ''}">
      <section class="asset-browser">
        <div class="search-wrap"><div class="search-input"><span>⌕</span><input id="assetSearch" placeholder="Search the hierarchy" value="${esc(search)}"></div><label class="check-row" style="margin-top:10px"><input type="checkbox" id="showArchived" ${archived?'checked':''}> Show archived items</label></div>
        <div class="tree-scroll">${treeMarkup(null, search.toLowerCase(), archived) || '<div class="empty-state"><p>No items found.</p></div>'}</div>
      </section>
      <section class="asset-detail" id="assetDetail">${state.selectedAsset ? '<div class="loading"><span></span></div>' : '<div class="empty-state"><span>◇</span><h2>Select an item</h2><p>Choose an item in the tree to view its fields, history, tasks, documents, and meters.</p></div>'}</section>
    </div>`}`;
  if (state.selectedAsset && state.assetView === 'tree') loadAssetDetail(state.selectedAsset);
}

function renderAssetTable(includeArchived) {
  const assets = state.data.assets.filter(asset => includeArchived || !asset.archived);
  const parentName = id => state.data.assets.find(a => a.id === id)?.name || '—';
  return `<div class="toolbar"><label class="check-row"><input type="checkbox" id="showArchived" ${includeArchived?'checked':''}> Show archived</label><div class="search-input"><span>⌕</span><input id="assetTableSearch" placeholder="Filter records"></div></div>
  <div class="dense-table-wrap"><table><thead><tr><th>Name</th><th>Parent</th><th>Category</th><th>Manufacturer</th><th>Model</th><th>Serial</th><th>Part</th><th>Lot</th><th>Status</th></tr></thead><tbody>
    ${assets.map(a => `<tr data-asset-id="${a.id}"><td><strong>${esc(a.name)}</strong></td><td>${esc(parentName(a.parent_id))}</td><td>${esc(a.attributes.category || '')}</td><td>${esc(a.attributes.manufacturer || '')}</td><td>${esc(a.attributes.model || '')}</td><td>${esc(a.attributes.serial || '')}</td><td>${esc(a.attributes.part_number || '')}</td><td>${esc(a.attributes.lot_number || '')}</td><td>${a.archived?'<span class="badge">ARCHIVED</span>':'<span class="badge green">ACTIVE</span>'}</td></tr>`).join('')}
  </tbody></table></div>`;
}

async function loadAssetDetail(assetId) {
  try {
    const asset = await api(`api/assets/${assetId}`);
    if (state.selectedAsset !== assetId || !$('#assetDetail')) return;
    const fields = state.data.standard_fields.filter(field => asset.attributes[field.key]);
    $('#assetDetail').innerHTML = `
      <div class="asset-detail-header">
        <div><button class="button small ghost no-print" data-back-assets>← Tree</button><p class="eyebrow">${esc(asset.attributes.category || 'ITEM RECORD')}</p><h2>${esc(asset.name)}</h2>
          <div>${asset.archived ? '<span class="badge">ARCHIVED</span>' : '<span class="badge green">ACTIVE</span>'} ${asset.replaced_by ? `<span class="badge blue">Replaced by ${esc(asset.replaced_by.name)}</span>` : ''} ${asset.replaced_from ? `<span class="badge blue">Replaced ${esc(asset.replaced_from.name)}</span>` : ''}</div></div>
        <div class="toolbar-group no-print"><button class="button small" data-qr="${asset.id}">QR label</button><button class="button small" data-edit-asset="${asset.id}">Edit</button><button class="button small" data-more-asset="${asset.id}">Actions</button></div>
      </div>
      <div class="detail-body">
        ${fields.length ? `<dl class="detail-grid">${fields.map(field => `<div class="field"><dt>${esc(field.label)}</dt><dd>${esc(asset.attributes[field.key])}</dd></div>`).join('')}</dl>` : '<p class="subtle">No optional fields have been selected for this item.</p>'}
        <div class="section-heading"><div class="section-title"><h3>Maintenance</h3>${helpButton('maintenance-task')}</div><button class="button small" data-new-task-asset="${asset.id}">＋ Task</button></div>
        ${renderTaskRows(asset.tasks)}
        <div class="section-heading"><div class="section-title"><h3>Material History</h3>${helpButton('remarks')}</div><button class="button small" data-new-remark="${asset.id}">＋ Remark</button></div>
        ${asset.remarks.length ? `<div class="timeline">${asset.remarks.map(r => `<div class="timeline-item"><div><span class="badge ${r.category==='corrective'?'red':r.category==='preventive'?'green':'blue'}">${esc(r.category.toUpperCase())}</span> <span class="subtle">Work: ${fmtDate(r.work_date)} · Entered ${new Date(r.entry_timestamp).toLocaleString()}</span></div><p>${esc(r.text)}</p>${r.attachments?.length?`<div class="toolbar-group">${r.attachments.map(a=>`<a class="badge blue" href="api/attachments/${a.id}" target="_blank">${esc(a.original_name)}</a>`).join('')}</div>`:''}<div class="toolbar-group no-print"><button class="button small ghost" data-edit-remark="${r.id}" data-asset="${asset.id}">Edit</button><button class="button small ghost" data-upload-owner="remark" data-owner-id="${r.id}">Attach file</button><button class="button small ghost" data-delete-remark="${r.id}" data-asset="${asset.id}">Delete</button></div></div>`).join('')}</div>` : '<p class="subtle">No history entries yet.</p>'}
        <div class="section-heading"><div class="section-title"><h3>Documents & Attachments</h3>${helpButton('attachments')}</div><button class="button small" data-upload-owner="asset" data-owner-id="${asset.id}">＋ Upload</button></div>
        ${asset.attachments.length ? `<div class="attachments">${asset.attachments.map(a => `<div class="attachment"><span class="badge">${esc(a.category.replace('_',' '))}</span><a href="api/attachments/${a.id}" target="_blank">${esc(a.original_name)}</a><span class="subtle">${fmtSize(a.size_bytes)}</span><button class="button small ghost" data-delete-attachment="${a.id}">Delete</button></div>`).join('')}</div>` : '<p class="subtle">No attachments yet.</p>'}
        <div class="section-heading"><div class="section-title"><h3>Meters</h3>${helpButton('meters-manage')}</div><button class="button small" data-new-meter="${asset.id}">＋ Meter</button></div>
        ${asset.meters.length ? `<div class="dense-table-wrap"><table><thead><tr><th>Meter</th><th>Current</th><th>Recorded</th><th>Actions</th></tr></thead><tbody>${asset.meters.map(m => `<tr class="${m.archived?'archived':''}"><td><strong>${esc(m.name)}</strong> ${m.archived?'<span class="badge">ARCHIVED</span>':''}</td><td>${m.readings[0] ? `${Number(m.readings[0].reading).toLocaleString()} ${esc(m.unit)}` : 'No Reading'}</td><td>${m.readings[0] ? new Date(m.readings[0].recorded_at).toLocaleString() : '—'}</td><td><div class="toolbar-group">${m.archived?`<button class="button small" data-restore-meter="${m.id}">Restore</button>`:`<button class="button small" data-update-meter="${m.id}">Update</button><button class="button small" data-meter-qr="${m.id}">QR</button><button class="button small" data-edit-meter="${m.id}">Edit</button><button class="button small ghost" data-manage-meter="${m.id}">Manage</button>`}</div></td></tr>`).join('')}</tbody></table></div>` : '<p class="subtle">No Meters Configured.</p>'}
      </div>`;
  } catch (error) { toast(error.message, 'error'); }
}

function renderMaintenance() {
  const order = {red:0, overdue:1, upcoming:2, snoozed:3, normal:4};
  const tasks = [...state.data.tasks].sort((a,b) => order[a.state] - order[b.state] || a.title.localeCompare(b.title));
  $('#page-maintenance').innerHTML = `
    <div class="toolbar"><div class="toolbar-group"><div class="segmented"><button data-maint-view="agenda" class="${state.maintenanceView==='agenda'?'active':''}">Agenda</button><button data-maint-view="calendar" class="${state.maintenanceView==='calendar'?'active':''}">Month</button><button data-maint-view="table" class="${state.maintenanceView==='table'?'active':''}">Dense Table</button></div>${helpButton('maintenance-views')}</div><button class="button primary" data-action="new-task">＋ Add Task</button></div>
    ${state.maintenanceView === 'agenda' ? `<div class="card"><div class="card-body flush">${renderTaskRows(tasks)}</div></div>` : state.maintenanceView === 'calendar' ? renderCalendar(tasks) : renderTaskTable(tasks)}`;
}

function renderTaskTable(tasks) {
  return `<div class="dense-table-wrap"><table><thead><tr><th>State</th><th>Task</th><th>Item</th><th>Schedule</th><th>Due</th><th>Red threshold</th><th>Last completed</th><th>Forecast</th></tr></thead><tbody>${tasks.map(t => `<tr data-task-id="${t.id}"><td>${stateLabel(t)}</td><td><strong>${esc(t.title)}</strong></td><td>${esc(t.asset_name)}</td><td>${esc(scheduleSummary(t))}</td><td>${esc(taskDueText(t))}</td><td>${esc(t.calendar_red ? fmtDate(t.calendar_red) : t.meter_red != null ? `${t.meter_red} ${t.meter_definition?.unit||''}` : '—')}</td><td>${fmtDate(t.last_completed_date)}</td><td>${t.meter_forecast?.estimated_date ? fmtDate(t.meter_forecast.estimated_date) : '—'}</td></tr>`).join('')}</tbody></table></div>`;
}

function renderCalendar(tasks) {
  const cursor = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth(), 1);
  const year = cursor.getFullYear(), month = cursor.getMonth();
  const first = new Date(year, month, 1 - cursor.getDay());
  const days = Array.from({length:42}, (_,i) => new Date(first.getFullYear(), first.getMonth(), first.getDate()+i));
  const dateKey = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  return `<div class="toolbar"><div class="toolbar-group"><button class="button small" data-cal-nav="-1">←</button><strong>${cursor.toLocaleDateString(undefined,{month:'long',year:'numeric'})}</strong><button class="button small" data-cal-nav="1">→</button></div></div>
  <div class="calendar">${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="calendar-head">${d}</div>`).join('')}${days.map(d => {
    const key=dateKey(d), events=tasks.filter(t=>t.calendar_due===key || t.meter_forecast?.estimated_date===key);
    return `<div class="calendar-day ${d.getMonth()!==month?'outside':''}"><span class="calendar-date">${d.getDate()}</span>${events.map(t=>`<button class="calendar-event ${['red','overdue'].includes(t.state)?'red':''}" data-task-id="${t.id}">${esc(t.title)}</button>`).join('')}</div>`;
  }).join('')}</div>`;
}

function scheduleSummary(task) {
  const calendar = task.calendar_value ? `Every ${task.calendar_value} ${task.calendar_unit}` : '';
  const meter = task.meter_interval ? `Every ${Number(task.meter_interval).toLocaleString()} ${task.meter_definition?.unit || ''}` : '';
  if (task.schedule_type === 'combined') return `${calendar} / ${meter} (${task.combination_rule})`;
  if (task.schedule_type === 'meter') return meter;
  if (task.schedule_type === 'one_time') return 'One-time';
  if (task.schedule_type === 'condition') return 'Manual condition';
  return calendar;
}

function renderMeters() {
  $('#page-meters').innerHTML = `<div class="toolbar"><div><p class="subtle">Enter only the meters you checked. Running totals cannot move backward.</p><label class="check-row"><input type="checkbox" id="showArchivedMeters" ${state.showArchivedMeters?'checked':''}> Show Archived Meters</label></div><div class="toolbar-group"><button class="button" data-new-meter-page>＋ New Meter</button><button class="button primary" data-action="readings">＋ Update Readings</button>${helpButton('meters-update')}</div></div><div id="meterTable" class="loading"><span></span></div>`;
  api(`api/meters${state.showArchivedMeters?'?include_archived=1':''}`).then(meters => {
    state.meters=meters;
    $('#meterTable').className='dense-table-wrap';
    $('#meterTable').innerHTML=meters.length?`<table><thead><tr><th>Item</th><th>Meter</th><th>Type</th><th>Current Reading</th><th>Recorded</th><th>Actions</th></tr></thead><tbody>${meters.map(m=>`<tr class="${m.archived?'archived':''}"><td>${esc(m.asset_name)}</td><td><strong>${esc(m.name)}</strong> ${m.archived?'<span class="badge">ARCHIVED</span>':''}</td><td>${esc(m.kind)} · ${esc(m.unit)}</td><td>${m.latest?`${Number(m.latest.reading).toLocaleString()} ${esc(m.unit)}`:'—'}</td><td>${m.latest?new Date(m.latest.recorded_at).toLocaleString():'—'}</td><td><div class="toolbar-group">${m.archived?`<button class="button small" data-restore-meter="${m.id}">Restore</button>`:`<button class="button small primary" data-update-meter="${m.id}">Update</button><button class="button small" data-meter-qr="${m.id}">QR</button><button class="button small" data-edit-meter="${m.id}">Edit</button><button class="button small ghost" data-manage-meter="${m.id}">Manage</button>`}</div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state"><span>⌁</span><h2>No Meters Configured</h2><p>Create a meter here or from an item record.</p><button class="button primary" data-new-meter-page>＋ New Meter</button></div>';
  }).catch(e=>toast(e.message,'error'));
}

const reportNames = {
  upcoming:'Upcoming maintenance', overdue:'Overdue maintenance', history:'Complete service history', hierarchy:'Material hierarchy', archived:'Archived/replaced items', warranties:'Warranty expiration', costs:'Maintenance cost', parts:'Parts and materials used', meters:'Meter-reading history'
};

function renderReports() {
  $('#page-reports').innerHTML = `<div class="toolbar no-print"><div class="toolbar-group"><select id="reportSelect">${Object.entries(reportNames).map(([k,v])=>`<option value="${k}" ${state.report===k?'selected':''}>${v}</option>`).join('')}</select><button class="button" id="runReport">Run report</button></div><button class="button" onclick="window.print()">Print / Save PDF</button></div><div id="reportOutput" class="card"><div class="empty-state"><span>▤</span><h2>Choose a report</h2><p>Reports are formatted for screen review and clean PDF printing.</p></div></div>`;
  runReport(state.report);
}

async function runReport(name) {
  state.report=name;
  $('#reportOutput').innerHTML='<div class="loading"><span></span></div>';
  try {
    if (name === 'hierarchy') {
      $('#reportOutput').innerHTML=`<div class="card-header"><h2>${reportNames[name]}</h2><span class="subtle">Generated ${new Date().toLocaleString()}</span></div><div class="card-body">${treeMarkup(null,'',true)}</div>`;
      return;
    }
    const data=await api(`api/reports/${name}`);
    const columns = reportColumns(name);
    $('#reportOutput').innerHTML=`<div class="card-header"><h2>${reportNames[name]}</h2><span class="subtle">${data.length} records · ${new Date().toLocaleString()}</span></div><div class="card-body flush"><div class="dense-table-wrap" style="border:0;border-radius:0"><table><thead><tr>${columns.map(c=>`<th>${c.label}</th>`).join('')}</tr></thead><tbody>${data.map(row=>`<tr>${columns.map(c=>`<td class="${c.wrap?'wrap':''}">${c.render?c.render(row):esc(row[c.key]??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  } catch(e) { $('#reportOutput').innerHTML=`<div class="empty-state"><h2>Report unavailable</h2><p>${esc(e.message)}</p></div>`; }
}

function reportColumns(name) {
  if (['upcoming','overdue'].includes(name)) return [
    {label:'State',render:r=>stateLabel(r)},{label:'Task',key:'title'},{label:'Item',key:'asset_name'},{label:'Due',render:r=>esc(taskDueText(r))},{label:'Schedule',render:r=>esc(scheduleSummary(r))}
  ];
  if (name==='history') return [{label:'Date',render:r=>fmtDate(r.completion_date)},{label:'Task',key:'title'},{label:'Item',key:'asset_name'},{label:'Outcome',render:r=>r.outcome==='higher_authority'?'⇧ Higher authority':esc(r.outcome)},{label:'Remark',key:'remark_text',wrap:true},{label:'Cost',render:r=>fmtMoney(r.total_cost)}];
  if (name==='archived') return [{label:'Item',key:'name'},{label:'Archived',render:r=>fmtDate(r.archived_at)},{label:'Replacement',render:r=>r.replaced_by_id?'Linked':'—'}];
  if (name==='warranties') return [{label:'Item',key:'name'},{label:'Manufacturer',render:r=>esc(r.attributes.manufacturer||'—')},{label:'Model',render:r=>esc(r.attributes.model||'—')},{label:'Expiration',render:r=>fmtDate(r.attributes.warranty_expiration)}];
  if (name==='costs') return [{label:'Date',render:r=>fmtDate(r.completion_date)},{label:'Item',key:'asset_name'},{label:'Task',key:'title'},{label:'Cost',render:r=>fmtMoney(r.total_cost)},{label:'Labor',render:r=>r.labor_minutes?`${r.labor_minutes} min`:'—'}];
  if (name==='parts') return [{label:'Date',render:r=>fmtDate(r.completion_date)},{label:'Item',key:'asset_name'},{label:'Task',key:'title'},{label:'Material',key:'description'},{label:'Quantity',key:'quantity'},{label:'Cost',render:r=>fmtMoney(r.cost)}];
  return [{label:'Date',render:r=>new Date(r.recorded_at).toLocaleString()},{label:'Item',key:'asset_name'},{label:'Meter',key:'meter_name'},{label:'Reading',render:r=>`${Number(r.reading).toLocaleString()} ${esc(r.unit)}`},{label:'Note',key:'note',wrap:true}];
}

function renderHelp() {
  $('#page-help').innerHTML = `<div class="help-layout">
    <nav class="help-toc"><a href="#help-start">Getting started</a><a href="#help-assets">Material history</a><a href="#help-maint">Maintenance</a><a href="#help-meters">Meters</a><a href="#help-replace">Replacement</a><a href="#help-files">Attachments</a><a href="#help-alerts">Alerts</a><a href="#help-reports">Reports</a><a href="#help-backup">Backup & transfer</a><a href="#help-mobile">Mobile & QR</a></nav>
    <article class="help-content">
      <section class="help-section" id="help-start"><p class="eyebrow">ORIENTATION</p><h2>Getting started</h2><p>The tracker combines a modern action dashboard with a dense, searchable material-history database. The supplied fictional records are safe to explore and can be removed from Settings without touching records you create.</p><ol class="steps"><li>Open <strong>Assets</strong> and explore the sample hierarchy.</li><li>Create the real top-level items you want to track.</li><li>Add meters only where usage-based maintenance matters.</li><li>Create recurring tasks and attach their instructions or manuals.</li><li>Remove the sample data when you are comfortable.</li></ol><div class="callout"><strong>Nothing requires the internet.</strong> Core records, attachments, schedules, and reports remain on your Home Assistant system. Nabu Casa provides convenient authenticated remote access.</div></section>
      <section class="help-section" id="help-assets"><p class="eyebrow">ASSET TREE</p><h2>Material history and hierarchy</h2><p>Every item has zero or one parent and may have any number of children. Nesting is unlimited: a property can contain a room, which contains an appliance, which contains a pump, which contains a replaceable seal.</p><h3>Moving an item</h3><p>Drag an item onto its new parent. The program prevents circular relationships and records a lifecycle remark. An item’s remarks, documents, meters, and maintenance history stay with it.</p><h3>Optional standardized fields</h3><p>Use <strong>Add field</strong> while editing. Only selected fields appear on the card, but their order remains consistent: category, manufacturer, model, serial, part, lot, tag, location, dates, vendor, and warranty.</p><div class="callout warning"><strong>Archive first.</strong> Archiving is reversible and is the normal choice. Permanent deletion is intended for property you will never need to reference again.</div></section>
      <section class="help-section" id="help-maint"><p class="eyebrow">WORKFLOW</p><h2>Maintenance scheduling and completion</h2><p>Tasks can be general or tied to one exact item. Supported bases are one-time date, calendar interval, runtime, mileage, cycles, quantities, seasonal or specific patterns, condition/manual trigger, and calendar-plus-meter combinations.</p><h3>Completion draft</h3><p>Choose <strong>Complete</strong>. The application prepares a remark. Review or rewrite it, enter optional labor, cost, meter reading, and materials, then select <strong>Approve & complete</strong>. The approved text becomes the item’s material-history remark.</p><h3>Higher authority</h3><p>The <strong>⇧ Completed by higher authority</strong> outcome is used when replacement or corrective work satisfies an ordinary maintenance requirement. It links the corrective/replacement item and resets the task’s periodicity exactly like an ordinary completion.</p><h3>Skipped maintenance</h3><p>A skip requires a reason. You decide whether the skipped occurrence advances the schedule. The choice is recorded with the completion.</p></section>
      <section class="help-section" id="help-meters"><p class="eyebrow">RUNNING TOTALS</p><h2>Mileage, runtime, cycles, and quantities</h2><p>Use the update screen to enter only the readings you checked. Readings are timestamped and retained. Because the tracker maintains a lifetime running total, a new reading cannot be lower than the most recent reading.</p><p>With two or more readings, the dashboard calculates an average usage rate, remaining usage, and projected due date. Maintenance still becomes due from the actual meter threshold—not merely the forecast.</p></section>
      <section class="help-section" id="help-replace"><p class="eyebrow">LIFECYCLE</p><h2>Replacing and archiving items</h2><p>The guided replacement workflow creates the replacement in the same location, links both records, lets you transfer selected children, and lets you copy selected maintenance plans. The old item is archived with its history intact.</p><p>When archiving a parent, every active direct child must be either archived or moved. Choosing archive includes that child’s descendants; choosing move requires a valid active destination.</p></section>
      <section class="help-section" id="help-files"><p class="eyebrow">MANAGED STORAGE</p><h2>Manuals and attachments</h2><p>Upload manuals, receipts, warranties, diagrams, photographs, videos, service records, or other files. Each file belongs to one exact item, remark, task, or completion. Files are copied into managed storage, so moving the original does not break the record.</p><div class="callout warning"><strong>Watch video size.</strong> Large videos increase Home Assistant backup size. With ample disk space this is workable, but off-site backup limits may still apply.</div></section>
      <section class="help-section" id="help-alerts"><p class="eyebrow">ESCALATION</p><h2>Due, overdue, and red alerts</h2><p>A task is due at its normal interval. It becomes red at 1.5 times the interval measured from the last completion or completion meter reading. Snoozing hides ordinary reminders only; it never conceals the red state.</p><ul><li>Intervals through one week repeat daily.</li><li>More than one week through three months repeat weekly.</li><li>More than three through nine months repeat every 14 days.</li><li>Longer intervals repeat monthly.</li></ul><p>Meter tasks use projected calendar interval when sufficient usage history exists and weekly reminders otherwise.</p></section>
      <section class="help-section" id="help-reports"><p class="eyebrow">OUTPUT</p><h2>Reports and PDF export</h2><p>Open Reports, choose a report, and select <strong>Print / Save PDF</strong>. The print layout removes navigation and controls. Available reports cover upcoming and overdue maintenance, complete service history, hierarchy, archives/replacements, warranties, cost, materials used, and meter readings.</p></section>
      <section class="help-section" id="help-backup"><p class="eyebrow">RECOVERY</p><h2>Home Assistant backups and manual transfer</h2><p>Home Assistant backups protect the app alongside the rest of your system. The manual export produces a portable ZIP containing the SQLite database, attachments, and a manifest. Use it to migrate just this tracker or retrieve its records without restoring all of Home Assistant.</p><ol class="steps"><li>Open Settings and select <strong>Download full export</strong>.</li><li>Keep the ZIP somewhere outside the Home Assistant machine.</li><li>To restore, select the ZIP under Manual import.</li><li>Confirm the warning and wait for the reload message.</li></ol><div class="callout warning"><strong>Import replaces current tracker data.</strong> Export the current data first if you may need to return to it.</div></section>
      <section class="help-section" id="help-mobile"><p class="eyebrow">ACCESS</p><h2>Mobile access and QR labels</h2><p>Open the tracker from the Home Assistant sidebar in a browser or the Companion app. Nabu Casa uses the same Home Assistant sign-in. A QR label contains the exact item route from the Home Assistant address used when the label was generated. Scan it with a signed-in phone to open that item directly.</p></section>
    </article>
  </div>`;
}

function renderHelpMaster(filter='') {
  const query=filter.trim().toLowerCase();
  const entries=Object.entries(HELP_ENTRIES).filter(([,entry])=>!query || `${entry.title} ${entry.group} ${entry.html}`.toLowerCase().includes(query));
  const groups=[...new Set(entries.map(([,entry])=>entry.group))];
  $('#page-help').innerHTML=`<div class="help-search"><div class="search-input"><span>⌕</span><input id="helpSearch" placeholder="Search Help" value="${esc(filter)}"></div></div><div class="help-layout">
    <nav class="help-toc">${groups.map(group=>`<a href="#help-group-${group.replace(/\W+/g,'-').toLowerCase()}">${esc(group)}</a>`).join('')}</nav>
    <article class="help-content">${entries.length?groups.map(group=>`<section class="help-section" id="help-group-${group.replace(/\W+/g,'-').toLowerCase()}"><p class="eyebrow">${esc(group.toUpperCase())}</p><h2>${esc(group)}</h2>${entries.filter(([,entry])=>entry.group===group).map(([id,entry])=>`<div id="help-${id}"><h3>${esc(entry.title)}</h3>${entry.html}</div>`).join('')}</section>`).join(''):'<div class="empty-state"><h2>No Help Entries Found</h2><p>Try a different search term.</p></div>'}</article>
  </div>`;
}

function openContextHelp(id) {
  const entry=HELP_ENTRIES[id];
  if(!entry){toast('This Help entry is unavailable.','error');return;}
  $('#contextHelpTitle').textContent=entry.title;
  $('#contextHelpBody').innerHTML=entry.html;
  $('#helpDialog').showModal();
}

function verifyHelpCoverage() {
  const missing=$$('[data-help]').map(button=>button.dataset.help).filter(id=>!HELP_ENTRIES[id]);
  if(missing.length) console.error('Missing Help entries:',[...new Set(missing)]);
}

function renderSettings() {
  const s=state.data.settings;
  $('#page-settings').innerHTML=`<div class="settings-grid">
    <section class="setting-card"><div class="section-title"><h2>Dashboard Window</h2>${helpButton('settings-window')}</div><p>Choose how far ahead the overview looks.</p><label>Days<input id="settingWindow" type="number" min="1" max="365" value="${s.dashboard_window_days}"></label><button class="button" style="margin-top:12px" id="saveWindow">Save</button></section>
    <section class="setting-card"><div class="section-title"><h2>Notifications</h2>${helpButton('settings-notifications')}</div><p>Choose Home Assistant Companion devices and the daily check hour.</p><button class="button" id="configureNotifications">Configure Devices</button></section>
    <section class="setting-card"><div class="section-title"><h2>Manual Export</h2>${helpButton('settings-export')}</div><p>Download the database and every managed attachment as one portable ZIP.</p><a class="button" href="api/export" style="display:inline-block;text-decoration:none">Download Full Export</a></section>
    <section class="setting-card"><div class="section-title"><h2>Manual Import</h2>${helpButton('settings-import')}</div><p>Replace current tracker data with a previously exported ZIP.</p><input id="importFile" type="file" accept=".zip"><button class="button danger" style="margin-top:12px" id="importData">Import and Replace</button></section>
    <section class="setting-card full"><div class="section-title"><h2>Fictional Sample Data</h2>${helpButton('settings-sample')}</div><p>${s.sample_data_installed ? 'The sample property, equipment, tasks, meters, and history are installed. Removing them does not affect records you created.' : 'The sample dataset has been removed. You may reinstall it for training at any time.'}</p><button class="button ${s.sample_data_installed?'danger':''}" id="toggleSample">${s.sample_data_installed?'Remove Sample Data':'Reinstall Sample Data'}</button></section>
    <section class="setting-card full"><div class="section-title"><h2>About</h2>${helpButton('backup-home-assistant')}</div><p>Home Maintenance Tracker ${state.data.version}. Local data is stored in SQLite with managed attachment storage. Routine protection is provided through Home Assistant backups.</p><button class="button" data-page="help">Open Complete Help</button></section>
  </div>`;
}

function renderAll() {
  renderDashboard(); renderAssets(); renderMaintenance(); renderMeters(); renderReports(); renderHelpMaster(); renderSettings();
  applyTheme(storageGet('hmt-theme') || state.data.settings.theme || 'system');
  verifyHelpCoverage();
}

function openModal({title, eyebrow='DETAILS', body, submit='Save', onSubmit, danger=false, wide=false, helpId=null}) {
  helpId=helpId||({
    'MATERIAL HISTORY':'asset-record','SCHEDULING':'maintenance-task','MAINTENANCE TASK':'maintenance-task',
    'COMPLETION RECORD':'maintenance-completion','REVIEW & APPROVE':'maintenance-completion','TEMPORARY REMINDER':'maintenance-snooze',
    'MANAGED STORAGE':'attachments','ITEM LIFECYCLE':'asset-lifecycle','HIERARCHY':'asset-hierarchy',
    'RECORD RETENTION':'asset-lifecycle','GUIDED REPLACEMENT':'asset-lifecycle','DESTRUCTIVE ACTION':'asset-lifecycle',
    'PRINTABLE LABEL':'asset-qr','HOME ASSISTANT':'settings-notifications'
  }[eyebrow]||'screen-help');
  $('#modalTitle').textContent=title; $('#modalEyebrow').textContent=eyebrow; $('#modalBody').innerHTML=body;
  $('#modalSubmit').textContent=submit; $('#modalSubmit').className=`button ${danger?'danger':'primary'}`;
  $('#modal').classList.toggle('wide',wide); $('#modalSubmit').onclick=async()=>{ try { $('#modalSubmit').disabled=true; await onSubmit?.(); } catch(e){toast(e.message,'error');} finally{$('#modalSubmit').disabled=false;} };
  $('#modalHelp').classList.toggle('hidden',!helpId); $('#modalHelp').dataset.help=helpId||'';
  $('#modal').showModal();
}
function closeModal(){ $('#modal').close(); }

function assetOptions({exclude=null, includeRoot=true}={}) {
  const options=state.data.assets.filter(a=>!a.archived && a.id!==exclude).sort((a,b)=>a.name.localeCompare(b.name)).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('');
  return `${includeRoot?'<option value="">Top level</option>':''}${options}`;
}

function openAssetForm(asset=null, parentId=null) {
  const attrs=asset?.attributes||{};
  const selected=new Set(Object.keys(attrs));
  const fieldRows=()=>state.data.standard_fields.filter(f=>selected.has(f.key)).map(f=>`<label data-field-row="${f.key}">${esc(f.label)}<div class="toolbar-group"><input name="field_${f.key}" value="${esc(attrs[f.key]||'')}"><button type="button" class="button small ghost" data-remove-field="${f.key}">×</button></div></label>`).join('');
  openModal({title:asset?'Edit item':'Add item',eyebrow:'MATERIAL HISTORY',body:`<div class="form-grid"><label class="full">Item name<input name="name" value="${esc(asset?.name||'')}" required autofocus></label>${asset?'':`<label class="full">Parent<select name="parent_id">${assetOptions()}</select></label>`}<div class="full" id="assetFields">${fieldRows()}</div><label class="full">Add a standardized field<select id="addAssetField"><option value="">Choose a field…</option>${state.data.standard_fields.filter(f=>!selected.has(f.key)).map(f=>`<option value="${f.key}">${esc(f.label)}</option>`).join('')}</select></label></div>`,submit:asset?'Save changes':'Create item',onSubmit:async()=>{
    const form=$('#modalForm'), name=form.elements.name.value.trim(); if(!name) throw new Error('Item name is required.');
    const attributes={}; state.data.standard_fields.forEach(f=>{const input=form.elements[`field_${f.key}`]; if(input?.value.trim())attributes[f.key]=input.value.trim();});
    const body={name,attributes}; if(!asset)body.parent_id=form.elements.parent_id.value||parentId||null;
    const saved=await api(asset?`api/assets/${asset.id}`:'api/assets',{method:asset?'PUT':'POST',body}); closeModal(); await refresh({quiet:true}); state.selectedAsset=saved.id; navigate('assets'); toast(asset?'Item updated.':'Item created.');
  }});
  if (!asset && parentId) $('#modalForm').elements.parent_id.value=parentId;
  $('#addAssetField').addEventListener('change',e=>{
    const key=e.target.value;if(!key)return;
    const field=state.data.standard_fields.find(item=>item.key===key);selected.add(key);
    $('#assetFields').insertAdjacentHTML('beforeend',`<label data-field-row="${key}">${esc(field.label)}<div class="toolbar-group"><input name="field_${key}"><button type="button" class="button small ghost" data-remove-field="${key}">×</button></div></label>`);
    e.target.querySelector(`option[value="${key}"]`).remove();e.target.value='';
  });
  $('#modalBody').addEventListener('click',e=>{
    const key=e.target.dataset.removeField;if(!key)return;
    const field=state.data.standard_fields.find(item=>item.key===key);selected.delete(key);e.target.closest('[data-field-row]').remove();
    $('#addAssetField').insertAdjacentHTML('beforeend',`<option value="${key}">${esc(field.label)}</option>`);
  });
}

function scheduleFields(type, task={}) {
  const calendar=['calendar','combined','seasonal','pattern'].includes(type);
  const meter=['meter','combined'].includes(type);
  const meters=state.data.assets.flatMap(a=>[]); // populated asynchronously by selected asset in the task form
  return `<div id="calendarFields" class="form-grid full ${calendar?'':'hidden'}"><label>Interval<input name="calendar_value" type="number" min="0.1" step="0.1" value="${task.calendar_value||''}"></label><label>Unit<select name="calendar_unit">${['days','weeks','months','years'].map(v=>`<option value="${v}" ${task.calendar_unit===v?'selected':''}>${v}</option>`).join('')}</select></label>${['seasonal','pattern'].includes(type)?`<label>Fixed month<input name="fixed_month" type="number" min="1" max="12" value="${task.fixed_month||''}"></label><label>Fixed day<input name="fixed_day" type="number" min="1" max="31" value="${task.fixed_day||''}"></label>`:''}</div><div id="meterFields" class="form-grid full ${meter?'':'hidden'}"><label>Meter<select name="meter_id" id="taskMeter"><option value="">Choose item first…</option></select></label><label>Interval<input name="meter_interval" type="number" min="0.01" step="0.01" value="${task.meter_interval||''}"></label>${type==='combined'?`<label class="full">Combined rule<select name="combination_rule"><option value="first" ${task.combination_rule!=='last'?'selected':''}>Whichever comes first</option><option value="last" ${task.combination_rule==='last'?'selected':''}>Whichever comes last</option></select></label>`:''}</div>`;
}

async function openTaskForm(task=null, assetId=null) {
  const initialType=task?.schedule_type||'calendar';
  openModal({title:task?'Edit maintenance task':'Add maintenance task',eyebrow:'SCHEDULING',body:`<div class="form-grid"><label class="full">Task title<input name="title" value="${esc(task?.title||'')}" autofocus></label><label class="full">Item (optional)<select name="asset_id" id="taskAsset"><option value="">General / unassigned</option>${assetOptions({includeRoot:false})}</select></label><label class="full">Description<textarea name="description">${esc(task?.description||'')}</textarea></label><label class="full">Schedule basis<select name="schedule_type" id="scheduleType">${[['one_time','One-time date'],['calendar','Calendar interval'],['meter','Runtime / mileage / cycles / quantity'],['combined','Calendar and meter'],['seasonal','Seasonal schedule'],['pattern','Specific calendar pattern'],['condition','Condition / manual trigger']].map(([v,l])=>`<option value="${v}" ${initialType===v?'selected':''}>${l}</option>`).join('')}</select></label><div id="dynamicSchedule" class="full">${scheduleFields(initialType,task||{})}</div><label>Start / due date<input type="date" name="start_date" value="${task?.start_date||today()}"></label><label>Estimated duration (minutes)<input type="number" min="0" name="estimated_minutes" value="${task?.estimated_minutes||''}"></label><label>Planned cost<input type="number" min="0" step="0.01" name="planned_cost" value="${task?.planned_cost||''}"></label></div>`,submit:task?'Save task':'Create task',onSubmit:async()=>{
    const f=$('#modalForm').elements; const body={title:f.title.value,asset_id:f.asset_id.value||null,description:f.description.value,schedule_type:f.schedule_type.value,start_date:f.start_date.value,estimated_minutes:f.estimated_minutes.value,planned_cost:f.planned_cost.value,calendar_value:f.calendar_value?.value||null,calendar_unit:f.calendar_unit?.value||null,meter_id:f.meter_id?.value||null,meter_interval:f.meter_interval?.value||null,combination_rule:f.combination_rule?.value||null,fixed_month:f.fixed_month?.value||null,fixed_day:f.fixed_day?.value||null};
    await api(task?`api/tasks/${task.id}`:'api/tasks',{method:task?'PUT':'POST',body});closeModal();await refresh({quiet:true});navigate('maintenance');toast(task?'Task updated.':'Task created.');
  }});
  $('#taskAsset').value=task?.asset_id||assetId||'';
  const fillMeters=async(selected=task?.meter_id)=>{const meters=await api('api/meters');const asset=$('#taskAsset').value;if(!$('#taskMeter'))return;const available=asset?meters.filter(m=>m.asset_id===asset):[];$('#taskMeter').innerHTML=!asset?'<option value="" selected disabled>Choose an item first…</option>':available.length?'<option value="">Choose a meter…</option>'+available.map(m=>`<option value="${m.id}" ${selected===m.id?'selected':''}>${esc(m.name)} (${esc(m.unit)})</option>`).join(''):'<option value="" selected disabled>No meters configured for this item</option>';};
  await fillMeters(); $('#taskAsset').onchange=()=>fillMeters();
  $('#scheduleType').onchange=()=>{const values={};new FormData($('#modalForm')).forEach((v,k)=>values[k]=v);$('#dynamicSchedule').innerHTML=scheduleFields($('#scheduleType').value,values);fillMeters(values.meter_id);};
}

async function openTaskDetail(taskId) {
  const task=await api(`api/tasks/${taskId}`);
  openModal({title:task.title,eyebrow:'MAINTENANCE TASK',body:`<div class="detail-grid"><div class="field"><dt>Item</dt><dd>${esc(task.asset_name)}</dd></div><div class="field"><dt>Status</dt><dd>${task.active?stateLabel(task):'<span class="badge">CANCELED</span>'}</dd></div><div class="field"><dt>Schedule</dt><dd>${esc(scheduleSummary(task))}</dd></div><div class="field"><dt>Next due</dt><dd>${esc(taskDueText(task))}</dd></div><div class="field"><dt>Last completed</dt><dd>${fmtDate(task.last_completed_date)}</dd></div><div class="field"><dt>Projected meter date</dt><dd>${task.meter_forecast?.estimated_date?fmtDate(task.meter_forecast.estimated_date):'—'}</dd></div></div>${task.description?`<div class="section-heading"><h3>Description</h3></div><p>${esc(task.description)}</p>`:''}<div class="section-heading"><h3>Instructions & attachments</h3><button type="button" class="button small" data-upload-owner="task" data-owner-id="${task.id}">＋ Upload</button></div>${task.attachments.length?`<div class="attachments">${task.attachments.map(a=>`<div class="attachment"><span class="badge">${esc(a.category)}</span><a href="api/attachments/${a.id}" target="_blank">${esc(a.original_name)}</a><span class="subtle">${fmtSize(a.size_bytes)}</span></div>`).join('')}</div>`:'<p class="subtle">No task instructions attached.</p>'}<div class="section-heading"><h3>Completion history</h3></div>${task.completions.length?`<div class="timeline">${task.completions.slice(0,8).map(c=>`<div class="timeline-item"><strong>${c.outcome==='higher_authority'?'⇧ Higher authority':esc(c.outcome)}</strong> · ${fmtDate(c.completion_date)}<p>${esc(c.remark_text)}</p><button type="button" class="button small ghost" data-edit-completion="${c.id}" data-task="${task.id}">Edit record</button></div>`).join('')}</div>`:'<p class="subtle">No completions recorded.</p>'}<div class="section-heading"><h3>Actions</h3></div><div class="toolbar-group">${task.active?`<button type="button" class="button primary" data-modal-complete="${task.id}">Complete</button><button type="button" class="button" data-modal-snooze="${task.id}">Snooze</button><button type="button" class="button" data-modal-edit-task="${task.id}">Edit schedule</button><button type="button" class="button danger" data-cancel-task="${task.id}">Cancel task</button>`:'<span class="subtle">This task is no longer active.</span>'}</div>`,submit:'Close',onSubmit:()=>closeModal()});
}

function openEditCompletion(task, completion) {
  const taskId=task.id;
  const materialRows=(completion.materials||[]).map(m=>`<div class="material-row"><input value="${esc(m.description||'')}"><input type="number" min="0" step="0.01" value="${m.quantity??''}"><input type="number" min="0" step="0.01" value="${m.cost??''}"><button type="button" class="button small ghost" data-remove-material>×</button></div>`).join('');
  openModal({title:'Edit completed maintenance',eyebrow:'COMPLETION RECORD',body:`<div class="form-grid"><label>Work date<input name="completion_date" type="date" value="${completion.completion_date}"></label><label>Outcome<select name="outcome" id="editCompletionOutcome"><option value="completed" ${completion.outcome==='completed'?'selected':''}>Completed</option><option value="higher_authority" ${completion.outcome==='higher_authority'?'selected':''}>⇧ Completed by higher authority</option><option value="skipped" ${completion.outcome==='skipped'?'selected':''}>Skipped</option></select></label>${task.meter_id?`<label>Meter reading<input name="meter_reading" type="number" min="0" step="0.01" value="${completion.meter_reading??''}"></label>`:''}<label>Labor minutes<input name="labor_minutes" type="number" min="0" value="${completion.labor_minutes??''}"></label><label>Total cost<input name="total_cost" type="number" min="0" step="0.01" value="${completion.total_cost??''}"></label><label class="full">Replacement / corrective item<select name="replacement_asset_id"><option value="">None</option>${assetOptions({includeRoot:false})}</select></label><label class="full"><span class="check-row"><input name="advance_schedule" type="checkbox" ${completion.advance_schedule?'checked':''}> Advance/reset the ordinary periodicity</span></label><label class="full">Material-history remark<textarea name="remark_text">${esc(completion.remark_text)}</textarea></label><div class="full"><strong>Materials used</strong><div id="materialsList">${materialRows||'<div class="material-row"><input placeholder="Material or part"><input type="number" min="0" step="0.01" placeholder="Qty"><input type="number" min="0" step="0.01" placeholder="Cost"><button type="button" class="button small ghost" data-remove-material>×</button></div>'}</div><button type="button" class="button small" id="addEditMaterial">＋ Line</button></div></div>`,submit:'Save record',onSubmit:async()=>{const f=$('#modalForm').elements;const materials=$$('#materialsList .material-row').map(row=>{const i=$$('input',row);return{description:i[0].value.trim(),quantity:Number(i[1].value)||null,cost:Number(i[2].value)||null};}).filter(m=>m.description);await api(`api/completions/${completion.id}`,{method:'PUT',body:{completion_date:f.completion_date.value,outcome:f.outcome.value,meter_reading:f.meter_reading?.value||null,labor_minutes:f.labor_minutes.value||null,total_cost:f.total_cost.value||null,replacement_asset_id:f.replacement_asset_id.value||null,advance_schedule:f.advance_schedule.checked,remark_text:f.remark_text.value,materials}});closeModal();await refresh({quiet:true});openTaskDetail(taskId);toast('Completion record updated.');}});
  $('#modalForm').elements.replacement_asset_id.value=completion.replacement_asset_id||'';
  $('#addEditMaterial').onclick=()=>$('#materialsList').insertAdjacentHTML('beforeend','<div class="material-row"><input placeholder="Material or part"><input type="number" min="0" step="0.01" placeholder="Qty"><input type="number" min="0" step="0.01" placeholder="Cost"><button type="button" class="button small ghost" data-remove-material>×</button></div>');
  $('#materialsList').onclick=e=>{if(e.target.dataset.removeMaterial!==undefined)e.target.closest('.material-row').remove();};
}

function completionDraft(task) {
  const meter = task.meter ? ` at ${Number(task.meter.reading).toLocaleString()} ${task.meter_definition?.unit||''}` : '';
  return `Completed ${task.title.toLowerCase()}${meter}. No discrepancies noted.`;
}

function openComplete(taskId) {
  const task=state.data.tasks.find(t=>t.id===taskId); if(!task)return;
  const materialsRow=()=>`<div class="material-row"><input placeholder="Material or part"><input type="number" min="0" step="0.01" placeholder="Qty"><input type="number" min="0" step="0.01" placeholder="Cost"><button type="button" class="button small ghost" data-remove-material>×</button></div>`;
  openModal({title:`Complete: ${task.title}`,eyebrow:'REVIEW & APPROVE',body:`<div class="form-grid"><label>Work date<input name="completion_date" type="date" value="${today()}"></label><label>Outcome<select name="outcome" id="completionOutcome"><option value="completed">Completed</option><option value="higher_authority">⇧ Completed by higher authority</option><option value="skipped">Skipped</option></select></label>${task.meter_id?`<label>Meter reading (${esc(task.meter_definition?.unit||'')})<input name="meter_reading" type="number" min="0" step="0.01" value="${task.meter?.reading??''}"></label>`:''}<label>Labor time (minutes)<input name="labor_minutes" type="number" min="0"></label><label>Total cost<input name="total_cost" type="number" min="0" step="0.01"></label><label class="full hidden" id="replacementField">Replacement / corrective item<select name="replacement_asset_id"><option value="">Choose item…</option>${assetOptions({includeRoot:false})}</select></label><label class="full hidden" id="skipAdvance"><span class="check-row"><input name="advance_schedule" type="checkbox" checked> Advance the schedule from the skipped date</span></label><label class="full">Approved material-history remark<textarea name="remark_text">${esc(completionDraft(task))}</textarea></label><div class="full"><div class="section-heading"><h3>Materials used</h3><button type="button" class="button small" id="addMaterial">＋ Line</button></div><div id="materialsList">${materialsRow()}</div></div><p class="form-note full">Nothing is committed until you select <strong>Approve & complete</strong>. Higher-authority completion links corrective or replacement work and resets the ordinary periodicity.</p></div>`,submit:'Approve & complete',onSubmit:async()=>{
    const f=$('#modalForm').elements; const materials=$$('#materialsList .material-row').map(row=>{const i=$$('input',row);return {description:i[0].value.trim(),quantity:Number(i[1].value)||null,cost:Number(i[2].value)||null};}).filter(m=>m.description);
    await api(`api/tasks/${task.id}/complete`,{method:'POST',body:{completion_date:f.completion_date.value,outcome:f.outcome.value,meter_reading:f.meter_reading?.value||null,labor_minutes:f.labor_minutes.value||null,total_cost:f.total_cost.value||null,replacement_asset_id:f.replacement_asset_id?.value||null,advance_schedule:f.advance_schedule?.checked??true,remark_text:f.remark_text.value,materials}});closeModal();await refresh({quiet:true});navigate(state.page);toast('Maintenance completed and history updated.');
  }});
  $('#completionOutcome').onchange=e=>{$('#replacementField').classList.toggle('hidden',e.target.value!=='higher_authority');$('#skipAdvance').classList.toggle('hidden',e.target.value!=='skipped');};
  $('#addMaterial').onclick=()=>$('#materialsList').insertAdjacentHTML('beforeend',materialsRow());
  $('#materialsList').onclick=e=>{if(e.target.dataset.removeMaterial!==undefined)e.target.closest('.material-row').remove();};
}

function openSnooze(taskId) {
  const task=state.data.tasks.find(t=>t.id===taskId); const defaultDate=new Date();defaultDate.setDate(defaultDate.getDate()+7);
  openModal({title:`Snooze: ${task.title}`,eyebrow:'TEMPORARY REMINDER',body:`<label>Snooze ordinary reminders until<input name="until" type="date" value="${defaultDate.toISOString().slice(0,10)}"></label><p class="form-note danger-note">Snoozing does not change the recurring schedule and cannot hide a red 1.5× escalation.</p>`,submit:'Snooze',onSubmit:async()=>{await api(`api/tasks/${taskId}/snooze`,{method:'POST',body:{until:$('#modalForm').elements.until.value}});closeModal();await refresh({quiet:true});renderMaintenance();toast('Task snoozed.');}});
}

function openRemark(assetId, remark=null) {
  openModal({title:remark?'Edit remark':'Add material-history remark',eyebrow:'MATERIAL HISTORY',body:`<div class="form-grid"><label>Type<select name="category">${[['preventive','Preventive maintenance'],['corrective','Corrective maintenance'],['observation','Observation']].map(([v,l])=>`<option value="${v}" ${remark?.category===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Work date<input name="work_date" type="date" value="${remark?.work_date||today()}"></label><label class="full">Remark<textarea name="text">${esc(remark?.text||'')}</textarea></label></div>`,submit:remark?'Save changes':'Add remark',onSubmit:async()=>{const f=$('#modalForm').elements;await api(remark?`api/remarks/${remark.id}`:`api/assets/${assetId}/remarks`,{method:remark?'PUT':'POST',body:{category:f.category.value,work_date:f.work_date.value,text:f.text.value}});closeModal();await refresh({quiet:true});loadAssetDetail(assetId);toast('Material history updated.');}});
}

function openUpload(ownerType, ownerId) {
  openModal({title:'Upload attachment',eyebrow:'MANAGED STORAGE',body:`<div class="form-grid"><label class="full">Category<select name="category">${[['manual','Manual'],['receipt','Receipt'],['warranty','Warranty'],['diagram','Diagram'],['photograph','Photograph'],['video','Video'],['service_record','Service record'],['other','Other']].map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select></label><label class="full">File<input name="file" type="file"></label><p class="form-note full">The file is copied into managed storage and included in full export and Home Assistant backup data.</p></div>`,submit:'Upload',onSubmit:async()=>{const f=$('#modalForm').elements;if(!f.file.files[0])throw new Error('Choose a file.');const body=new FormData();body.append('owner_type',ownerType);body.append('owner_id',ownerId);body.append('category',f.category.value);body.append('file',f.file.files[0]);await api('api/attachments',{method:'POST',body});closeModal();if(ownerType==='asset')loadAssetDetail(ownerId);toast('Attachment uploaded.');}});
}

const localDateTime=()=>new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16);
const meterTypeLabels={mileage:'Distance / Mileage',runtime:'Runtime',cycles:'Counts / Cycles',volume:'Volume',energy:'Energy',mass:'Mass'};
function meterTypeOptions(selected='mileage'){return `${state.data.meter_units[selected]?'':`<option value="${esc(selected)}" selected disabled>Legacy Type — Choose a Standard Type</option>`}${Object.keys(state.data.meter_units).map(kind=>`<option value="${kind}" ${kind===selected?'selected':''}>${meterTypeLabels[kind]||kind}</option>`).join('')}`;}
function meterUnitOptions(kind,selected=''){const units=state.data.meter_units[kind]||[];return units.length?units.map(unit=>`<option value="${esc(unit)}" ${unit===selected?'selected':''}>${esc(unit)}</option>`).join(''):`<option value="${esc(selected)}" selected disabled>Choose a Standard Type First</option>`;}

async function meterById(meterId){return (await api('api/meters?include_archived=1')).find(m=>m.id===meterId);}

function openMeterForm(meter=null, assetId=null, chooseAsset=false) {
  const kind=meter?.kind||'mileage';
  const unit=state.data.meter_units[kind]?.includes(meter?.unit)?meter.unit:(meter?.unit||state.data.meter_units[kind]?.[0]||'');
  openModal({title:meter?'Edit Meter':'Add Meter',eyebrow:'USAGE TRACKING',helpId:'meters-create',body:`<div class="form-grid">${chooseAsset&&!meter?`<label class="full">Item<select name="asset_id"><option value="">Choose an item…</option>${assetOptions({includeRoot:false})}</select></label>`:''}<label class="full">Meter Name<input name="name" value="${esc(meter?.name||'')}" placeholder="Odometer, engine hours, cycles…" required></label><label>Type<select name="kind" id="meterKind">${meterTypeOptions(kind)}</select></label><label>Unit<select name="unit" id="meterUnit">${meterUnitOptions(kind,unit)}</select></label>${meter?'':'<label>Initial Reading (optional)<input name="initial_reading" type="number" min="0" step="0.01"></label><label>Initial Reading Time<input name="initial_recorded_at" type="datetime-local" value="'+localDateTime()+'"></label>'}<p class="form-note full">Use one consistent unit. Changing a meter unit does not convert existing readings or maintenance thresholds.</p></div>`,submit:meter?'Save Meter':'Add Meter',onSubmit:async()=>{
    const f=$('#modalForm').elements;const selectedAsset=meter?.asset_id||assetId||f.asset_id?.value;
    if(!selectedAsset)throw new Error('Choose an item for this meter.');
    if(meter&&f.unit.value!==meter.unit&&(meter.reading_count||meter.task_count)&&!confirm('Changing the unit will not convert existing readings or maintenance thresholds. Continue?'))return;
    const body={asset_id:selectedAsset,name:f.name.value,kind:f.kind.value,unit:f.unit.value,initial_reading:f.initial_reading?.value||null,initial_recorded_at:f.initial_recorded_at?.value?new Date(f.initial_recorded_at.value).toISOString():null};
    await api(meter?`api/meters/${meter.id}`:'api/meters',{method:meter?'PUT':'POST',body});closeModal();await refresh({quiet:true});if(state.page==='assets'&&selectedAsset)loadAssetDetail(selectedAsset);else navigate('meters');toast(meter?'Meter updated.':'Meter added.');
  }});
  $('#meterKind').onchange=()=>{$('#meterUnit').innerHTML=meterUnitOptions($('#meterKind').value);};
}

function openNewMeter(assetId){openMeterForm(null,assetId,false);}

async function openEditMeter(meterId){const meter=await meterById(meterId);if(meter)openMeterForm(meter);}

async function openSingleReading(meterId) {
  const meter=await meterById(meterId);if(!meter||meter.archived)return toast('This meter is archived or unavailable.','error');
  openModal({title:`Update ${meter.name}`,eyebrow:'INDIVIDUAL READING',helpId:'meters-update',body:`<div class="form-grid"><div class="field full"><dt>Item</dt><dd>${esc(meter.asset_name)}</dd></div><div class="field"><dt>Current Reading</dt><dd>${meter.latest?`${Number(meter.latest.reading).toLocaleString()} ${esc(meter.unit)}`:'No Reading'}</dd></div><label>Reading<input name="reading" type="number" min="${meter.latest?.reading??0}" step="0.01" required autofocus></label><label class="full">Reading Date and Time<input name="recorded_at" type="datetime-local" value="${localDateTime()}"></label><label class="full">Note (optional)<input name="note"></label></div>`,submit:'Save Reading',onSubmit:async()=>{const f=$('#modalForm').elements;await api('api/meters/readings',{method:'POST',body:{readings:[{meter_id:meter.id,reading:f.reading.value,recorded_at:new Date(f.recorded_at.value).toISOString(),note:f.note.value}]}});closeModal();await refresh({quiet:true});navigate('meters');toast('Meter reading saved.');}});
}

async function openReadings() {
  const meters=await api('api/meters');
  if(!meters.length)return openModal({title:'Update Meter Readings',eyebrow:'QUICK ENTRY',helpId:'meters-update',body:'<div class="empty-state"><h2>No Meters Configured</h2><p>Create a meter before entering readings.</p><button type="button" class="button primary" data-new-meter-page>＋ New Meter</button></div>',submit:'Close',onSubmit:closeModal});
  openModal({title:'Update Meter Readings',eyebrow:'QUICK ENTRY',helpId:'meters-update',body:`<p class="form-note">Enter only the meters you checked. Every submitted reading receives the selected date and time.</p><label>Reading Date and Time<input id="readingTime" type="datetime-local" value="${localDateTime()}"></label><div class="dense-table-wrap" style="margin-top:14px"><table><thead><tr><th>Item</th><th>Meter</th><th>Current</th><th>New Reading</th></tr></thead><tbody>${meters.map(m=>`<tr data-meter-row="${m.id}"><td>${esc(m.asset_name)}</td><td>${esc(m.name)}</td><td>${m.latest?Number(m.latest.reading).toLocaleString():'—'} ${esc(m.unit)}</td><td><input type="number" min="${m.latest?.reading??0}" step="0.01" placeholder="Not Checked"></td></tr>`).join('')}</tbody></table></div>`,submit:'Save Entered Readings',onSubmit:async()=>{const recorded_at=new Date($('#readingTime').value).toISOString();const readings=$$('[data-meter-row]').map(row=>({meter_id:row.dataset.meterRow,reading:$('input',row).value,recorded_at})).filter(x=>x.reading!=='');if(!readings.length)throw new Error('Enter at least one reading.');await api('api/meters/readings',{method:'POST',body:{readings}});closeModal();await refresh({quiet:true});navigate('meters');toast(`${readings.length} reading${readings.length===1?'':'s'} saved.`);}});
}

async function openMeterQr(meterId) {
  const meter=await meterById(meterId),appInfo=await api('api/ha/app-info');if(!meter)return;
  let url;try{url=companionNavigateUrl(appInfo.panel_path,'meter',meterId);}catch(error){return toast(error.message,'error');}
  openModal({title:`QR Label: ${meter.name}`,eyebrow:'PRINTABLE QUICK ENTRY',helpId:'meters-qr',body:`<div style="text-align:center"><img src="api/meters/${meter.id}/qr?url=${encodeURIComponent(url)}" alt="QR code for ${esc(meter.name)}" style="width:min(280px,100%);background:white;padding:10px;border-radius:12px"><h3>${esc(meter.asset_name)} — ${esc(meter.name)}</h3><p class="subtle">Scanning opens Home Assistant Companion on Android or Apple devices, then opens this meter’s individual reading form. The label contains no credentials.</p><button type="button" class="button" onclick="window.print()">Print Label</button></div>`,submit:'Close',onSubmit:closeModal});
}

async function openManageMeter(meterId) {
  const meter=await meterById(meterId);if(!meter)return;
  const permanent=meter.reading_count===0&&meter.task_count===0;
  const warning=meter.active_task_count?`<p class="form-note danger-note">This meter is used by ${meter.active_task_count} active maintenance task${meter.active_task_count===1?'':'s'}. Change or cancel those tasks before archiving it.</p>`:'';
  openModal({title:`Manage ${meter.name}`,eyebrow:'METER LIFECYCLE',helpId:'meters-manage',body:`${warning}<p>${meter.reading_count} recorded reading${meter.reading_count===1?'':'s'} · ${meter.task_count} linked task${meter.task_count===1?'':'s'}</p><div class="toolbar-group">${meter.archived?`<button type="button" class="button" data-restore-meter="${meter.id}">Restore Meter</button>`:permanent?`<button type="button" class="button danger" data-delete-meter="${meter.id}">Delete Permanently</button>`:`<button type="button" class="button danger" data-archive-meter="${meter.id}" ${meter.active_task_count?'disabled':''}>Archive Meter</button>`}</div>`,submit:'Close',onSubmit:closeModal});
}

function openAssetActions(assetId) {
  const asset=state.data.assets.find(a=>a.id===assetId);
  openModal({title:`Actions: ${asset.name}`,eyebrow:'ITEM LIFECYCLE',body:`<div class="toolbar-group"><button type="button" class="button" data-action-move>Move item</button><button type="button" class="button" data-action-replace>Replace item</button>${asset.archived?'<button type="button" class="button" data-action-restore>Restore</button>':'<button type="button" class="button danger" data-action-archive>Archive</button>'}<button type="button" class="button danger" data-action-delete>Delete permanently</button></div><p class="form-note danger-note" style="margin-top:18px">Archive is reversible. Permanent deletion is intended only for items and history you will never need again.</p>`,submit:'Close',onSubmit:closeModal});
  $('[data-action-move]').onclick=()=>openMove(assetId); $('[data-action-replace]').onclick=()=>openReplace(assetId);
  $('[data-action-archive]')?.addEventListener('click',()=>openArchive(assetId));
  $('[data-action-restore]')?.addEventListener('click',async()=>{await api(`api/assets/${assetId}/restore`,{method:'POST'});closeModal();await refresh({quiet:true});toast('Item restored.');});
  $('[data-action-delete]').onclick=()=>openPermanentDelete(assetId);
}

function openMove(assetId) {
  const asset=state.data.assets.find(a=>a.id===assetId);
  openModal({title:`Move ${asset.name}`,eyebrow:'HIERARCHY',body:`<label>New parent<select name="parent_id">${assetOptions({exclude:assetId})}</select></label><p class="form-note">The item’s complete history, tasks, meters, and attachments move with it.</p>`,submit:'Move item',onSubmit:async()=>{await api(`api/assets/${assetId}/move`,{method:'POST',body:{parent_id:$('#modalForm').elements.parent_id.value||null}});closeModal();await refresh({quiet:true});state.expanded.add($('#modalForm').elements.parent_id.value);renderAssets();toast('Item moved.');}});
}

function openArchive(assetId) {
  const asset=state.data.assets.find(a=>a.id===assetId), children=state.data.assets.filter(a=>a.parent_id===assetId&&!a.archived);
  openModal({title:`Archive ${asset.name}`,eyebrow:'RECORD RETENTION',body:`<label>Reason<textarea name="reason">Item archived.</textarea></label>${children.length?`<p class="form-note danger-note">Every active child must be moved or archived.</p>${children.map(c=>`<div class="form-grid" data-child-decision="${c.id}"><strong>${esc(c.name)}</strong><select data-child-action><option value="archive">Archive with parent</option><option value="move">Move to another parent</option></select><select data-child-parent class="hidden">${assetOptions({exclude:assetId})}</select></div>`).join('')}`:''}`,submit:'Archive item',danger:true,onSubmit:async()=>{const decisions={};$$('[data-child-decision]').forEach(row=>{const action=$('[data-child-action]',row).value;decisions[row.dataset.childDecision]={action,parent_id:action==='move'?$('[data-child-parent]',row).value||null:null};});await api(`api/assets/${assetId}/archive`,{method:'POST',body:{reason:$('#modalForm').elements.reason.value,children:decisions}});closeModal();state.selectedAsset=null;await refresh({quiet:true});renderAssets();toast('Item archived.');}});
  $$('[data-child-action]').forEach(sel=>sel.onchange=()=>sel.closest('[data-child-decision]').querySelector('[data-child-parent]').classList.toggle('hidden',sel.value!=='move'));
}

function openReplace(assetId) {
  const old=state.data.assets.find(a=>a.id===assetId), children=state.data.assets.filter(a=>a.parent_id===assetId&&!a.archived), tasks=state.data.tasks.filter(t=>t.asset_id===assetId);
  openModal({title:`Replace ${old.name}`,eyebrow:'GUIDED REPLACEMENT',body:`<div class="form-grid"><label class="full">New item name<input name="name" value="${esc(old.name)}"></label><label class="full">Reason<textarea name="reason">Replaced with a new item.</textarea></label><div class="full"><strong>Children to transfer</strong>${children.length?children.map(c=>`<label class="check-row"><input type="checkbox" data-move-child="${c.id}" checked> ${esc(c.name)}</label>`).join(''):'<p class="subtle">No child items.</p>'}</div><div class="full"><strong>Maintenance plans to copy</strong>${tasks.length?tasks.map(t=>`<label class="check-row"><input type="checkbox" data-copy-task="${t.id}" checked> ${esc(t.title)}</label>`).join(''):'<p class="subtle">No maintenance plans.</p>'}</div><p class="form-note full">The old and new records remain visibly linked. Copied plans start a fresh history.</p></div>`,submit:'Create replacement',onSubmit:async()=>{const f=$('#modalForm').elements;const result=await api(`api/assets/${assetId}/replace`,{method:'POST',body:{name:f.name.value,reason:f.reason.value,attributes:old.attributes,move_child_ids:$$('[data-move-child]:checked').map(x=>x.dataset.moveChild),copy_task_ids:$$('[data-copy-task]:checked').map(x=>x.dataset.copyTask)}});closeModal();await refresh({quiet:true});state.selectedAsset=result.id;renderAssets();toast('Replacement created and linked.');}});
}

function openPermanentDelete(assetId) {
  const asset=state.data.assets.find(a=>a.id===assetId);
  openModal({title:'Permanently delete item?',eyebrow:'DESTRUCTIVE ACTION',body:`<p>This permanently deletes <strong>${esc(asset.name)}</strong> and its descendants. This cannot be undone.</p><label>Type <strong>DELETE</strong> to confirm<input name="confirmation" autocomplete="off"></label>`,submit:'Delete permanently',danger:true,onSubmit:async()=>{if($('#modalForm').elements.confirmation.value!=='DELETE')throw new Error('Type DELETE exactly to confirm.');await api(`api/assets/${assetId}?confirm=permanent`,{method:'DELETE'});closeModal();state.selectedAsset=null;await refresh({quiet:true});renderAssets();toast('Item permanently deleted.');}});
}

async function openQr(assetId) {
  const asset=state.data.assets.find(a=>a.id===assetId), appInfo=await api('api/ha/app-info');
  let url;try{url=companionNavigateUrl(appInfo.panel_path,'asset',assetId);}catch(error){return toast(error.message,'error');}
  openModal({title:`QR Label: ${asset.name}`,eyebrow:'PRINTABLE LABEL',body:`<div style="text-align:center"><img src="api/assets/${assetId}/qr?url=${encodeURIComponent(url)}" alt="QR code for ${esc(asset.name)}" style="width:min(280px,100%);background:white;padding:10px;border-radius:12px"><h3>${esc(asset.name)}</h3><p class="subtle">Scanning opens Home Assistant Companion on Android or Apple devices, then opens this item. The label contains no credentials.</p><button type="button" class="button" onclick="window.print()">Print Label</button></div>`,submit:'Close',onSubmit:closeModal});
}

async function configureNotifications(fromSetup=false) {
  const result=await api('api/ha/notify-services'); const selected=new Set(state.data.settings.notification_services||[]);
  openModal({title:'Companion notifications',eyebrow:'HOME ASSISTANT',body:`${result.connected?'<p>Select every device that should receive overdue reminders.</p>':`<p class="form-note danger-note">${esc(result.message||'Home Assistant is not connected.')}</p>`}<div class="device-list">${result.services.length?result.services.map(s=>`<label class="device-option"><input type="checkbox" data-notify-service="${s.service}" ${selected.has(s.service)?'checked':''}> <span><strong>${esc(s.label)}</strong><small class="subtle">notify.${esc(s.service)}</small></span></label>`).join(''):'<p class="subtle">No Companion notification services were found. Open the app once on each phone, then return here.</p>'}</div><label style="margin-top:15px">Daily notification check hour (0–23)<input name="hour" type="number" min="0" max="23" value="${state.data.settings.notification_check_hour??9}"></label>`,submit:'Save devices',onSubmit:async()=>{const services=$$('[data-notify-service]:checked').map(x=>x.dataset.notifyService);await api('api/settings',{method:'PUT',body:{notification_services:services,notification_check_hour:Number($('#modalForm').elements.hour.value)}});if(services.length)await api('api/ha/test-notification',{method:'POST',body:{services}});closeModal();await refresh({quiet:true});toast('Notification devices saved.');}});
}

function startSetup() {
  state.setupStep=0; const dialog=$('#setupDialog');
  const render=()=>{const body=$('#setupBody'); if(state.setupStep===0){body.innerHTML=`<div class="setup-hero"><div class="big-mark">⌂</div><h3>Your local maintenance record is ready.</h3><p>The fictional sample property is installed so you can safely explore every workflow. Your real records stay on this Home Assistant system and are available through Nabu Casa anywhere you normally access Home Assistant.</p></div>`;$('#setupNext').textContent='Choose notifications';}
    else {body.innerHTML=`<div class="setup-hero"><div class="big-mark">⌁</div><h3>Companion notifications</h3><p>Finish setup, then open Settings → Notifications to select any phones that should receive overdue reminders. Devices appear after the Home Assistant Companion app has registered its notification service.</p><div class="callout">You can use the tracker without notifications and configure them later.</div></div>`;$('#setupNext').textContent='Finish setup';}};
  $('#setupNext').onclick=async()=>{if(state.setupStep===0){state.setupStep=1;render();}else{await api('api/settings',{method:'PUT',body:{setup_complete:true}});dialog.close();await refresh({quiet:true});configureNotifications();}};render();dialog.showModal();
}

function applyTheme(theme) {
  const effective=theme==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):theme;
  document.documentElement.dataset.theme=effective; storageSet('hmt-theme',theme);
}

document.addEventListener('click', async event => {
  const target=event.target.closest('button,a,tr,[data-asset-id],[data-task-id]'); if(!target)return;
  if(target.dataset.help){openContextHelp(target.dataset.help);return;}
  if(target.dataset.page){event.preventDefault();navigate(target.dataset.page);return;}
  if(target.dataset.go){navigate(target.dataset.go);return;}
  if(target.dataset.action==='new-asset'){openAssetForm();return;}
  if(target.dataset.action==='new-task'){openTaskForm();return;}
  if(target.dataset.action==='readings'){openReadings();return;}
  if(target.dataset.selectAsset){state.selectedAsset=target.dataset.selectAsset;state.expanded.add(target.dataset.selectAsset);renderAssets();return;}
  if(target.dataset.assetId){state.selectedAsset=target.dataset.assetId;state.assetView='tree';navigate('assets');return;}
  if(target.dataset.toggleNode){state.expanded.has(target.dataset.toggleNode)?state.expanded.delete(target.dataset.toggleNode):state.expanded.add(target.dataset.toggleNode);renderAssets();return;}
  if(target.dataset.assetView){state.assetView=target.dataset.assetView;renderAssets();return;}
  if(target.dataset.backAssets!==undefined){state.selectedAsset=null;renderAssets();return;}
  if(target.dataset.editAsset){openAssetForm(state.data.assets.find(a=>a.id===target.dataset.editAsset));return;}
  if(target.dataset.moreAsset){openAssetActions(target.dataset.moreAsset);return;}
  if(target.dataset.qr){openQr(target.dataset.qr);return;}
  if(target.dataset.newTaskAsset){openTaskForm(null,target.dataset.newTaskAsset);return;}
  if(target.dataset.newRemark){openRemark(target.dataset.newRemark);return;}
  if(target.dataset.editRemark){const detail=await api(`api/assets/${target.dataset.asset}`);openRemark(target.dataset.asset,detail.remarks.find(r=>r.id===target.dataset.editRemark));return;}
  if(target.dataset.deleteRemark){if(confirm('Delete this remark and its remark attachments?')){await api(`api/remarks/${target.dataset.deleteRemark}`,{method:'DELETE'});await refresh({quiet:true});loadAssetDetail(target.dataset.asset);toast('Remark deleted.');}return;}
  if(target.dataset.uploadOwner){openUpload(target.dataset.uploadOwner,target.dataset.ownerId);return;}
  if(target.dataset.deleteAttachment){if(confirm('Delete this attachment?')){await api(`api/attachments/${target.dataset.deleteAttachment}`,{method:'DELETE'});loadAssetDetail(state.selectedAsset);toast('Attachment deleted.');}return;}
  if(target.dataset.newMeter){openNewMeter(target.dataset.newMeter);return;}
  if(target.dataset.newMeterPage!==undefined){if($('#modal').open)closeModal();openMeterForm(null,null,true);return;}
  if(target.dataset.updateMeter){if($('#modal').open)closeModal();openSingleReading(target.dataset.updateMeter);return;}
  if(target.dataset.meterQr){if($('#modal').open)closeModal();openMeterQr(target.dataset.meterQr);return;}
  if(target.dataset.editMeter){if($('#modal').open)closeModal();openEditMeter(target.dataset.editMeter);return;}
  if(target.dataset.manageMeter){openManageMeter(target.dataset.manageMeter);return;}
  if(target.dataset.archiveMeter){if(confirm('Archive this meter? Its history will remain available.')){await api(`api/meters/${target.dataset.archiveMeter}/archive`,{method:'POST'});closeModal();await refresh({quiet:true});navigate('meters');toast('Meter archived.');}return;}
  if(target.dataset.deleteMeter){if(confirm('Permanently delete this unused meter? This cannot be undone.')){await api(`api/meters/${target.dataset.deleteMeter}`,{method:'DELETE'});closeModal();await refresh({quiet:true});navigate('meters');toast('Meter permanently deleted.');}return;}
  if(target.dataset.restoreMeter){await api(`api/meters/${target.dataset.restoreMeter}/restore`,{method:'POST'});if($('#modal').open)closeModal();await refresh({quiet:true});navigate('meters');toast('Meter restored.');return;}
  if(target.dataset.complete){event.stopPropagation();openComplete(target.dataset.complete);return;}
  if(target.dataset.taskId){openTaskDetail(target.dataset.taskId);return;}
  if(target.dataset.modalComplete){closeModal();openComplete(target.dataset.modalComplete);return;}
  if(target.dataset.modalSnooze){closeModal();openSnooze(target.dataset.modalSnooze);return;}
  if(target.dataset.modalEditTask){const task=state.data.tasks.find(t=>t.id===target.dataset.modalEditTask);closeModal();openTaskForm(task);return;}
  if(target.dataset.editCompletion){const detail=await api(`api/tasks/${target.dataset.task}`);const completion=detail.completions.find(c=>c.id===target.dataset.editCompletion);closeModal();openEditCompletion(detail,completion);return;}
  if(target.dataset.cancelTask){const reason=prompt('Reason for canceling this task:','Maintenance task canceled.');if(reason!==null&&confirm('Cancel this maintenance task?')){await api(`api/tasks/${target.dataset.cancelTask}/cancel`,{method:'POST',body:{reason}});closeModal();await refresh({quiet:true});navigate('maintenance');toast('Task canceled.');}return;}
  if(target.dataset.maintView){state.maintenanceView=target.dataset.maintView;renderMaintenance();return;}
  if(target.dataset.calNav){state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+Number(target.dataset.calNav),1);renderMaintenance();return;}
  if(target.dataset.report){state.report=target.dataset.report;navigate('reports');return;}
});

document.addEventListener('input',event=>{
  if(event.target.id==='assetSearch'){const value=event.target.value;renderAssets();const input=$('#assetSearch');input.value=value;input.focus();input.setSelectionRange(value.length,value.length);}
  if(event.target.id==='assetTableSearch'){const query=event.target.value.toLowerCase();$$('#page-assets tbody tr').forEach(row=>row.classList.toggle('hidden',!row.textContent.toLowerCase().includes(query)));}
  if(event.target.id==='helpSearch'){const value=event.target.value;renderHelpMaster(value);const input=$('#helpSearch');input.focus();input.setSelectionRange(value.length,value.length);}
});
document.addEventListener('change',event=>{if(event.target.id==='showArchived')renderAssets();if(event.target.id==='showArchivedMeters'){state.showArchivedMeters=event.target.checked;renderMeters();}if(event.target.id==='reportSelect')state.report=event.target.value;});

document.addEventListener('dragstart',event=>{const row=event.target.closest('[data-drag-id]');if(row)event.dataTransfer.setData('text/plain',row.dataset.dragId);});
document.addEventListener('dragover',event=>{const row=event.target.closest('[data-drop-id]');if(row){event.preventDefault();row.classList.add('drag-over');}});
document.addEventListener('dragleave',event=>event.target.closest('[data-drop-id]')?.classList.remove('drag-over'));
document.addEventListener('drop',async event=>{const row=event.target.closest('[data-drop-id]');if(!row)return;event.preventDefault();row.classList.remove('drag-over');const id=event.dataTransfer.getData('text/plain');if(id&&id!==row.dataset.dropId){try{await api(`api/assets/${id}/move`,{method:'POST',body:{parent_id:row.dataset.dropId}});state.expanded.add(row.dataset.dropId);await refresh({quiet:true});renderAssets();toast('Item moved.');}catch(e){toast(e.message,'error');}}});

$('#nav').addEventListener('click',()=>{});
$('#quickAdd').onclick=()=>state.page==='maintenance'?openTaskForm():state.page==='meters'?openReadings():openAssetForm();
$('#themeToggle').onclick=()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
$('#modalClose').onclick=closeModal;
$('#modalCancel').onclick=closeModal;
$('#modalForm').onsubmit=event=>{event.preventDefault();$('#modalSubmit').click();};
$('#helpClose').onclick=()=>$('#helpDialog').close();
$('#helpDone').onclick=()=>$('#helpDialog').close();
$('#helpFull').onclick=()=>{$('#helpDialog').close();navigate('help');};
function setSidebarCollapsed(collapsed) {
  $('#app').classList.toggle('sidebar-collapsed',collapsed);
  storageSet('hmt-sidebar-collapsed',String(collapsed));
  const toggle=$('#sidebarToggle'), label=collapsed?'Expand sidebar':'Minimize sidebar';
  toggle.setAttribute('aria-label',label);toggle.setAttribute('aria-expanded',String(!collapsed));toggle.title=label;
}
const sidebarToggle=$('#sidebarToggle');
let sidebarPointerHandled=false;
sidebarToggle.addEventListener('pointerup',event=>{
  if(event.pointerType!=='touch'&&event.pointerType!=='pen')return;
  event.preventDefault();sidebarPointerHandled=true;
  setSidebarCollapsed(!$('#app').classList.contains('sidebar-collapsed'));
  setTimeout(()=>{sidebarPointerHandled=false;},450);
});
sidebarToggle.addEventListener('click',event=>{
  event.preventDefault();if(sidebarPointerHandled)return;
  setSidebarCollapsed(!$('#app').classList.contains('sidebar-collapsed'));
});
document.addEventListener('click',async e=>{
  if(e.target.id==='runReport')runReport($('#reportSelect').value);
  if(e.target.id==='saveWindow'){await api('api/settings',{method:'PUT',body:{dashboard_window_days:Number($('#settingWindow').value)}});await refresh({quiet:true});toast('Dashboard window saved.');}
  if(e.target.id==='configureNotifications')configureNotifications();
  if(e.target.id==='toggleSample'){const installed=state.data.settings.sample_data_installed;if(confirm(installed?'Remove only the fictional sample records?':'Reinstall the fictional sample records?')){await api(`api/sample-data/${installed?'remove':'restore'}`,{method:'POST'});state.selectedAsset=null;await refresh({quiet:true});navigate('settings');toast(installed?'Sample data removed.':'Sample data installed.');}}
  if(e.target.id==='importData'){const file=$('#importFile').files[0];if(!file)return toast('Choose an export ZIP first.','error');if(!confirm('Import will replace all current tracker records and attachments. Continue?'))return;const body=new FormData();body.append('file',file);await api('api/import',{method:'POST',body});toast('Import complete. Reloading…');setTimeout(()=>location.reload(),900);}
});

function routedAssetId(){return new URLSearchParams(location.search).get('asset') || location.hash.match(/^#\/asset\/(.+)$/)?.[1] || null;}
function routedMeterId(){return new URLSearchParams(location.search).get('meter') || location.hash.match(/^#\/meter\/(.+)$/)?.[1] || null;}
window.addEventListener('hashchange',()=>{const id=routedAssetId();if(id&&state.data){state.selectedAsset=id;state.assetView='tree';navigate('assets');}});

setSidebarCollapsed(storageGet('hmt-sidebar-collapsed')==='true');
refresh().then(()=>{const meterId=routedMeterId(),assetId=routedAssetId();if(meterId){navigate('meters');openSingleReading(meterId);}else if(assetId){state.selectedAsset=assetId;state.assetView='tree';navigate('assets');}});
