/*
 * View Logs page: loads real log records from GET /logs/data/?action=
 * (staff login required) and renders the summary cards and the table.
 */
"use strict";

const LOGS_URL = "/logs/data/";
const $ = (selector) => document.querySelector(selector);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function messageRow(title, detail = "") {
  const cell = el("td", { colSpan: 5, className: "empty" }, el("strong", { textContent: title }), detail);
  $("#logs-body").replaceChildren(el("tr", {}, cell));
}

function render(data, action) {
  $("#sum-total").textContent = data.summary.total;
  $("#sum-success").textContent = data.summary.success;
  $("#sum-errors").textContent = data.summary.errors;
  $("#logs-info").textContent =
    `${data.entries.length} entr${data.entries.length === 1 ? "y" : "ies"} · updated ${new Date().toLocaleTimeString()}`;

  if (data.entries.length === 0) {
    if (action) messageRow(`No ${action} entries yet.`, "Choose “All entries” to see every operation.");
    else messageRow("No activity logs available yet.", "Add, view, edit or delete a book, then press Refresh Logs.");
    return;
  }

  const rows = data.entries.map((entry) => el("tr", {},
    el("td", { className: "nowrap", textContent: entry.timestamp }),
    el("td", {}, el("span", { className: `log-action log-action-${entry.action.toLowerCase()}`, textContent: entry.action })),
    el("td", {}, el("span", { className: `badge log-level-${entry.level.toLowerCase()}`, textContent: entry.level })),
    el("td", { className: "log-message", textContent: entry.message }),
    el("td", { className: "num" }, entry.book_id ?? el("span", { className: "muted", textContent: "—" })),
  ));
  $("#logs-body").replaceChildren(...rows);
}

async function loadLogs() {
  const action = $("#action-filter").value;
  const button = $("#refresh-logs");
  button.disabled = true;
  try {
    const response = await fetch(action ? `${LOGS_URL}?action=${encodeURIComponent(action)}` : LOGS_URL, {
      headers: { Accept: "application/json" },
    });
    if (response.status === 403) {
      messageRow("Your session has expired.", "Reload the page and sign in again.");
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json(), action);
  } catch {
    messageRow("Could not load logs.", "The server or database may be unavailable. Try Refresh Logs again shortly.");
  } finally {
    button.disabled = false;
  }
}

$("#action-filter").addEventListener("change", loadLogs);
$("#refresh-logs").addEventListener("click", loadLogs);
loadLogs();
