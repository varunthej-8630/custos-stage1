const socket = io({
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  timeout: 10000,
});
let alertsData = [], dismissed = false, monitoring = false;
let drawMode = false, zoneType = 'HIGH', zones = [], drawing = false, sx, sy, cx, cy;
let t0 = Date.now(), peakRisk = 0, rHist = [], aPerHr = new Array(24).fill(0);
let rChart = null, aChart = null, curPage = 'dashboard', afilt = 'all';
let selCamIdx = 0, availCams = [];
// Real camera frame dimensions — received from server on first socket update
let camW = 640, camH = 480, camDimsReady = false;

// ═══════════════════════════════════════════════════════
// CAMERA MODAL
// How it works:
//   1. User clicks "📷 Camera" button
//   2. Browser calls /list_cameras on Python server
//   3. Python probes cv2.VideoCapture(0..4) — only real cameras appear
//   4. Results shown as cards — laptop cam + any USB cams connected
//   5. User selects one and clicks Apply
//   6. socket.emit('set_camera') tells Python to switch cv2 source
//   7. Feed reloads with new camera
// ═══════════════════════════════════════════════════════
async function openCamModal() {
  // Show modal immediately with spinner
  document.getElementById('camOverlay').classList.add('on');
  document.getElementById('camApply').disabled = true;
  document.getElementById('camSub').textContent = 'Scanning connected cameras…';
  document.getElementById('camNote').textContent = 'Python is probing OpenCV camera indices 0–4';
  document.getElementById('camList').innerHTML =
    '<div class="cam-scan-msg"><div class="cam-spinner"></div>Scanning, please wait…</div>';

  availCams = [];

  try {
    // Ask Python backend to scan cameras using OpenCV
    const response = await fetch('/list_cameras');
    const data = await response.json();

    if (!data.cameras || data.cameras.length === 0) {
      // No cameras found at all
      document.getElementById('camList').innerHTML =
        '<div class="cam-error-box">⚠ No cameras detected. Check your connections and try again.</div>';
      document.getElementById('camSub').textContent = 'No cameras found';
      document.getElementById('camNote').textContent = 'Connect a camera and click the Camera button again';
      return;
    }

    availCams = data.cameras;
    const count = availCams.length;
    document.getElementById('camSub').textContent =
      count === 1 ? '1 camera detected' : `${count} cameras detected`;
    document.getElementById('camNote').textContent =
      'Select a camera below and click Apply to switch';

    renderCamList();

  } catch (err) {
    document.getElementById('camList').innerHTML =
      '<div class="cam-error-box">⚠ Could not reach server. Is Python running?</div>';
    document.getElementById('camSub').textContent = 'Server connection failed';
    document.getElementById('camNote').textContent = 'Make sure python web_server.py is running';
  }
}

function renderCamList() {
  document.getElementById('camList').innerHTML = availCams.map(cam => `
    <div class="cam-item ${cam.index === selCamIdx ? 'sel' : ''}" onclick="selectCam(${cam.index})">
      <div class="cam-ico">${cam.icon}</div>
      <div class="cam-info">
        <div class="cam-name">${cam.name}</div>
        <div class="cam-sub-text">${cam.sub}</div>
      </div>
      <div class="cam-chk">${cam.index === selCamIdx ? '✓' : ''}</div>
    </div>
  `).join('');
  document.getElementById('camApply').disabled = false;
}

function selectCam(idx) {
  selCamIdx = idx;
  renderCamList();
}

function confirmCam() {
  const cam = availCams.find(c => c.index === selCamIdx);
  if (!cam) return;

  // Tell Python to switch the cv2.VideoCapture source
  socket.emit('set_camera', { index: selCamIdx });

  // Update HUD and settings labels immediately
  document.getElementById('hudCam').textContent = `CAM-0${selCamIdx + 1}`;
  document.getElementById('setCam').textContent = `${cam.name} (Index ${selCamIdx})`;

  // Reload the MJPEG feed so it shows the new camera
  const feed = document.getElementById('liveFeed');
  feed.src = '/video_feed?t=' + Date.now();

  document.getElementById('camOverlay').classList.remove('on');
}

// Close modal when clicking outside
document.getElementById('camOverlay').addEventListener('click', function (e) {
  if (e.target === this) this.classList.remove('on');
});

