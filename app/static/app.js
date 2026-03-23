const state = {
  runs: [],
  selectedRun: null,
  filters: { type: "all", status: "all", date: "" },
};

const jobTypeLabel = {
  check: "巡检",
  enable: "恢复",
  check_and_enable: "巡检并恢复",
};

const statusLabel = {
  success: "成功",
  failed: "失败",
  partial: "部分成功",
  skipped: "已跳过",
  running: "运行中",
};

const triggerLabel = {
  manual: "手动触发",
  schedule: "定时触发",
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("未登录或登录已过期");
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `请求失败: ${response.status}`);
  }
  return response.json();
}

function byId(id) {
  return document.getElementById(id);
}

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "暂无";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}小时${m}分${s}秒`;
  if (m > 0) return `${m}分${s}秒`;
  return `${s}秒`;
}

function formatReset(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}天${hours}小${minutes}分`;
  if (hours > 0) return `${hours}小${minutes}分`;
  return `${minutes}分`;
}

function recoveryTypeLabel(reasonCode) {
  if (reasonCode === "weekly_window_grace") return "周窗口";
  if (reasonCode === "suggest_reenable" || reasonCode === "rate_limit_grace") return "短期窗口";
  return "人工判断";
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tabName);
  });
}

function renderCards(health) {
  const latest = health.latest_run;
  const cards = [
    {
      title: "调度器状态",
      value: health.scheduler.started ? "运行中" : "未启动",
      meta: health.scheduler.schedule_enabled ? `定时间隔 ${health.scheduler.interval_minutes} 分钟` : "定时任务已关闭",
    },
    {
      title: "自动恢复",
      value: health.scheduler.auto_reenable_enabled ? "已开启" : "已关闭",
      meta: health.scheduler.currently_running ? "当前有任务正在执行" : "当前空闲",
    },
    {
      title: "最近任务",
      value: latest ? jobTypeLabel[latest.job_type] : "暂无",
      meta: latest ? `${statusLabel[latest.status] || latest.status} / ${formatDateTime(latest.started_at)}` : "尚未执行",
    },
    {
      title: "最近耗时",
      value: latest ? formatDuration(latest.duration_seconds) : "暂无",
      meta: latest ? `触发方式：${triggerLabel[latest.trigger] || latest.trigger}` : "等待首次执行",
    },
  ];
  byId("dashboardCards").innerHTML = cards.map((card) => `
    <article class="card">
      <h3>${card.title}</h3>
      <div class="card-value">${card.value}</div>
      <div class="muted">${card.meta}</div>
    </article>
  `).join("");
}

function renderOverviewHighlights(run) {
  const target = byId("overviewHighlights");
  if (!run) {
    target.innerHTML = `<div class="muted">暂无概览数据。</div>`;
    return;
  }
  const checkSummary = run.metadata?.check_summary || (run.job_type === "check" ? run.summary : null);
  const enableSummary = run.metadata?.enable_summary || (run.job_type === "enable" ? run.summary : null);
  const checkStats = run.metadata?.check_stats || null;
  const items = [
    { label: "自动禁用总数", value: checkStats?.auto_disabled_total ?? checkSummary?.total ?? run.summary.total ?? 0 },
    { label: "纳入巡检数", value: checkStats?.included_auto_disabled_total ?? checkSummary?.total ?? run.summary.total ?? 0 },
    { label: "可直接恢复", value: checkSummary?.suggest_reenable ?? 0 },
    { label: "周窗口受限", value: checkSummary?.weekly_window_blocked ?? 0 },
    { label: "短期窗口受限", value: checkSummary?.short_window_blocked ?? 0 },
    { label: "恢复成功", value: enableSummary?.success ?? run.summary.success ?? 0 },
    { label: "优先级跳过", value: checkStats?.skipped_priority_total ?? 0 },
  ];
  target.innerHTML = items.map((item) => `
    <article class="mini-card">
      <div class="mini-label">${item.label}</div>
      <div class="mini-value">${item.value}</div>
    </article>
  `).join("");
}

function loadConfigForm(config) {
  const form = byId("configForm");
  Object.entries(config).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (!field) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else if (Array.isArray(value)) {
      field.value = value.join(",");
    } else {
      field.value = value;
    }
  });
}

function serializeConfig() {
  const form = byId("configForm");
  return {
    request_timeout: Number(form.request_timeout.value),
    max_enable_per_run: Number(form.max_enable_per_run.value),
    dry_run: form.dry_run.checked,
    deny_channel_ids: form.deny_channel_ids.value.split(",").map((item) => item.trim()).filter(Boolean).map(Number),
    skip_channel_priorities: form.skip_channel_priorities.value.split(",").map((item) => item.trim()).filter(Boolean).map(Number),
    schedule_enabled: form.schedule_enabled.checked,
    auto_reenable_enabled: form.auto_reenable_enabled.checked,
    schedule_interval_minutes: Number(form.schedule_interval_minutes.value),
    log_retention_days: Number(form.log_retention_days.value),
    run_retention_days: Number(form.run_retention_days.value),
    lock_ttl_minutes: Number(form.lock_ttl_minutes.value),
  };
}

