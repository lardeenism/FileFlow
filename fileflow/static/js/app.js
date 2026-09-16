"use strict";

const page = document.body.dataset.page;
const maxUploadBytes = Number(document.body.dataset.maxUploadBytes || 0);
const maxUploadLabel = document.body.dataset.maxUploadLabel || "configured limit";
const defaultDocumentTitle = document.title;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

function niceTime(value, withDate = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return withDate ? date.toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", second:"2-digit"}) : date.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
}
function fileSize(bytes) {
  let value = Number(bytes || 0); const units = ["B", "KB", "MB", "GB"]; let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${unit ? value.toFixed(1) : value.toFixed(0)} ${units[unit]}`;
}
function extension(name) { return (String(name).split(".").pop() || "FILE").slice(0,4).toUpperCase(); }
function durationLabel(worker) {
  if (!worker.start_time) return "—";
  return elapsedLabel(worker.start_time, worker.completion_time);
}
function elapsedLabel(startValue, endValue) {
  if (!startValue) return "—";
  const start = new Date(startValue).getTime();
  const end = endValue ? new Date(endValue).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  return `${Math.max(0, (end - start) / 1000).toFixed(1)}s`;
}
let lastToast = {message: "", time: 0};
function toast(message, type = "info", title = type === "error" ? "Action failed" : "FileFlow") {
  const stack = $("#toastStack"); if (!stack) return;
  const now = Date.now();
  if (message === lastToast.message && now - lastToast.time < 3000) return;
  lastToast = {message, time: now};
  const item = document.createElement("div"); item.className = `toast ${type}`;
  item.innerHTML = `<strong>${esc(title)}</strong><p>${esc(message)}</p>`; stack.append(item);
  setTimeout(() => item.remove(), 4500);
}
async function api(url, options = {}) {
  const response = await fetch(url, options); let data;
  try { data = await response.json(); } catch { data = {message: "The server returned an invalid response."}; }
  if (!response.ok) throw new Error(data.message || `Request failed (${response.status})`);
  return data;
}
function badge(status, extra = "") { const label = status === "processing" ? "running" : status; return `<span class="badge ${esc(status)} ${extra}">${esc(label)}</span>`; }
function progress(value) { const safe = Math.max(0, Math.min(100, Number(value || 0))); return `<div class="table-progress"><div class="progress-track"><i style="width:${safe}%"></i></div><span>${safe}%</span></div>`; }

function workerMarkup(worker, compact = false) {
  const status = worker.status || "idle"; const number = String(worker.worker_id).padStart(2, "0");
  if (compact) return `<article class="compact-worker ${esc(status)}"><header><b>WORKER ${number}</b><i class="status-dot"></i></header><div class="file">${esc(worker.current_file || "Waiting for task")}</div><div class="thread">TID ${esc(worker.thread_id || "not started")}</div><div class="progress-track"><i style="width:${Number(worker.progress || 0)}%"></i></div><div class="worker-progress-label"><span>${esc(status.toUpperCase())}</span><span>${Number(worker.progress || 0)}%</span></div></article>`;
  return `<article class="thread-card ${esc(status)}" aria-label="Worker ${number}, ${esc(status)}"><header><div><h3>Worker ${number}</h3><small class="worker-throughput">${Number(worker.processed || 0)} file${Number(worker.processed || 0) === 1 ? "" : "s"} completed</small></div><span class="thread-state"><i class="status-dot"></i>${esc(status.toUpperCase())}</span></header><div class="thread-id"><small>NATIVE OS THREAD ID</small><strong>${esc(worker.thread_id || "Waiting to start")}</strong></div><div class="thread-field"><small>CURRENT FILE</small><div class="thread-file">${esc(worker.current_file || "No file assigned")}</div></div><div class="progress-track"><i style="width:${Number(worker.progress || 0)}%"></i></div><div class="worker-progress-label"><span>PROGRESS</span><span>${Number(worker.progress || 0)}%</span></div><div class="thread-times"><span>START<br>${esc(niceTime(worker.start_time))}</span><span>DURATION<br>${esc(durationLabel(worker))}</span><span>COMPLETE<br>${esc(niceTime(worker.completion_time))}</span></div></article>`;
}

function renderEngineWorkers(workers) {
  const orbit = $("#heroWorkerOrbit");
  const lines = $("#heroFlowLines");
  if (!orbit || !lines) return;

  const count = Math.max(1, Math.min(12, workers?.length || 5));
  if (orbit.dataset.workerCount === String(count)) return;
  orbit.dataset.workerCount = String(count);
  $$('[data-orbit-worker]', orbit).forEach(node => node.remove());

  const workerNodes = [];
  const flowNodes = [];
  for (let index = 0; index < count; index++) {
    const orbitAngle = -90 + (360 * index / count);
    const radians = orbitAngle * Math.PI / 180;
    const x = 50 + 50 * Math.cos(radians);
    const y = 50 + 50 * Math.sin(radians);
    workerNodes.push(`<span data-orbit-worker style="--orbit-x:${x.toFixed(2)}%;--orbit-y:${y.toFixed(2)}%">W${index + 1}</span>`);

    const flowAngle = count === 1 ? 0 : -24 + (48 * index / (count - 1));
    flowNodes.push(`<i style="--flow-angle:${flowAngle.toFixed(2)}deg"></i>`);
  }
  orbit.insertAdjacentHTML("beforeend", workerNodes.join(""));
  lines.innerHTML = flowNodes.join("");
}
function updateGlobal(data) {
  const {stats, processing} = data;
  $$('[data-stat]').forEach(node => node.textContent = stats[node.dataset.stat] ?? 0);
  if ($("#navQueueCount")) $("#navQueueCount").textContent = stats.pending;
  if ($("#sidebarWorkers")) $("#sidebarWorkers").textContent = processing.workers.length;
  renderEngineWorkers(processing.workers);
  if ($("#sidebarStatus")) $("#sidebarStatus").textContent = processing.active ? "Processing active" : (processing.message === "ALL FILES PROCESSED!" ? processing.message : "System ready");
  if ($("#sidebarMeter")) {
    const total = processing.completed_in_batch + processing.failed_in_batch + stats.pending + stats.active_workers;
    const done = processing.completed_in_batch + processing.failed_in_batch;
    $("#sidebarMeter").style.width = `${processing.active && total ? (done / total) * 100 : (processing.message === "ALL FILES PROCESSED!" ? 100 : 0)}%`;
  }
  if ($("#heroQueue")) $("#heroQueue").textContent = stats.pending;
  if ($("#dashboardWorkers")) $("#dashboardWorkers").innerHTML = processing.workers.map(w => workerMarkup(w, true)).join("");
  if ($("#threadGrid")) $("#threadGrid").innerHTML = processing.workers.map(w => workerMarkup(w)).join("");
  if ($("#workerPoolSummary")) $("#workerPoolSummary").textContent = processing.active ? `${stats.active_workers} running · ${processing.workers.length} configured` : `${processing.workers.length} configured · ready for the next batch`;
  if ($("#completionOrder")) {
    $("#completionOrder").innerHTML = processing.completion_order.length ? processing.completion_order.map(item => `<div class="finish-item ${esc(item.status)}"><b>#${item.rank}</b><div><strong>${esc(item.status === "completed" ? "✓" : "!")} Worker ${String(item.worker_id).padStart(2,"0")} ${esc(item.status)} ${esc(item.filename)}</strong><small>TID ${esc(item.thread_id || "—")} · ${Number(item.duration_seconds || 0).toFixed(3)}s</small></div><span>${esc(niceTime(item.completed_at))}</span></div>`).join("") : `<div class="empty-state">Worker completions will appear here in real time.</div>`;
  }
  const summary = processing.summary || {total:0,completed:0,running:0,pending:0,failed:0,progress:0};
  const hasBatch = summary.total > 0;
  if ($("#batchEmpty")) $("#batchEmpty").hidden = hasBatch;
  if ($("#batchMetrics")) $("#batchMetrics").hidden = !hasBatch;
  if ($("#batchContext")) $("#batchContext").textContent = processing.active ? `${summary.total} file${summary.total === 1 ? "" : "s"} processing now` : `Last run · ${summary.completed} completed${summary.failed ? ` · ${summary.failed} failed` : ""}`;
  if ($("#batchTotal")) $("#batchTotal").textContent = summary.total;
  if ($("#batchCompleted")) $("#batchCompleted").textContent = summary.completed;
  if ($("#batchRunning")) $("#batchRunning").textContent = summary.running;
  if ($("#batchPending")) $("#batchPending").textContent = summary.pending;
  if ($("#batchFailed")) $("#batchFailed").textContent = summary.failed;
  if ($("#batchProgressLabel")) $("#batchProgressLabel").textContent = `${summary.progress}%`;
  if ($("#batchProgressBar")) $("#batchProgressBar").style.width = `${summary.progress}%`;
  $("#batchProgressBar")?.parentElement?.setAttribute("aria-valuenow", String(summary.progress));
  if ($("#monitorHeadline")) $("#monitorHeadline").textContent = processing.active ? "Concurrent file processing active" : processing.message;
  if ($("#monitorSubline")) $("#monitorSubline").textContent = processing.active ? `${summary.running} worker thread(s) running · ${summary.pending} batch task(s) waiting.` : (stats.pending ? `${stats.pending} queued file(s) ready to run.` : "No queued work. Add files to begin.");
  if ($("#monitorFreshness")) $("#monitorFreshness").textContent = `LIVE · ${new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"})}`;
  if ($("#queuePending")) $("#queuePending").textContent = stats.pending;
  if ($("#queueActive")) $("#queueActive").textContent = stats.active_workers;
  if ($("#queueCompleted")) $("#queueCompleted").textContent = stats.processed;

  if ($("#recentActivity")) {
    $("#recentActivity").innerHTML = data.logs.length ? data.logs.slice(0, 7).map(log => `<div class="activity-item"><span>${log.level === "success" ? "✓" : log.level === "error" ? "!" : "↗"}</span><div><p>${esc(log.message)}</p><small>${esc(log.event_type.toUpperCase())} · ${esc(niceTime(log.created_at))}</small></div></div>`).join("") : `<div class="empty-state">No activity yet.</div>`;
  }
  if ($("#dashboardLogs")) {
    $("#dashboardLogs").innerHTML = data.logs.length ? [...data.logs].reverse().map(log => `<p><span class="log-time">[${esc(niceTime(log.created_at))}]</span> <span class="log-worker">${log.worker_id ? `worker-${String(log.worker_id).padStart(2,"0")}` : "system"}</span> <span class="log-${esc(log.level)}">${esc(log.message)}</span></p>`).join("") : `<p class="muted">$ FileFlow is ready. Upload files or start the demo.</p>`;
    $("#dashboardLogs").scrollTop = $("#dashboardLogs").scrollHeight;
  }
  $$('[data-action="demo"]').forEach(button => button.disabled = processing.active);
  $$('[data-action="process"]').forEach(button => {
    if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.innerHTML;
    button.disabled = processing.active || stats.pending === 0;
    button.innerHTML = processing.active ? "◌ Processing…" : button.dataset.defaultLabel;
    button.title = processing.active ? "A worker batch is already active" : (stats.pending ? `Run ${stats.pending} pending file(s)` : "No pending files");
  });
  $$('.run-task').forEach(button => button.disabled = processing.active);
  if (page === "threads") document.title = processing.active ? `(${summary.running}) Processing · FileFlow` : defaultDocumentTitle;
}

