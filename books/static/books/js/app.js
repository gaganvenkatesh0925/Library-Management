/*
 * Library Management System - front-end logic (vanilla JavaScript).
 *
 * Every read and write goes through the REST API:
 *   GET    /api/books/?search=&status=   -> table
 *   GET    /api/books/stats/             -> dashboard cards
 *   GET    /api/borrowers/               -> borrower dropdown
 *   POST   /api/books/                   -> add
 *   PUT    /api/books/<id>/              -> edit
 *   DELETE /api/books/<id>/              -> delete
 */
"use strict";

const BOOKS_URL = "/api/books/";
const STATUS_LABELS = { available: "Available", borrowed: "Borrowed", overdue: "Overdue" };
const DEFAULT_LOAN_DAYS = 14;

const state = { search: "", status: "", editingId: null, deletingId: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

// ---------------------------------------------------------------------------
// API helper: one place that talks to the server and turns failures into
// friendly messages (no stack traces or technical details for the user).
// ---------------------------------------------------------------------------
class ApiError extends Error {
  constructor(message, status = 0, data = null) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
    });
  } catch {
    throw new ApiError("Cannot reach the server. Please check that it is running and try again.");
  }
  if (response.status === 204) return null;

  let data = null;
  try { data = await response.json(); } catch { /* non-JSON body */ }

  if (!response.ok) {
    let message = "Something went wrong on the server. Please try again.";
    if (response.status === 400) message = "Please fix the highlighted fields.";
    else if (response.status === 404) message = "This book no longer exists. It may have been deleted.";
    else if (response.status === 503 && data && data.detail) message = data.detail;
    throw new ApiError(message, response.status, data);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Small utilities
// ---------------------------------------------------------------------------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function toIsoDate(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function addDays(isoDate, days) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return toIsoDate(new Date(y, m - 1, d + days));
}

function formatDate(isoDate) {
  if (!isoDate) return null;
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function toast(message, type = "success") {
  // Several requests can fail for the same reason (e.g. database down): show it once.
  const shown = [...$("#toasts").children].some((t) => t.textContent === message);
  if (shown) return;
  const node = el("div", { className: `toast toast-${type}`, textContent: message, role: "status" });
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 3500);
}