// ═══════════════════════════════════════════════════════
// SOCKET — with reconnection and connection status
// ═══════════════════════════════════════════════════════
socket.on('connect', () => { console.log('[CUSTOS] connected'); setConnStatus(true); });
socket.on('disconnect', () => { console.log('[CUSTOS] disconnected'); setConnStatus(false); });
socket.on('connect_error', () => setConnStatus(false));
socket.on('risk_update', onUpdate);
socket.on('tamper', d => {
  showBanner('CAMERA TAMPER DETECTED', 'Camera obstructed at ' + d.time);
  playAlertSound('tamper');
  alertsData.unshift({ time: d.time, score: 100, events: ['CAMERA TAMPERED!'], snapshot: '', clip: d.clip || '', resolved: false });
  renderTl(alertsData.slice(0, 8)); renderAlertsList(); refreshEvIfOpen();
  document.getElementById('notifPip').classList.add('on');
});
socket.on('alert_resolved', () => {
  const a = alertsData.find(x => !x.resolved); if (a) a.resolved = true;
  renderTl(alertsData.slice(0, 8)); renderAlertsList();
  dismissed = false;
  const b = document.getElementById('alertBanner');
  if (b.classList.contains('on')) {
    b.style.background = 'var(--green-bg)'; b.style.borderBottomColor = 'rgba(34,197,94,0.2)';
    document.getElementById('abTitle').style.color = 'var(--green)';
    document.getElementById('abTitle').textContent = 'Alert Resolved — Person Left Zone';
    document.getElementById('abSub').textContent = 'Risk returning to safe level';
    document.getElementById('abIcon').textContent = '✓';
    document.getElementById('abIcon').style.background = 'var(--green)';
    setTimeout(() => { b.classList.remove('on'); b.style = ''; }, 4000);
  }
});
function setConnStatus(ok) {
  // Sidebar connection pip — green when live, amber when reconnecting
  const pip = document.querySelector('.s-pip.on');
  const lbl = document.querySelector('.sb-status span');
  if (pip) pip.style.background = ok ? '' : 'var(--amber)';
  if (lbl) lbl.style.color = ok ? '' : 'var(--amber)';
}

// ═══════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════
function gotoPage(p) {
  document.querySelectorAll('.page').forEach(x => x.classList.remove('on'));
  document.querySelectorAll('.ni').forEach(x => x.classList.remove('on'));
  document.getElementById('page-' + p).classList.add('on');
  document.getElementById('ni-' + p).classList.add('on');
  curPage = p;
  if (p === 'analytics') initCharts();
  if (p === 'evidence') loadEvidence();
  if (p === 'alerts') renderAlertsList();
}
let slim = false;
function toggleSb() {
  slim = !slim;
  document.getElementById('sidebar').classList.toggle('slim', slim);
  document.getElementById('sbToggle').textContent = slim ? '▶' : '◀';
}