const statusCacheKey = "fileflow-last-status";
let lastStatus = null;
try {
  const cachedStatus = JSON.parse(sessionStorage.getItem(statusCacheKey) || "null");
  if (cachedStatus && Date.now() - cachedStatus.savedAt < 10000) {
    lastStatus = cachedStatus.data;
    updateGlobal(lastStatus);
  }
} catch {
  sessionStorage.removeItem(statusCacheKey);
}
async function pollStatus() {
  try {
    lastStatus = await api("/api/status");
    sessionStorage.setItem(statusCacheKey, JSON.stringify({savedAt: Date.now(), data: lastStatus}));
    updateGlobal(lastStatus);
  } catch (error) { console.error(error); }
  setTimeout(pollStatus, lastStatus?.processing?.active ? 700 : 2200);
}

async function startAction(kind, source, taskIds = null) {
  source.disabled = true;
  let started = false;
  try {
    const options = {method:"POST"};
    if (kind === "process" && taskIds) {
      options.headers = {"Content-Type":"application/json"};
      options.body = JSON.stringify({task_ids: taskIds});
    }
    const result = await api(kind === "demo" ? "/api/demo/start" : "/api/process/start", options);
    started = true;
    toast(result.message, "success", kind === "demo" ? "Demo started" : "Workers started");
    if (kind === "process" && page !== "threads") {
      sessionStorage.setItem("fileflow-monitor-message", result.message);
      if (window.FileFlowNavigation) window.FileFlowNavigation.navigate("/threads");
      else window.location.assign("/threads");
      return;
    }
    pollPageData();
    try {
      const freshStatus = await api("/api/status");
      lastStatus = freshStatus;
      updateGlobal(freshStatus);
    } catch (statusError) { console.error(statusError); }
  } catch (error) { toast(error.message, "error"); }
  finally { if (!started) source.disabled = false; }
}
$$('[data-action="demo"]').forEach(button => button.addEventListener("click", () => startAction("demo", button)));
$$('[data-action="process"]').forEach(button => button.addEventListener("click", () => startAction("process", button)));