// ---------------------------------------------------------------------------
// Dashboard + table
// ---------------------------------------------------------------------------
async function loadStats() {
  try {
    const stats = await api(`${BOOKS_URL}stats/`);
    for (const key of ["total", "available", "borrowed", "overdue"]) {
      $(`#stat-${key}`).textContent = stats[key];
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

async function loadBooks(highlightId = null) {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  const query = params.toString();

  try {
    const books = await api(query ? `${BOOKS_URL}?${query}` : BOOKS_URL);
    renderBooks(books);
    if (highlightId) highlightRow(highlightId);
  } catch (err) {
    renderMessageRow("Could not load books.", err.message);
    toast(err.message, "error");
  }
}

function refresh(highlightId = null) {
  return Promise.all([loadBooks(highlightId), loadStats()]);
}

function renderMessageRow(title, detail = "", action = null) {
  const cell = el("td", { colSpan: 9, className: "empty" }, el("strong", { textContent: title }), detail, action);
  $("#books-body").replaceChildren(el("tr", {}, cell));
}

function renderBooks(books) {
  const count = $("#result-count");
  count.textContent = `Showing ${books.length} book${books.length === 1 ? "" : "s"}`;

  if (books.length === 0) {
    if (state.search) {
      renderMessageRow("No books match your search.", "Try a different title, author, borrower or status.");
    } else if (state.status) {
      renderMessageRow("No books found.", `There are no ${STATUS_LABELS[state.status].toLowerCase()} books right now.`);
    } else {
      const addButton = el("button", { className: "btn btn-primary", type: "button", textContent: "+ Add your first book" });
      addButton.addEventListener("click", openAddDialog);
      renderMessageRow("No books found.", el("div", { textContent: "The library is empty." }), addButton);
    }
    return;
  }

  const today = toIsoDate(new Date());
  const rows = books.map((book) => {
    const dash = () => el("span", { className: "muted", textContent: "—" });
    const isLate = book.status !== "available" && book.return_due_date && book.return_due_date < today;

    const editBtn = el("button", { className: "btn btn-sm btn-edit", type: "button", textContent: "Edit" });
    editBtn.addEventListener("click", () => openEditDialog(book.id));
    const deleteBtn = el("button", { className: "btn btn-sm btn-delete", type: "button", textContent: "Delete" });
    deleteBtn.addEventListener("click", () => openDeleteDialog(book));

    const row = el("tr",
      {},
      el("td", {}, el("span", { className: `badge badge-${book.status}`, textContent: book.status_display })),
      el("td", { className: "title", textContent: book.title }),
      el("td", { className: "num", textContent: book.number_of_copies }),
      el("td", { className: "author", textContent: book.author }),
      el("td", {}, formatDate(book.date_of_borrow) ?? dash()),
      el("td", { className: isLate ? "late" : "" }, formatDate(book.return_due_date) ?? dash()),
      el("td", {}, book.borrower_name ?? dash()),
      el("td", {}, book.borrower ?? dash()),
      el("td", {}, el("div", { className: "actions" }, editBtn, deleteBtn)),
    );
    row.dataset.id = book.id;
    return row;
  });
  $("#books-body").replaceChildren(...rows);
}

function highlightRow(id) {
  const row = document.querySelector(`#books-body tr[data-id="${id}"]`);
  if (!row) return;
  row.classList.add("highlight");
  row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setTimeout(() => row.classList.remove("highlight"), 2500);
}

// ---------------------------------------------------------------------------
// Search + status filter (both are sent to the API together)
// ---------------------------------------------------------------------------
function setStatusFilter(status) {
  state.status = status;
  $$(".chip").forEach((chip) => chip.classList.toggle("active", chip.dataset.filter === status));
  loadBooks();
}

$("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.search = $("#search-input").value.trim();
  loadBooks();
});

// The little "x" in a search box clears it: show all books again.
$("#search-input").addEventListener("search", () => {
  if ($("#search-input").value === "" && state.search) {
    state.search = "";
    loadBooks();
  }
});

$$("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => setStatusFilter(button.dataset.filter));
});

// ---------------------------------------------------------------------------
// Add / Edit dialog
// ---------------------------------------------------------------------------
const bookDialog = $("#book-dialog");
const bookForm = $("#book-form");

async function loadBorrowers() {
  try {
    const borrowers = await api("/api/borrowers/");
    const select = bookForm.elements.borrower;
    select.replaceChildren(
      el("option", { value: "", textContent: "— Select borrower —" }),
      ...borrowers.map((b) => el("option", { value: b.borrower_id, textContent: `${b.borrower_id} — ${b.name}` })),
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

function clearErrors() {
  $("#form-error").hidden = true;
  $$("[data-error-for]").forEach((node) => { node.textContent = ""; });
  $$(".field.invalid").forEach((node) => node.classList.remove("invalid"));
}

function showFieldErrors(errors) {
  let unmatched = [];
  for (const [field, messages] of Object.entries(errors)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    const slot = document.querySelector(`[data-error-for="${field}"]`);
    if (slot) {
      slot.textContent = text;
      slot.closest(".field").classList.add("invalid");
    } else {
      unmatched.push(text);
    }
  }
  if (unmatched.length) showFormError(unmatched.join(" "));
}

function showFormError(message) {
  const box = $("#form-error");
  box.textContent = message;
  box.hidden = false;
}

function updateLoanFields() {
  const status = bookForm.elements.status.value;
  const isAvailable = status === "available";
  $("#loan-fields").disabled = isAvailable;
  $("#loan-hint").textContent = isAvailable
    ? "Not needed for available books. Any existing loan details will be cleared."
    : `Required for ${STATUS_LABELS[status].toLowerCase()} books.`;

  // Helpful defaults when a book is lent out: borrowed today, due in 14 days.
  if (!isAvailable) {
    const borrowInput = bookForm.elements.date_of_borrow;
    const dueInput = bookForm.elements.return_due_date;
    if (!borrowInput.value) borrowInput.value = toIsoDate(new Date());
    if (!dueInput.value) dueInput.value = addDays(borrowInput.value, DEFAULT_LOAN_DAYS);
  }
}

function openAddDialog() {
  state.editingId = null;
  bookForm.reset();
  clearErrors();
  $("#book-dialog-title").textContent = "Add Book";
  $("#save-btn").textContent = "Add Book";
  updateLoanFields();
  bookDialog.showModal();
  bookForm.elements.title.focus();
}

async function openEditDialog(id) {
  let book;
  try {
    book = await api(`${BOOKS_URL}${id}/`);
  } catch (err) {
    toast(err.message, "error");
    refresh();
    return;
  }
  state.editingId = id;
  bookForm.reset();
  clearErrors();
  const f = bookForm.elements;
  f.title.value = book.title;
  f.author.value = book.author;
  f.number_of_copies.value = book.number_of_copies;
  f.status.value = book.status;
  f.borrower.value = book.borrower ?? "";
  f.date_of_borrow.value = book.date_of_borrow ?? "";
  f.return_due_date.value = book.return_due_date ?? "";
  $("#book-dialog-title").textContent = "Edit Book";
  $("#save-btn").textContent = "Save Changes";
  updateLoanFields();
  bookDialog.showModal();
}

function readForm() {
  const f = bookForm.elements;
  const status = f.status.value;
  const onLoan = status !== "available";
  return {
    title: f.title.value.trim(),
    author: f.author.value.trim(),
    number_of_copies: f.number_of_copies.value === "" ? null : Number(f.number_of_copies.value),
    status,
    borrower: onLoan ? f.borrower.value || null : null,
    date_of_borrow: onLoan ? f.date_of_borrow.value || null : null,
    return_due_date: onLoan ? f.return_due_date.value || null : null,
  };
}

// Quick checks in the browser for instant feedback. The server enforces the
// same rules, so the API stays safe even when called directly with curl.
function validate(data) {
  const errors = {};
  if (!data.title) errors.title = "Book title is required.";
  if (!data.author) errors.author = "Author is required.";
  if (data.number_of_copies === null || !Number.isInteger(data.number_of_copies) || data.number_of_copies < 0) {
    errors.number_of_copies = "Enter a whole number of 0 or more.";
  }
  if (data.status !== "available") {
    if (!data.borrower) errors.borrower = "Select a borrower.";
    if (!data.date_of_borrow) errors.date_of_borrow = "Date of borrow is required.";
    if (!data.return_due_date) errors.return_due_date = "Return due date is required.";
  }
  if (data.date_of_borrow && data.return_due_date && data.return_due_date < data.date_of_borrow) {
    errors.return_due_date = "Return due date cannot be before the date of borrow.";
  }
  return errors;
}

bookForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();
  const data = readForm();
  const errors = validate(data);
  if (Object.keys(errors).length) {
    showFieldErrors(errors);
    return;
  }

  const isEdit = state.editingId !== null;
  const saveBtn = $("#save-btn");
  saveBtn.disabled = true;
  try {
    const saved = await api(isEdit ? `${BOOKS_URL}${state.editingId}/` : BOOKS_URL, {
      method: isEdit ? "PUT" : "POST",
      body: JSON.stringify(data),
    });
    bookDialog.close();
    toast(isEdit ? `"${saved.title}" was updated successfully.` : `"${saved.title}" was added successfully.`);
    await refresh(saved.id);
  } catch (err) {
    if (err.status === 400 && err.data && typeof err.data === "object") {
      showFieldErrors(err.data);
    } else {
      showFormError(err.message);
    }
  } finally {
    saveBtn.disabled = false;
  }
});

// As soon as the user fixes a field, remove its old error message.
bookForm.addEventListener("input", (event) => {
  const field = event.target.closest(".field");
  if (!field || !field.classList.contains("invalid")) return;
  field.classList.remove("invalid");
  field.querySelector("[data-error-for]").textContent = "";
});

bookForm.elements.status.addEventListener("change", updateLoanFields);
bookForm.elements.date_of_borrow.addEventListener("change", () => {
  const f = bookForm.elements;
  if (f.date_of_borrow.value && (!f.return_due_date.value || f.return_due_date.value < f.date_of_borrow.value)) {
    f.return_due_date.value = addDays(f.date_of_borrow.value, DEFAULT_LOAN_DAYS);
  }
});
$("#add-btn").addEventListener("click", openAddDialog);

// ---------------------------------------------------------------------------
// Delete confirmation
// ---------------------------------------------------------------------------
const deleteDialog = $("#delete-dialog");

function openDeleteDialog(book) {
  state.deletingId = book.id;
  $("#delete-name").textContent = `"${book.title}" by ${book.author}`;
  deleteDialog.showModal();
}

$("#confirm-delete-btn").addEventListener("click", async () => {
  const button = $("#confirm-delete-btn");
  button.disabled = true;
  try {
    await api(`${BOOKS_URL}${state.deletingId}/`, { method: "DELETE" });
    toast("The book was deleted successfully.");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    button.disabled = false;
    deleteDialog.close();
    state.deletingId = null;
    refresh();
  }
});

// Any button with data-close closes the dialog it is in.
$$("[data-close]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
loadBorrowers();
refresh();