// ═══════════════════════════════════════════════════════
// MAIN UPDATE
// ═══════════════════════════════════════════════════════
function onUpdate(d) {
  // Capture real camera dims from server on first update
  if (d.cam_w && d.cam_h && !camDimsReady) {
    camW = d.cam_w; camH = d.cam_h; camDimsReady = true;
    console.log(`[CUSTOS] Camera: ${camW}×${camH}`);
  }
  const score = d.score || 0;
  rHist.push({ t: new Date().toTimeString().slice(0, 5), v: score });
  if (rHist.length > 60) rHist.shift();
  if (score > peakRisk) peakRisk = score;

  let col, lbl, lvc, dotc, bc;
  if (score < 40) { col = '#22c55e'; lbl = 'SAFE'; lvc = 'lv-safe'; dotc = ''; bc = 'safe'; }
  else if (score < 60) { col = '#f59e0b'; lbl = 'WATCH'; lvc = 'lv-watch'; dotc = 'w'; bc = 'watch'; }
  else if (score < 80) { col = '#f97316'; lbl = 'SUSPICIOUS'; lvc = 'lv-sus'; dotc = 's'; bc = 'sus'; }
  else { col = '#ef4444'; lbl = 'CRITICAL'; lvc = 'lv-crit'; dotc = 'c'; bc = 'crit'; }

  ['riskNum', 'monRiskNum'].forEach(id => { const e = document.getElementById(id); if (e) { e.textContent = Math.round(score); e.style.color = col; } });
  ['riskFill', 'monRiskFill'].forEach(id => { const e = document.getElementById(id); if (e) { e.style.width = score + '%'; e.style.background = col; } });
  ['riskBadge', 'monBadge'].forEach(id => { const e = document.getElementById(id); if (e) { e.className = 'risk-badge ' + bc; e.textContent = '● ' + lbl; } });
  const lp = document.getElementById('levelPill'); lp.className = 'level-pill ' + lvc; lp.textContent = '● ' + lbl;
  document.getElementById('riskDot').className = 'risk-ind ' + dotc;
  if (d.mode) document.getElementById('modeTag').textContent = d.mode + ' MODE';

  const active = {};
  (d.event_log || []).forEach(e => {
    if (e.includes('PACING')) active.PACING = true;
    if (e.includes('CROUCH')) active.CROUCHING = true;
    if (e.includes('linger')) active.LINGERING = true;
    if (e.includes('FROZE')) active.FREEZE = true;
    if (e.includes('RUNNING')) active.RUNNING = true;
    if (e.includes('circling')) active.CIRCLING = true;
  });
  const bHtml = ['PACING', 'CROUCHING', 'LINGERING', 'FREEZE', 'RUNNING', 'CIRCLING']
    .map(k => `<span class="chip ${active[k] ? 'active' : ''}">${k}</span>`).join('');
  ['behChips', 'monBeh'].forEach(id => { const e = document.getElementById(id); if (e) e.innerHTML = bHtml; });

  const reasons = getRs(d.event_log || []);
  const wp = document.getElementById('whyPanel');
  wp.innerHTML = reasons.length
    ? reasons.map(r => `<div class="why-row on"><div class="why-pip on"></div>${r}</div>`).join('')
    : '<div class="empty-msg">No active alerts</div>';

  if (d.alert_active && !dismissed) {
    const isH = (d.event_log || []).some(e => e.includes('HIGH'));
    showBanner(isH ? 'HIGH ZONE BREACH — Person Detected' : 'SUSPICIOUS ACTIVITY DETECTED',
      (reasons[0] || 'Suspicious activity') + ' · Score: ' + Math.round(score));
    document.getElementById('notifPip').classList.add('on');
    maybePlayAlert(true, false);
  } else if (!d.alert_active) {
    dismissed = false;
    maybePlayAlert(false, d.tamper || false);
  }
  if (d.tamper) maybePlayAlert(false, true);

  if (d.alerts && d.alerts.length) {
    alertsData = d.alerts; const n = d.alerts.length;
    document.getElementById('stAlerts').textContent = n;
    document.getElementById('tlCount').textContent = n + (n !== 1 ? ' alerts' : ' alert');
    const unresolved = d.alerts.filter(a => !a.resolved).length;
    const b = document.getElementById('alertBadge'); b.textContent = unresolved; b.style.display = unresolved ? 'block' : 'none';
    d.alerts.forEach(a => { const h = parseInt((a.time || '0').split(':')[0]); if (!isNaN(h)) aPerHr[h]++; });
    renderTl(d.alerts.slice(0, 8));
    if (curPage === 'alerts') renderAlertsList();
  }
  document.getElementById('stPersons').textContent = d.persons || 0;
  document.getElementById('hudFps').textContent = (d.fps || 0) + ' FPS';
  document.getElementById('hudPersons').textContent = (d.persons || 0) + ' persons';
  document.getElementById('monFps').textContent = (d.fps || 0) + ' FPS';
  document.getElementById('anTotal').textContent = alertsData.length;
  document.getElementById('anHigh').textContent = alertsData.filter(a => (a.events || []).some(e => e.includes('HIGH'))).length;
  document.getElementById('anPeak').textContent = peakRisk > 0 ? Math.round(peakRisk) : '—';
  const avg = alertsData.length ? Math.round(alertsData.reduce((s, a) => s + (a.score || 0), 0) / alertsData.length) : 0;
  document.getElementById('anAvg').textContent = avg;
  if (curPage === 'analytics') updateCharts();
  document.getElementById('stZones').textContent = zones.length;
  document.getElementById('setZones').textContent = zones.length;
}