function uploadRequest(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
    });
    xhr.addEventListener("load", () => {
      const data = xhr.response || {message: "The server returned an invalid response."};
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.message || `Upload failed (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("Upload failed because the server connection was interrupted.")));
    xhr.addEventListener("abort", () => reject(new Error("Upload was cancelled.")));
    xhr.send(form);
  });
}

function uploadNotice(files, totalBytes) {
  const stack = $("#toastStack");
  const item = document.createElement("div");
  item.className = "toast upload-toast";
  item.innerHTML = `<strong>Uploading ${files.length} file(s)</strong><p>${esc(fileSize(totalBytes))} total</p><div class="progress-track"><i></i></div><small>0%</small>`;
  stack?.append(item);
  const feedback = $("#uploadFeedback");
  if (feedback) feedback.hidden = false;
  return {
    update(percent) {
      $("i", item).style.width = `${percent}%`;
      $("small", item).textContent = `${percent}%`;
      if ($("#uploadFeedbackBar")) $("#uploadFeedbackBar").style.width = `${percent}%`;
      if ($("#uploadFeedbackPercent")) $("#uploadFeedbackPercent").textContent = `${percent}%`;
      if ($("#uploadFeedbackText")) $("#uploadFeedbackText").textContent = percent < 100 ? `Uploading ${files.length} file(s)…` : "Upload received · creating queue tasks…";
    },
    remove() {
      item.remove();
      if (feedback) feedback.hidden = true;
    },
  };
}

async function uploadFiles(files) {
  if (!files?.length) return;
  const selected = [...files];
  if (selected.length > 100) {
    toast("Choose no more than 100 files in one request.", "error", "Too many files");
    $$('#dashboardUpload, #monitorUpload, #fileInput').forEach(input => { input.value = ""; });
    return;
  }
  const totalBytes = selected.reduce((total, file) => total + Number(file.size || 0), 0);
  if (maxUploadBytes && totalBytes > maxUploadBytes) {
    toast(`Selected files total ${fileSize(totalBytes)}. The request limit is ${maxUploadLabel}.`, "error", "Upload too large");
    $$('#dashboardUpload, #monitorUpload, #fileInput').forEach(input => { input.value = ""; });
    return;
  }
  const form = new FormData(); selected.forEach(file => form.append("files", file));
  const notice = uploadNotice(selected, totalBytes);
  try {
    const result = await uploadRequest(form, percent => notice.update(percent));
    notice.update(100);
    toast(result.message, result.rejected?.length ? "info" : "success", "Upload complete");
    pollPageData();
    api("/api/status").then(data => { lastStatus = data; updateGlobal(data); }).catch(() => {});
  } catch (error) { toast(error.message, "error", "Upload failed"); }
  finally {
    window.setTimeout(() => notice.remove(), 350);
    $$('#dashboardUpload, #monitorUpload, #fileInput').forEach(input => { input.value = ""; });
  }
}

function initUploads() {
  const dashboardInput = $("#dashboardUpload"); if (dashboardInput) dashboardInput.addEventListener("change", event => uploadFiles(event.target.files));
  const monitorInput = $("#monitorUpload"); if (monitorInput) monitorInput.addEventListener("change", event => uploadFiles(event.target.files));
  const input = $("#fileInput"), browse = $("#browseButton"), zone = $("#dropZone");
  if (!input || !zone) return;
  browse.addEventListener("click", () => input.click()); input.addEventListener("change", e => uploadFiles(e.target.files));
  ["dragenter","dragover"].forEach(name => zone.addEventListener(name, e => {e.preventDefault(); zone.classList.add("dragover");}));
  ["dragleave","drop"].forEach(name => zone.addEventListener(name, e => {e.preventDefault(); zone.classList.remove("dragover");}));
  zone.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
}

let cachedFiles = [];
const organizedFolders = ["Images", "Documents", "Spreadsheets", "Presentations", "Videos", "Audio", "Archives", "Others", "Duplicates"];
const folderIcons = {Images:"IMG", Documents:"DOC", Spreadsheets:"XLS", Presentations:"PPT", Videos:"VID", Audio:"AUD", Archives:"ZIP", Others:"···", Duplicates:"DUP"};
function displayCategory(file) { return file.is_duplicate ? "Duplicates" : (file.category || "Others"); }
function renderFolderSummary() {
  const summary = $("#folderSummary"); if (!summary) return;
  const counts = Object.fromEntries(organizedFolders.map(folder => [folder, 0]));
  cachedFiles.forEach(file => counts[displayCategory(file)]++);
  summary.innerHTML = organizedFolders.map(folder => `<div class="folder-tile"><span>${folderIcons[folder]}</span><div><strong>${esc(folder)}</strong><small>${counts[folder]} file${counts[folder] === 1 ? "" : "s"}</small></div></div>`).join("");
}
function renderFiles() {
  const body = $("#filesTable"); if (!body) return;
  renderFolderSummary();
  const filter = $("#fileSearch")?.value.trim().toLowerCase() || "";
  const category = $("#categoryFilter")?.value || "all";
  const status = $("#statusFilter")?.value || "all";
  const rows = cachedFiles
    .filter(file => file.original_filename.toLowerCase().includes(filter))
    .filter(file => category === "all" || displayCategory(file) === category)
    .filter(file => status === "all" || file.status === status)
    .sort((left, right) => organizedFolders.indexOf(displayCategory(left)) - organizedFolders.indexOf(displayCategory(right)) || left.original_filename.localeCompare(right.original_filename));
  if ($("#fileResultsCount")) $("#fileResultsCount").textContent = `Showing ${rows.length} of ${cachedFiles.length} files`;
  body.innerHTML = rows.length ? rows.map(file => `<tr><td><div class="file-cell"><span class="file-type-icon">${esc(extension(file.original_filename))}</span>${esc(file.original_filename)}</div></td><td>${badge(file.is_duplicate ? "duplicate" : file.category || "Others")}</td><td>${fileSize(file.size)}</td><td class="hash">${esc(file.short_hash || "pending")}</td><td>${badge(file.status)}</td><td><span class="hash">${file.worker_id ? `W${String(file.worker_id).padStart(2,"0")} / ${file.thread_id}` : "unassigned"}</span></td><td><div class="table-actions">${file.status === "completed" ? `<a class="table-action" title="Download" href="/api/files/${file.id}/download">↓</a>` : ""}<button class="table-action delete-file" data-id="${file.id}" title="Delete">×</button></div></td></tr>`).join("") : `<tr><td colspan="7"><div class="empty-state">${cachedFiles.length ? "No files match the current filters." : "No files found. Drop files above to begin."}</div></td></tr>`;
  $$(".delete-file", body).forEach(button => button.addEventListener("click", async () => {
    if (!confirm("Delete this file and its processing record?")) return;
    try { const result = await api(`/api/files/${button.dataset.id}`, {method:"DELETE"}); toast(result.message,"success"); loadFiles(); } catch(error){toast(error.message,"error");}
  }));
}
async function loadFiles() { if (!$("#filesTable")) return; try { cachedFiles = (await api("/api/files")).files; renderFiles(); } catch(error){toast(error.message,"error");} }

async function loadTasks() {
  const body = $("#tasksTable"), monitorBody = $("#monitorPendingTasks");
  if (!body && !monitorBody) return;
  try {
    const tasks = (await api("/api/tasks")).tasks;
    if ($("#taskResultsCount")) {
      const pendingCount = tasks.filter(task => task.status === "pending").length;
      const runningCount = tasks.filter(task => task.status === "processing").length;
      $("#taskResultsCount").textContent = `${pendingCount} pending · ${runningCount} running`;
    }
    if (body) {
      const queuedTasks = tasks.filter(task => task.status === "pending" || task.status === "processing");
      body.innerHTML = queuedTasks.length ? queuedTasks.map(task => `<tr><td class="hash">#${task.id}</td><td><div class="file-cell"><span class="file-type-icon">${esc(extension(task.original_filename))}</span>${esc(task.original_filename)}</div></td><td>${task.worker_id ? `Worker ${String(task.worker_id).padStart(2,"0")}` : "—"}</td><td>${progress(task.progress)}</td><td>${badge(task.status)}</td><td>${esc(niceTime(task.queued_at,true))}</td><td>${task.status === "pending" ? `<button class="button button-primary button-small run-task" data-task-id="${task.id}">Run</button>` : ""}</td></tr>`).join("") : `<tr><td colspan="7"><div class="empty-state">No queued or running tasks. Completed work is available in History.</div></td></tr>`;
      $$(".run-task", body).forEach(button => button.addEventListener("click", () => startAction("process", button, [Number(button.dataset.taskId)])));
    }
    if (monitorBody) {
      const pending = tasks.filter(task => task.status === "pending");
      monitorBody.innerHTML = pending.length ? pending.map(task => `<tr><td class="hash">#${task.id}</td><td><div class="file-cell"><span class="file-type-icon">${esc(extension(task.original_filename))}</span>${esc(task.original_filename)}</div></td><td>${badge("pending")}</td><td>${esc(niceTime(task.queued_at,true))}</td><td><button class="button button-primary button-small run-task" data-task-id="${task.id}">Run</button></td></tr>`).join("") : `<tr><td colspan="5"><div class="empty-state">No pending files. Add files to create a new queue.</div></td></tr>`;
      $$(".run-task", monitorBody).forEach(button => button.addEventListener("click", () => startAction("process", button, [Number(button.dataset.taskId)])));
      if (lastStatus?.processing?.active) $$(".run-task", monitorBody).forEach(button => button.disabled = true);
    }
  } catch(error){toast(error.message,"error");}
}
let cachedHistory = [];
async function loadHistory() {
  const body = $("#historyTable"); if (!body) return;
  try { cachedHistory = (await api("/api/history")).history; if ($("#historyResultsCount")) $("#historyResultsCount").textContent = `${cachedHistory.length} completed task${cachedHistory.length === 1 ? "" : "s"}`; if ($("#exportHistory")) { $("#exportHistory").disabled = cachedHistory.length === 0; $("#exportHistory").title = cachedHistory.length ? "Download processing history as CSV" : "No history to export"; } body.innerHTML = cachedHistory.length ? cachedHistory.map(item => `<tr><td><div class="file-cell"><span class="file-type-icon">${esc(extension(item.original_filename))}</span>${esc(item.original_filename)}</div></td><td>${item.is_duplicate ? badge("duplicate") : badge(item.status)}</td><td>${esc(item.category || "Others")}</td><td>${item.worker_id ? `Worker ${String(item.worker_id).padStart(2,"0")}` : "—"}</td><td class="hash">${esc(item.thread_id || "—")}</td><td class="hash">${esc(elapsedLabel(item.started_at,item.completed_at))}</td><td class="hash">${esc(item.short_hash || "—")}</td><td>${esc(niceTime(item.completed_at,true))}</td></tr>`).join("") : `<tr><td colspan="8"><div class="empty-state">No completed tasks yet.</div></td></tr>`; } catch(error){toast(error.message,"error");}
}