function buildCheckSummary(run) {
  const summary = run.metadata?.check_summary || (run.job_type === "check" ? run.summary : null);
  const stats = run.metadata?.check_stats || null;
  if (!summary) return "";
  return `
    <article class="summary-card">
      <h3>巡检结果汇总</h3>
      <div class="summary-line">脚本退出码：${run.metadata?.check_exit_code ?? (run.status === "failed" ? 1 : 0)}</div>
      <div class="summary-line">自动禁用总数：${stats?.auto_disabled_total ?? summary.total ?? 0}</div>
      <div class="summary-line">纳入巡检渠道数：${stats?.included_auto_disabled_total ?? summary.total ?? 0}</div>
      <div class="summary-line">因跳过优先级排除：${stats?.skipped_priority_total ?? 0}</div>
      <div class="summary-line">可直接恢复渠道数：${summary.suggest_reenable ?? 0}</div>
      <div class="summary-line">周窗口仍受限：${summary.weekly_window_blocked ?? 0}</div>
      <div class="summary-line">周窗口已到可恢复缓冲区：${summary.weekly_window_grace ?? 0}</div>
      <div class="summary-line">短期窗口仍受限：${summary.short_window_blocked ?? 0}</div>
      <div class="summary-line">短期限流已到可恢复缓冲区：${summary.rate_limit_grace ?? 0}</div>
      <div class="summary-line">usage 401：${summary.usage_error_401 ?? 0}</div>
      <div class="summary-line">usage 402：${summary.usage_error_402 ?? 0}</div>
    </article>
  `;
}

function buildEnableSuccessList(run) {
  const items = (run.decisions || []).filter((item) => item.action === "enable" && item.suggestion === "已恢复");
  if (!items.length) {
    return `<div class="summary-line">本次恢复成功列表：无</div>`;
  }
  return `
    <div class="summary-line">本次恢复成功列表：</div>
    ${items.map((item) => {
      const reset = item.details?.weekly_reset_after_seconds ?? item.details?.short_reset_after_seconds;
      return `<div class="summary-line">渠道ID=${item.channel_id}；名称=${htmlEscape(item.channel_name)}；恢复类型=${recoveryTypeLabel(item.reason_code)}；距离重置=${formatReset(reset)}</div>`;
    }).join("")}
  `;
}

function buildEnableSummary(run) {
  const summary = run.metadata?.enable_summary || (run.job_type === "enable" ? run.summary : null);
  const stats = run.metadata?.enable_stats || null;
  const enableExecuted = run.metadata?.enable_executed || run.job_type === "enable";
  if (!enableExecuted || !summary) return "";
  return `
    <article class="summary-card">
      <h3>恢复结果汇总</h3>
      <div class="summary-line">脚本退出码：${run.metadata?.enable_exit_code ?? (run.status === "failed" ? 1 : 0)}</div>
      <div class="summary-line">自动禁用总数：${stats?.auto_disabled_total ?? summary.total ?? 0}</div>
      <div class="summary-line">纳入恢复判断渠道数：${stats?.included_auto_disabled_total ?? summary.total ?? 0}</div>
      <div class="summary-line">因跳过优先级排除：${stats?.skipped_priority_total ?? 0}</div>
      <div class="summary-line">成功恢复：${summary.success ?? 0}</div>
      <div class="summary-line">恢复失败：${summary.failed ?? 0}</div>
      <div class="summary-line">跳过数量：${summary.skipped ?? 0}</div>
      ${buildEnableSuccessList(run)}
    </article>
  `;
}

function renderRunSummaryInto(targetId, run) {
  const target = byId(targetId);
  if (!run) {
    target.innerHTML = `<div class="muted">暂无运行结果。</div>`;
    return;
  }
  target.innerHTML = `
    <div class="summary-header">
      <div>任务类型：${jobTypeLabel[run.job_type] || run.job_type}</div>
      <div>执行状态：${statusLabel[run.status] || run.status}</div>
      <div>触发方式：${triggerLabel[run.trigger] || run.trigger}</div>
      <div>开始时间：${formatDateTime(run.started_at)}</div>
      <div>结束时间：${formatDateTime(run.finished_at)}</div>
      <div>耗时：${formatDuration(run.duration_seconds)}</div>
    </div>
    <div class="summary-grid">
      ${buildCheckSummary(run)}
      ${buildEnableSummary(run)}
    </div>
  `;
}

function filterRuns(runs) {
  return runs.filter((run) => {
    if (state.filters.type !== "all" && run.job_type !== state.filters.type) return false;
    if (state.filters.status !== "all" && run.status !== state.filters.status) return false;
    if (state.filters.date) {
      const started = new Date(run.started_at);
      const y = started.getFullYear();
      const m = String(started.getMonth() + 1).padStart(2, "0");
      const d = String(started.getDate()).padStart(2, "0");
      if (`${y}-${m}-${d}` !== state.filters.date) return false;
    }
    return true;
  });
}