function getRs(evts) {
  const o = [];
  evts.forEach(e => {
    if (e.includes('entered HIGH')) o.push('Person entered restricted area');
    else if (e.includes('PACING')) o.push('Person pacing back and forth');
    else if (e.includes('CROUCH')) o.push('Person crouching in zone');
    else if (e.includes('FROZE')) o.push('Person froze suddenly');
    else if (e.includes('circling')) o.push('Person repeatedly returning');
    else if (e.includes('linger')) o.push('Person lingering too long');
    else if (e.includes('RUNNING')) o.push('Person running in zone');
    else if (e.includes('TAMPER')) o.push('Camera tamper detected');
  });
  return [...new Set(o)];
}

function renderTl(alerts) {
  const el = document.getElementById('dashTl');
  if (!alerts.length) { el.innerHTML = '<div class="empty-msg">No alerts yet</div>'; return; }
  el.innerHTML = alerts.map((a, i) => {
    const isH = (a.events || []).some(e => e.includes('HIGH')), isT = (a.events || []).some(e => e.includes('TAMPER'));
    const desc = getRs(a.events || [])[0] || 'Suspicious activity', tl = isT ? 'TAMPER' : isH ? 'HIGH' : 'OBS';
    const isR = a.resolved;
    return `<div class="tl-item ${isH || isT ? '' : 'obs'}" onclick="openEvidence(${i})" style="${isR ? 'opacity:0.7' : ''}">
      <div class="tl-top"><span class="tl-type ${isH || isT ? 'h' : 'o'}" style="${isR ? 'background:var(--green-bg);color:var(--green)' : ''}">${isR ? '✓ ' + tl : tl}</span><span class="tl-time">${a.time}</span></div>
      <div class="tl-desc">${desc}</div>
      <div class="tl-score">Score <em>${a.score}</em></div>
    </div>`;
  }).join('');
}

function showBanner(t, s) { document.getElementById('abTitle').textContent = t; document.getElementById('abSub').textContent = s; document.getElementById('alertBanner').classList.add('on'); }
function dismissBanner() { dismissed = true; document.getElementById('alertBanner').classList.remove('on'); }
function demoAlert() {
  playAlertSound('alert');
  showBanner('HIGH ZONE BREACH — DEMO', 'Risk Score: 100 · Demo mode');
  ['riskNum', 'monRiskNum'].forEach(id => { const e = document.getElementById(id); if (e) { e.textContent = '100'; e.style.color = '#ef4444'; } });
  ['riskFill', 'monRiskFill'].forEach(id => { const e = document.getElementById(id); if (e) { e.style.width = '100%'; e.style.background = '#ef4444'; } });
  ['riskBadge', 'monBadge'].forEach(id => { const e = document.getElementById(id); if (e) { e.className = 'risk-badge crit'; e.textContent = '● CRITICAL'; } });
  document.getElementById('levelPill').className = 'level-pill lv-crit';
  document.getElementById('levelPill').textContent = '● CRITICAL';
  document.getElementById('riskDot').className = 'risk-ind c';
  document.getElementById('notifPip').classList.add('on');
}
function demoTamper() { playAlertSound('tamper'); showBanner('CAMERA TAMPER DETECTED — DEMO', 'Obstruction simulated · ' + new Date().toTimeString().slice(0, 8)); }