let cachedReport = null;
async function loadReports() {
  if (!$("#categoryReport")) return;
  try {
    cachedReport = await api("/api/reports");
    const summary = cachedReport.summary;
    $("#reportCompleted").textContent = summary.completed;
    $("#reportBytes").textContent = fileSize(summary.completed_bytes);
    $("#reportDuplicates").textContent = `${Number(summary.duplicate_ratio).toFixed(1)}%`;
    $("#reportDuration").textContent = `${Number(summary.average_duration_seconds).toFixed(3)}s`;
    $("#reportFailed").textContent = summary.failed;
    $("#reportTotal").textContent = summary.total_files;
    $("#reportGenerated").textContent = `Generated ${niceTime(cachedReport.generated_at, true)} from persisted Supabase PostgreSQL records`;
    $("#reportScope").textContent = cachedReport.scope_note;
    const categoryMax = Math.max(1, ...cachedReport.categories.map(item => item.file_count));
    $("#categoryReport").innerHTML = cachedReport.categories.length ? cachedReport.categories.map(item => `<div class="report-bar"><div><strong>${esc(item.category)}</strong><span>${item.file_count} file${item.file_count === 1 ? "" : "s"} / ${fileSize(item.total_bytes)}</span></div><div class="report-track"><i style="width:${item.file_count * 100 / categoryMax}%"></i></div></div>`).join("") : `<div class="empty-state">No completed files to report yet.</div>`;
    const workerTotal = cachedReport.workers.reduce((sum, item) => sum + item.task_count, 0);
    $("#workerReport").innerHTML = cachedReport.workers.length ? cachedReport.workers.map(item => { const share = workerTotal ? item.task_count * 100 / workerTotal : 0; return `<div class="report-bar"><div><strong>Worker ${String(item.worker_id).padStart(2,"0")}</strong><span>${item.task_count} task${item.task_count === 1 ? "" : "s"} / ${fileSize(item.total_bytes)} / ${share.toFixed(1)}%</span></div><div class="report-track worker"><i style="width:${share}%"></i></div></div>`; }).join("") : `<div class="empty-state">No completed worker tasks to report yet.</div>`;
    $("#exportReport").disabled = false;
  } catch(error) { toast(error.message, "error"); }
}

