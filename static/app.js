(function () {
  const $ = (id) => document.getElementById(id);
  const LABELS = { unique: "Unique", false_positive: "False positive (verified)", redundant: "Redundant", invalid: "Invalid" };
  let view = "records";

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    return { status: res.status, data: await res.json() };
  }

  async function refreshStats() {
    const { data } = await api("/api/stats");
    const items = [
      ["Submitted", data.submitted], ["Stored", data.stored], ["Redundant blocked", data.redundant],
      ["False positives cleared", data.false_positive], ["Invalid rejected", data.invalid],
      ["Duplicates blocked", data.duplicates_blocked_percent + "%"],
    ];
    const box = $("stats");
    box.replaceChildren();
    items.forEach(([label, value]) => {
      const s = el("div", undefined, "stat");
      s.append(el("b", String(value)), el("span", label));
      box.append(s);
    });
  }

  function renderTable(headers, rows) {
    const table = $("table");
    table.replaceChildren();
    if (!rows.length) {
      const p = el("p", "Nothing here yet. Add a record or run the sample data.", "empty");
      table.append(p);
      return;
    }
    const thead = el("thead"); const tr = el("tr");
    headers.forEach((h) => tr.append(el("th", h)));
    thead.append(tr); table.append(thead);
    const tbody = el("tbody");
    rows.forEach((cells) => {
      const r = el("tr");
      cells.forEach((c) => {
        const td = el("td");
        if (c && c.badge) td.append(el("span", LABELS[c.badge] || c.badge, "badge " + c.badge));
        else td.textContent = c === null || c === undefined ? "" : c;
        r.append(td);
      });
      tbody.append(r);
    });
    table.append(tbody);
  }

  async function refreshTable() {
    if (view === "records") {
      const { data } = await api("/api/records");
      renderTable(["ID", "Name", "Email", "Phone", "City", "Flag"],
        data.map((r) => [r.id, r.name, r.email, r.phone, r.city, r.flagged ? { badge: "false_positive" } : ""]));
    } else {
      const { data } = await api("/api/audit");
      renderTable(["Time (UTC)", "Input", "Decision", "Reason"],
        data.map((a) => [a.created_at.replace("T", " "), [a.input.name, a.input.email].filter(Boolean).join(" | "),
          { badge: a.decision }, a.reason]));
    }
  }

  function setView(v) {
    view = v;
    $("tab-records").setAttribute("aria-selected", String(v === "records"));
    $("tab-audit").setAttribute("aria-selected", String(v === "audit"));
    refreshTable();
  }

  async function refreshAll() { await Promise.all([refreshStats(), refreshTable()]); }

  async function addRecord() {
    const body = { name: $("f-name").value, email: $("f-email").value, phone: $("f-phone").value, city: $("f-city").value };
    $("btn-add").disabled = true;
    try {
      const { data } = await api("/api/records", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const box = $("result");
      box.hidden = false;
      box.className = "result " + data.decision;
      box.replaceChildren(el("strong", LABELS[data.decision] || data.decision), el("span", data.reason || data.error || ""));
      if (data.decision === "unique" || data.decision === "false_positive") {
        ["f-name", "f-email", "f-phone", "f-city"].forEach((id) => ($(id).value = ""));
      }
      await refreshAll();
    } catch (e) {
      $("result").hidden = false;
      $("result").className = "result invalid";
      $("result").textContent = "Cannot reach the server.";
    } finally { $("btn-add").disabled = false; }
  }

  async function bulk(csvText) {
    $("bulk-msg").textContent = "Processing...";
    const { status, data } = await api("/api/records/bulk", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ csv: csvText }) });
    if (status !== 200) { $("bulk-msg").textContent = data.error || "Import failed."; return; }
    const s = data.summary;
    $("bulk-msg").textContent = `${data.total} rows processed: ${s.unique || 0} unique, ${s.false_positive || 0} false positives cleared, ${s.redundant || 0} redundant blocked, ${s.invalid || 0} invalid.`;
    await refreshAll();
  }

  $("btn-add").addEventListener("click", addRecord);
  ["f-name", "f-email", "f-phone", "f-city"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") addRecord(); }));
  $("btn-sample").addEventListener("click", async () => { const { data } = await api("/api/sample"); bulk(data.csv); });
  $("f-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => bulk(String(reader.result));
    reader.readAsText(file);
    e.target.value = "";
  });
  $("tab-records").addEventListener("click", () => setView("records"));
  $("tab-audit").addEventListener("click", () => setView("audit"));

  refreshAll();
})();