function filterAlerts(f, btn) {
  afilt = f; document.querySelectorAll('.fbt').forEach(b => b.classList.remove('sel')); btn.classList.add('sel'); renderAlertsList();
}
function renderAlertsList() {
  const el = document.getElementById('alertsList');
  let data = alertsData;
  if (afilt !== 'all') data = data.filter(a => {
    const ev = a.events || [];
    if (afilt === 'RESOLVED') return a.resolved;
    if (afilt === 'HIGH') return ev.some(e => e.includes('HIGH'));
    if (afilt === 'TAMPER') return ev.some(e => e.includes('TAMPER'));
    if (afilt === 'OBSERVATION') return !ev.some(e => e.includes('HIGH') || e.includes('TAMPER'));
    return true;
  });
  if (!data.length) { el.innerHTML = '<div class="empty-msg" style="padding:60px 0;">No alerts match this filter</div>'; return; }
  el.innerHTML = data.map(a => {
    const isH = (a.events || []).some(e => e.includes('HIGH')), isT = (a.events || []).some(e => e.includes('TAMPER'));
    const reasons = getRs(a.events || []), tl = isT ? 'TAMPER' : isH ? 'HIGH' : 'OBSERVATION', idx = alertsData.indexOf(a);
    return `<div class="alert-card ${isT ? 'tamper' : isH ? '' : 'obs'}">
      <div class="ac-top">
        <div class="ac-meta"><div class="ac-type ${isH || isT ? '' : 'o'}">${tl} — ${isT ? 'Camera Tampered' : isH ? 'Intrusion' : 'Suspicious Behaviour'}</div><div class="ac-desc">${reasons[0] || 'Suspicious activity detected'}</div></div>
        <div class="ac-time">${a.time}</div><div class="ac-score">${a.score}</div>
      </div>
      <div class="ac-bot">
        <div class="ac-tags">${reasons.map(r => `<span class="ac-tag">${r}</span>`).join('')}</div>
        <button class="view-ev" onclick="openEvidence(${idx})">View Evidence</button>
      </div>
    </div>`;
  }).join('');
}

function fmtTs(raw) {
  const m = raw.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!m) return raw;
  let h = parseInt(m[4]); const min = m[5], sec = m[6], ap = h >= 12 ? 'PM' : 'AM'; h = h % 12 || 12;
  return `${m[3]}/${m[2]}/${m[1]} ${h}:${min}:${sec} ${ap}`;
}
function refreshEvIfOpen() { if (curPage === 'evidence') loadEvidence(); }
async function loadEvidence() {
  const g = document.getElementById('evGrid'); g.innerHTML = '<div class="ev-empty">Loading…</div>';
  try {
    const r = await fetch('/list_evidence'); const d = await r.json();
    if (!d.files || !d.files.length) { g.innerHTML = '<div class="ev-empty">No evidence yet — alerts auto-save here</div>'; return; }
    const clips = d.files.filter(f => f.name.endsWith('.mp4'));
    const images = d.files.filter(f => !f.name.endsWith('.mp4'));
    const rc = f => {
      const isT = f.name.includes('pretamper'), isV = f.name.endsWith('.mp4');
      const badge = isT ? 'tamper' : 'alert', bt = isT ? 'TAMPER' : 'ALERT';
      const thumb = isV
        ? `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:28px;background:var(--bg2)">🎬</div>`
        : `<img src="/snapshots/${f.name}?t=${Date.now()}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:var(--bg2);font-size:28px>📷</div>'">`;
      const ts = fmtTs(f.name.replace(/^(alert_|pretamper_)/, '').replace(/\.(jpg|mp4)$/, ''));
      return `<div class="ev-card" onclick="openFile('${f.name}')">
        <div class="ev-thumb">${thumb}<div class="ev-play">${isV ? '▶' : '🔍'}</div><span class="ev-badge ${badge}">${bt}</span></div>
        <div class="ev-info"><div class="ev-name">${isT ? 'Tamper Clip' : 'Alert Snapshot'}</div><div class="ev-ts">${ts}</div></div>
      </div>`;
    };
    g.innerHTML = `<div class="ev-sect">🎬 Video Clips (${clips.length})</div>${clips.length ? clips.map(rc).join('') : '<div class="ev-empty" style="grid-column:1/-1;padding:12px 0;">No clips yet</div>'}<div class="ev-sect">📷 Alert Snapshots (${images.length})</div>${images.length ? images.map(rc).join('') : '<div class="ev-empty" style="grid-column:1/-1;padding:12px 0;">No snapshots yet</div>'}`;
  } catch (e) { g.innerHTML = '<div class="ev-empty">Could not load — server starting up</div>'; }
}
function openEvidence(idx) {
  const a = alertsData[idx]; if (!a) return;
  const isT = (a.events || []).some(e => e.includes('TAMPER'));
  if (isT && a.clip) openFile(a.clip); else if (a.snapshot) openFile(a.snapshot);
  else { document.getElementById('modalBg').classList.add('on'); showMErr(); }
}
function openFile(fname) {
  const bg = document.getElementById('modalBg'), img = document.getElementById('mImg'), vid = document.getElementById('mVid'), err = document.getElementById('mErr');
  bg.classList.add('on'); img.style.display = 'none'; vid.style.display = 'none'; err.style.display = 'none';
  document.getElementById('mMeta').textContent = fname;
  if (fname.endsWith('.mp4')) {
    document.getElementById('modalTitle').textContent = 'Tamper Video Clip'; err.style.display = 'block';
    err.innerHTML = `<div style="font-size:28px;margin-bottom:12px;">🎬</div><div style="font-size:13px;font-weight:600;color:var(--txt);margin-bottom:6px;">${fname}</div><div style="font-size:11px;color:var(--txt3);margin-bottom:18px;">Browser cannot play this codec directly</div><a href="/snapshots/${fname}" download="${fname}" style="font-size:12px;font-weight:700;padding:10px 22px;border-radius:12px;border:2px solid var(--blue);color:var(--blue);text-decoration:none;background:var(--blue-bg);">⬇ Download Clip</a>`;
  } else { document.getElementById('modalTitle').textContent = 'Alert Snapshot'; img.style.display = 'block'; img.src = '/snapshots/' + fname + '?t=' + Date.now(); }
}
function showMErr() { document.getElementById('mImg').style.display = 'none'; document.getElementById('mVid').style.display = 'none'; document.getElementById('mErr').style.display = 'block'; }
function closeModal() { document.getElementById('modalBg').classList.remove('on'); document.getElementById('mVid').pause(); document.getElementById('mImg').src = ''; document.getElementById('mVid').src = ''; }