function renderRuns(runs) {
  const filtered = filterRuns(runs);
  byId("runList").innerHTML = filtered.map((run) => `
    <article class="run-item">
      <div>
        <strong>${jobTypeLabel[run.job_type] || run.job_type}</strong>
        <span class="badge">${statusLabel[run.status] || run.status}</span>
      </div>
      <div class="muted">开始时间：${formatDateTime(run.started_at)}</div>
      <div class="muted">触发方式：${triggerLabel[run.trigger] || run.trigger}</div>
      <div class="muted">耗时：${formatDuration(run.duration_seconds)}</div>
      <div class="actions" style="margin-top: 10px;">
        <button onclick="selectRun('${run.run_id}')">查看结果</button>
        <button onclick="showRunLog('${run.run_id}')">查看日志</button>
      </div>
    </article>
  `).join("") || `<div class="muted">当前筛选条件下没有运行记录。</div>`;
}

async function selectRun(runId) {
  const run = await fetchJson(`/api/runs/${runId}`);
  state.selectedRun = run;
  renderRunSummaryInto("runSummary", run);
  renderRunSummaryInto("jobRunSummary", run);
  renderOverviewHighlights(run);
  await showRunLog(runId);
  switchTab("history");
}

async function showRunLog(runId) {
  const payload = await fetchJson(`/api/logs?run_id=${encodeURIComponent(runId)}`);
  const viewer = byId("logViewer");
  viewer.textContent = payload.lines.join("\n");
  if (byId("autoScrollLogs").checked) {
    viewer.scrollTop = viewer.scrollHeight;
  }
}

async function copyLogs() {
  const text = byId("logViewer").textContent || "";
  await navigator.clipboard.writeText(text);
}

async function refreshAll() {
  const [health, config, runs] = await Promise.all([
    fetchJson("/api/health"),
    fetchJson("/api/config"),
    fetchJson("/api/runs"),
  ]);
  state.runs = runs;
  renderCards(health);
  loadConfigForm(config);
  renderRuns(runs);
  const current = state.selectedRun
    ? runs.find((run) => run.run_id === state.selectedRun.run_id) || runs[0]
    : runs[0];
  state.selectedRun = current || null;
  renderRunSummaryInto("runSummary", current || null);
  renderRunSummaryInto("jobRunSummary", current || null);
  renderOverviewHighlights(current || null);
  if (current) {
    await showRunLog(current.run_id);
  } else {
    byId("logViewer").textContent = "";
  }
}

async function triggerJob(jobType) {
  byId("jobStatus").textContent = `正在执行${jobTypeLabel[jobType] || jobType}...`;
  try {
    const result = await fetchJson(`/api/jobs/${jobType}`, { method: "POST" });
    byId("jobStatus").textContent = `任务执行完成：${result.run_id} / ${statusLabel[result.status] || result.status}`;
    await refreshAll();
    switchTab("jobs");
  } catch (error) {
    byId("jobStatus").textContent = error.message;
  }
}

async function saveConfig() {
  byId("configStatus").textContent = "正在保存配置...";
  try {
    await fetchJson("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(serializeConfig()),
    });
    byId("configStatus").textContent = "配置已保存。";
    await refreshAll();
  } catch (error) {
    byId("configStatus").textContent = error.message;
  }
}

async function validateConfig() {
  byId("configStatus").textContent = "正在校验配置...";
  try {
    const result = await fetchJson("/api/config/validate", { method: "POST" });
    byId("configStatus").textContent = result.message;
  } catch (error) {
    byId("configStatus").textContent = error.message;
  }
}

function bindFilters() {
  byId("historyTypeFilter").addEventListener("change", (event) => {
    state.filters.type = event.target.value;
    renderRuns(state.runs);
  });
  byId("historyStatusFilter").addEventListener("change", (event) => {
    state.filters.status = event.target.value;
    renderRuns(state.runs);
  });
  byId("historyDateFilter").addEventListener("change", (event) => {
    state.filters.date = event.target.value;
    renderRuns(state.runs);
  });
  byId("historyResetFilters").addEventListener("click", () => {
    state.filters = { type: "all", status: "all", date: "" };
    byId("historyTypeFilter").value = "all";
    byId("historyStatusFilter").value = "all";
    byId("historyDateFilter").value = "";
    renderRuns(state.runs);
  });
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});
document.querySelectorAll("[data-job]").forEach((button) => {
  button.addEventListener("click", () => triggerJob(button.dataset.job));
});
byId("saveConfig").addEventListener("click", saveConfig);
byId("validateConfig").addEventListener("click", validateConfig);
byId("refreshAll").addEventListener("click", refreshAll);
byId("logoutButton").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  window.location.href = "/login";
});
byId("copyLogs").addEventListener("click", () => copyLogs().catch((error) => {
  byId("jobStatus").textContent = error.message;
}));
bindFilters();
refreshAll().catch((error) => {
  byId("jobStatus").textContent = error.message;
});