function initReportActions() {
  $("#printReport")?.addEventListener("click", () => window.print());
  $("#exportReport")?.addEventListener("click", () => {
    if (!cachedReport) return;
    const cell = value => `"${String(value ?? "").replaceAll('"','""')}"`;
    const rows = [
      ["FileFlow Reports & Analytics"],
      ["Generated", cachedReport.generated_at],
      [],
      ["Metric", "Value"],
      ["All uploads", cachedReport.summary.total_files],
      ["Completed files", cachedReport.summary.completed],
      ["Completed bytes", cachedReport.summary.completed_bytes],
      ["Failed files", cachedReport.summary.failed],
      ["Duplicate files", cachedReport.summary.duplicates],
      ["Duplicate ratio percent", cachedReport.summary.duplicate_ratio],
      ["Average duration seconds", cachedReport.summary.average_duration_seconds],
      [], ["Category", "Completed files", "Bytes"],
      ...cachedReport.categories.map(item => [item.category, item.file_count, item.total_bytes]),
      [], ["Worker pool label", "Completed tasks", "Bytes"],
      ...cachedReport.workers.map(item => [item.worker_id, item.task_count, item.total_bytes]),
      [], ["Scope note", cachedReport.scope_note],
    ];
    const csv = rows.map(row => row.map(cell).join(",")).join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], {type:"text/csv;charset=utf-8"}));
    link.download = "fileflow-report.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  });
}