// ═══════════════════════════════════════════════════════
// CHARTS
// ═══════════════════════════════════════════════════════
const cOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#fff', titleColor: '#1a2236', bodyColor: '#4a5568', titleFont: { family: 'Barlow Condensed', size: 12, weight: '800' }, bodyFont: { family: 'DM Mono', size: 11 }, borderColor: 'rgba(0,0,0,0.08)', borderWidth: 1, padding: 10 } }, scales: { x: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { color: '#8a96a8', font: { family: 'DM Mono', size: 9 } } }, y: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { color: '#8a96a8', font: { family: 'DM Mono', size: 9 } } } } };
function initCharts() {
  if (rChart && aChart) { updateCharts(); return; }
  rChart = new Chart(document.getElementById('riskChart'), { type: 'line', data: { labels: [], datasets: [{ data: [], fill: true, borderColor: '#3b7ff5', borderWidth: 2.5, backgroundColor: 'rgba(59,127,245,0.08)', pointRadius: 3, pointBackgroundColor: '#3b7ff5', tension: 0.4 }] }, options: { ...cOpts, scales: { x: { ...cOpts.scales.x }, y: { ...cOpts.scales.y, min: 0, max: 100 } } } });
  aChart = new Chart(document.getElementById('alertChart'), { type: 'bar', data: { labels: Array.from({ length: 24 }, (_, i) => i + ':00'), datasets: [{ data: new Array(24).fill(0), backgroundColor: 'rgba(239,68,68,0.2)', borderColor: '#ef4444', borderWidth: 2, borderRadius: 6 }] }, options: cOpts });
  updateCharts();
}
function updateCharts() {
  if (!rChart || !aChart) return;
  const l = rHist.slice(-30); rChart.data.labels = l.map(p => p.t); rChart.data.datasets[0].data = l.map(p => p.v); rChart.update('none');
  aChart.data.datasets[0].data = [...aPerHr]; aChart.update('none');
}

// ═══════════════════════════════════════════════════════
// ZONE DRAWING
// KEY FIX: Uses real camera frame size from server (camW/camH)
// instead of feedEl.naturalWidth — which returns 0 on MJPEG streams.
// Letterbox offsets computed correctly for object-fit:contain layout.
// ═══════════════════════════════════════════════════════
const canvas = document.getElementById('zoneCanvas'), ctx = canvas.getContext('2d');
const feedEl = document.getElementById('liveFeed'), fa = document.getElementById('feedArea');

function resizeCanvas() { canvas.width = fa.clientWidth; canvas.height = fa.clientHeight; redraw(); }
window.addEventListener('resize', resizeCanvas);
feedEl.addEventListener('load', () => { setTimeout(resizeCanvas, 100); });
setTimeout(resizeCanvas, 300); setTimeout(resizeCanvas, 900);

function toggleDraw() {
  drawMode = !drawMode; const b = document.getElementById('btnDraw'), r = document.getElementById('ztRow');
  b.textContent = drawMode ? 'Drawing…' : 'Draw Zone'; b.classList.toggle('drawing', drawMode);
  r.classList.toggle('on', drawMode); canvas.classList.toggle('draw', drawMode); fa.classList.toggle('cross', drawMode);
}
function setZT(t) {
  zoneType = t;
  document.getElementById('ztHigh').className = 'zt' + (t === 'HIGH' ? ' high' : '');
  document.getElementById('ztObs').className = 'zt' + (t === 'OBSERVATION' ? ' obs' : '');
}
canvas.addEventListener('mousedown', e => {
  if (!drawMode) return;
  const r = canvas.getBoundingClientRect();
  sx = e.clientX - r.left; sy = e.clientY - r.top;
  drawing = true;
});
canvas.addEventListener('mousemove', e => {
  if (!drawing) return;
  const r = canvas.getBoundingClientRect();
  cx = e.clientX - r.left; cy = e.clientY - r.top;
  redraw(); prevZone();
});
canvas.addEventListener('mouseup', e => {
  if (!drawing) return;
  drawing = false;
  const r = canvas.getBoundingClientRect();
  cx = e.clientX - r.left; cy = e.clientY - r.top;
  if (Math.abs(cx - sx) > 20 && Math.abs(cy - sy) > 20) {
    zones.push({ x1: Math.min(sx, cx), y1: Math.min(sy, cy), x2: Math.max(sx, cx), y2: Math.max(sy, cy), type: zoneType });
    document.getElementById('stZones').textContent = zones.length;
    document.getElementById('zbStat').textContent = zones.length + ' zone(s) drawn';
    redraw(); sendZones();
  }
});
function redraw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  zones.forEach((z, i) => {
    const isH = z.type === 'HIGH', col = isH ? '#ef4444' : '#f97316';
    ctx.fillStyle = isH ? 'rgba(239,68,68,0.13)' : 'rgba(249,115,22,0.13)';
    ctx.fillRect(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1);
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.strokeRect(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1);
    ctx.lineWidth = 3; const L = 12;
    [[z.x1, z.y1, 1, 1], [z.x2, z.y1, -1, 1], [z.x1, z.y2, 1, -1], [z.x2, z.y2, -1, -1]].forEach(([px, py, dx, dy]) => {
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + dx * L, py); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px, py + dy * L); ctx.stroke();
    });
    ctx.fillStyle = col; ctx.font = '700 12px Barlow Condensed,sans-serif';
    const lbl = `Z${i + 1} ${z.type}`, tw = ctx.measureText(lbl).width;
    ctx.beginPath(); ctx.roundRect(z.x1, z.y1 - 22, tw + 16, 22, 6); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.fillText(lbl, z.x1 + 8, z.y1 - 6);
  });
}
function prevZone() {
  // FIX: call redraw() first so ghost zones don't accumulate while dragging
  redraw();
  const col = zoneType === 'HIGH' ? '#ef4444' : '#f97316';
  ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  ctx.strokeRect(sx, sy, cx - sx, cy - sy); ctx.setLineDash([]);
  ctx.fillStyle = zoneType === 'HIGH' ? 'rgba(239,68,68,0.07)' : 'rgba(249,115,22,0.07)';
  ctx.fillRect(sx, sy, cx - sx, cy - sy);
}
function clearZones() {
  zones = []; ctx.clearRect(0, 0, canvas.width, canvas.height);
  document.getElementById('stZones').textContent = '0';
  document.getElementById('zbStat').textContent = 'Draw zones then start';
  sendZones(false);
}