function initConcurrencyQuiz() {
  const form = $("#concurrencyQuiz"); if (!form) return;
  form.addEventListener("submit", event => {
    event.preventDefault();
    let correct = 0;
    $$("fieldset", form).forEach((fieldset, index) => {
      const selected = $("input:checked", fieldset);
      const passed = selected?.value === fieldset.dataset.answer;
      const feedback = $(".quiz-feedback", fieldset);
      fieldset.classList.toggle("correct", passed);
      fieldset.classList.toggle("wrong", !passed);
      if (passed) correct++;
      if (!selected) feedback.textContent = "Choose an answer before checking.";
      else if (index === 0) feedback.textContent = passed ? "Correct. Threads in one process usually keep the same address-space context, so less switching work is required." : "A thread switch is generally lighter. A process switch may also change address-space mappings and cause additional memory/cache effects.";
      else feedback.textContent = passed ? "Correct. Unsynchronized timing-dependent access is a data race; deadlock means participants are stuck waiting for one another." : "This is a data race. Deadlock instead prevents progress because threads wait indefinitely for resources held by each other.";
    });
    toast(`${correct}/2 answers correct.`, correct === 2 ? "success" : "info", "Quiz result");
  });
}

let logLevel = "all";
async function loadLogs() {
  const terminal = $("#logTerminal"); if (!terminal) return;
  try { const logs = (await api(`/api/logs?level=${logLevel}`)).logs; if ($("#logResultsCount")) $("#logResultsCount").textContent = `${logs.length} ${logLevel === "all" ? "recent" : logLevel} event${logs.length === 1 ? "" : "s"}`; terminal.innerHTML = logs.length ? [...logs].reverse().map(log => `<div class="log-line ${esc(log.level)}"><span class="log-time">${esc(niceTime(log.created_at,true))}</span><span class="log-event">${esc(log.event_type)}</span><span class="log-worker">${log.worker_id ? `worker-${String(log.worker_id).padStart(2,"0")}` : "system"}</span><span class="message">${esc(log.message)}</span></div>`).join("") : `<p class="muted">No matching log entries.</p>`; terminal.scrollTop = terminal.scrollHeight; } catch(error){toast(error.message,"error");}
}