// ── COORDINATE MAPPING ──────────────────────────────────
// Feed uses object-fit:contain → compute letterbox offsets.
// camW/camH = real camera frame dimensions from server.
// Canvas pixel → camera pixel: subtract letterbox offset, then scale.
function getLetterbox() {
  const cW = canvas.width, cH = canvas.height;
  const ar = camW / camH, bar = cW / cH;
  let rW, rH, oX, oY;
  if (ar > bar) { rW = cW; rH = cW / ar; oX = 0; oY = (cH - rH) / 2; }
  else { rH = cH; rW = cH * ar; oX = (cW - rW) / 2; oY = 0; }
  return { rW, rH, oX, oY };
}
function sendZones(mon) {
  if (mon === undefined) mon = monitoring;
  const { rW, rH, oX, oY } = getLetterbox();
  const scX = camW / rW, scY = camH / rH;
  const sc = zones.map(z => {
    // The feed is CSS-flipped (scaleX(-1)) but Python sees the real unflipped frame.
    // Mirror the canvas X coords before sending so zones align with Python's frame.
    const rx1 = canvas.width - z.x2, rx2 = canvas.width - z.x1;
    return [
      Math.max(0, Math.round((rx1 - oX) * scX)),
      Math.max(0, Math.round((z.y1 - oY) * scY)),
      Math.min(camW, Math.round((rx2 - oX) * scX)),
      Math.min(camH, Math.round((z.y2 - oY) * scY))
    ];
  });
  socket.emit('set_zones', { zones: sc, types: zones.map(z => z.type === 'HIGH' ? 'HIGH' : 'WATCH'), monitoring: mon });
}
function startMonitoring() {
  if (!zones.length) { document.getElementById('zbStat').textContent = '⚠ Draw a zone first'; return; }
  monitoring = true; sendZones(true);
  const b = document.getElementById('btnStart'); b.textContent = '■ Active'; b.classList.add('active');
  document.getElementById('zbStat').textContent = 'AI detection running';
  if (drawMode) toggleDraw();
}
function feedErr() { document.getElementById('feedOffline').classList.add('on'); }
function feedOk() {
  document.getElementById('feedOffline').classList.remove('on');
  // Fallback: grab natural dims if server hasn't sent them yet
  if (!camDimsReady && feedEl.naturalWidth > 0) {
    camW = feedEl.naturalWidth; camH = feedEl.naturalHeight; camDimsReady = true;
  }
}
function tick() {
  const t = new Date().toTimeString().slice(0, 8);
  document.getElementById('topClock').textContent = t;
  document.getElementById('hudClock').textContent = t;
  const s = Math.floor((Date.now() - t0) / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
  document.getElementById('stUptime').textContent = h > 0 ? h + 'h ' + (m % 60) + 'm' : m + 'm';
}
setInterval(tick, 1000); tick();

// ═══════════════════════════════════════════════════════
// ALERT SOUND — Web Audio API (no file needed)
// Two sounds: sharp alert beep for intrusions, lower tone for tamper
// ═══════════════════════════════════════════════════════
let audioCtx = null;
function getAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function playAlertSound(type = 'alert') {
  try {
    const ctx = getAudioCtx();
    const now = ctx.currentTime;

    if (type === 'alert') {
      // Three sharp rising beeps — urgent, attention-grabbing
      [0, 0.22, 0.44].forEach((offset, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'square';
        osc.frequency.setValueAtTime(880 + i * 220, now + offset);
        gain.gain.setValueAtTime(0, now + offset);
        gain.gain.linearRampToValueAtTime(0.35, now + offset + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.18);
        osc.start(now + offset);
        osc.stop(now + offset + 0.2);
      });
    } else if (type === 'tamper') {
      // Low pulsing tone — different from alert so you know it's tamper
      [0, 0.3, 0.6].forEach(offset => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(220, now + offset);
        gain.gain.setValueAtTime(0, now + offset);
        gain.gain.linearRampToValueAtTime(0.3, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.25);
        osc.start(now + offset);
        osc.stop(now + offset + 0.28);
      });
    }
  } catch (e) {
    console.warn('[SOUND] Audio error:', e);
  }
}

// Track last alert state to avoid repeating sound every socket tick
let _lastAlertState = false;
function maybePlayAlert(alertActive, isTamper) {
  if (isTamper && !_lastAlertState) {
    playAlertSound('tamper');
    _lastAlertState = true;
  } else if (alertActive && !_lastAlertState) {
    playAlertSound('alert');
    _lastAlertState = true;
  } else if (!alertActive && !isTamper) {
    _lastAlertState = false;
  }
}