function pollPageData() { loadFiles(); loadTasks(); loadHistory(); loadLogs(); loadReports(); }
function initSettings() {
  const form = $("#settingsForm"); if (!form) return;
  const input = $("#workerCount"), output = $("#workerOutput"); input.addEventListener("input", () => output.textContent = input.value);
  api("/api/settings").then(data => { input.value = data.settings.worker_count || 5; output.textContent = input.value; }).catch(error => toast(error.message,"error"));
  form.addEventListener("submit", async event => { event.preventDefault(); const button=$("button[type='submit']",form); const label=button.textContent; button.disabled=true; button.textContent="Saving…"; try { const result = await api("/api/settings", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({worker_count:input.value})}); toast(result.message,"success"); if ($("#sidebarWorkers")) $("#sidebarWorkers").textContent = result.worker_count; } catch(error){toast(error.message,"error");} finally { button.disabled=false; button.textContent=label; } });
  $("#syncDemo").addEventListener("click", async event => { const button=event.currentTarget;button.disabled=true;button.textContent="Running real threads…";try{const {result}=await api("/api/synchronization-demo",{method:"POST"});$("#syncResults").innerHTML=`<div class="result-box"><small>EXPECTED</small><strong>${result.expected}</strong></div><div class="result-box unsafe"><small>UNSAFE / LOST ${result.unsafe_lost}</small><strong>${result.unsafe_actual}</strong></div><div class="result-box safe"><small>LOCK / LOST ${result.safe_lost}</small><strong>${result.safe_actual}</strong></div>`;toast("The Lock preserved every increment; the unsafe counter lost updates.","success","Experiment complete");}catch(error){toast(error.message,"error");}finally{button.disabled=false;button.textContent="Run race condition demo";}});
}
function initHistoryExport(){const button=$("#exportHistory");if(!button)return;button.addEventListener("click",()=>{if(!cachedHistory.length){toast("There is no history to export.","error");return;}const fields=["id","original_filename","status","category","worker_id","thread_id","duration","short_hash","started_at","completed_at"];const cell=value=>`"${String(value??"").replaceAll('"','""')}"`;const value=(row,key)=>key==="duration"?elapsedLabel(row.started_at,row.completed_at):row[key];const csv=[fields.join(","),...cachedHistory.map(row=>fields.map(key=>cell(value(row,key))).join(","))].join("\n");const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));link.download="fileflow-history.csv";link.click();URL.revokeObjectURL(link.href);});}

const sidebar = $("#sidebar");
const menuButton = $("#menuButton");
const sidebarCollapse = $("#sidebarCollapse");
const sidebarBackdrop = $("#sidebarBackdrop");
const mobileSidebar = window.matchMedia("(max-width: 860px)");

function updateSidebarControl() {
  if (!sidebarCollapse) return;
  const collapsed = document.body.classList.contains("sidebar-collapsed");
  const mobile = mobileSidebar.matches;
  $("span", sidebarCollapse).textContent = mobile ? "\u00d7" : (collapsed ? "\u203a" : "\u2039");
  const label = mobile ? "Close navigation" : (collapsed ? "Expand sidebar" : "Collapse sidebar");
  sidebarCollapse.setAttribute("aria-label", label);
  sidebarCollapse.title = label;
}

function setMobileSidebar(open, focusClose = false) {
  if (!sidebar) return;
  const shouldOpen = Boolean(open && mobileSidebar.matches);
  sidebar.classList.toggle("open", shouldOpen);
  document.body.classList.toggle("mobile-sidebar-open", shouldOpen);
  if (mobileSidebar.matches) {
    sidebar.toggleAttribute("inert", !shouldOpen);
    sidebar.setAttribute("aria-hidden", String(!shouldOpen));
  } else {
    sidebar.removeAttribute("inert");
    sidebar.removeAttribute("aria-hidden");
  }
  menuButton?.setAttribute("aria-expanded", String(shouldOpen));
  menuButton?.setAttribute("aria-label", shouldOpen ? "Close navigation" : "Open navigation");
  updateSidebarControl();
  if (shouldOpen && focusClose) window.setTimeout(() => sidebarCollapse?.focus(), 120);
}

function applySidebarState(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  updateSidebarControl();
}

applySidebarState(localStorage.getItem("fileflow-sidebar") === "collapsed");
setMobileSidebar(false);
menuButton?.addEventListener("click", () => setMobileSidebar(!sidebar?.classList.contains("open"), true));
sidebarBackdrop?.addEventListener("click", () => {
  setMobileSidebar(false);
  menuButton?.focus();
});
sidebarCollapse?.addEventListener("click", () => {
  if (mobileSidebar.matches) {
    setMobileSidebar(false);
    menuButton?.focus();
    return;
  }
  const collapsed = !document.body.classList.contains("sidebar-collapsed");
  applySidebarState(collapsed);
  localStorage.setItem("fileflow-sidebar", collapsed ? "collapsed" : "expanded");
});
$$('.nav-item', sidebar || document).forEach(link => link.addEventListener("click", () => setMobileSidebar(false)));
$(".brand", sidebar || document)?.addEventListener("click", () => setMobileSidebar(false));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && sidebar?.classList.contains("open")) {
    setMobileSidebar(false);
    menuButton?.focus();
  }
});
const handleSidebarBreakpoint = () => setMobileSidebar(false);
if (mobileSidebar.addEventListener) mobileSidebar.addEventListener("change", handleSidebarBreakpoint);
else mobileSidebar.addListener(handleSidebarBreakpoint);
$("#fileSearch")?.addEventListener("input", renderFiles);
$("#categoryFilter")?.addEventListener("change", renderFiles);
$("#statusFilter")?.addEventListener("change", renderFiles);
$("#clearFileFilters")?.addEventListener("click", () => {
  $("#fileSearch").value = "";
  $("#categoryFilter").value = "all";
  $("#statusFilter").value = "all";
  renderFiles();
});
$$('#logFilters button').forEach(button => button.addEventListener("click", () => { $$('#logFilters button').forEach(b=>{b.classList.remove("active");b.setAttribute("aria-pressed","false");}); button.classList.add("active"); button.setAttribute("aria-pressed","true"); logLevel=button.dataset.level; loadLogs(); }));

initUploads(); initSettings(); initHistoryExport(); initReportActions(); initConcurrencyQuiz();
if ($("#heroWorkerOrbit")) {
  const initialWorkerCount = Number($("#sidebarWorkers")?.textContent || 5);
  renderEngineWorkers(Array.from({length: initialWorkerCount}, () => ({})));
}
pollPageData(); pollStatus();
const monitorMessage = sessionStorage.getItem("fileflow-monitor-message");
if (monitorMessage && page === "threads") {
  sessionStorage.removeItem("fileflow-monitor-message");
  toast(monitorMessage, "success", "Workers started");
}
setInterval(() => { if (lastStatus?.processing?.active) pollPageData(); }, 1100);

const themeToggle = $("#themeToggle");
function applyTheme(lightMode) {
  document.body.classList.toggle("light-mode", lightMode);
  if (!themeToggle) return;
  const nextMode = lightMode ? "dark" : "light";
  $(".theme-icon", themeToggle).textContent = lightMode ? "☾" : "☀";
  $(".theme-label", themeToggle).textContent = lightMode ? "Dark mode" : "Light mode";
  themeToggle.setAttribute("aria-label", `Switch to ${nextMode} mode`);
  themeToggle.title = `Switch to ${nextMode} mode`;
}
const savedTheme = localStorage.getItem("fileflow-theme");
applyTheme(savedTheme === "light");
themeToggle?.addEventListener("click", () => {
  const lightMode = !document.body.classList.contains("light-mode");
  applyTheme(lightMode);
  localStorage.setItem("fileflow-theme", lightMode ? "light" : "dark");
});
