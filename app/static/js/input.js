const inventoryFields = document.querySelector(".inventory-fields");
const form = document.querySelector("#calculation-form");
const calculationScrollKey = "nesting1d-scroll-to-results";

function updateMode() {
    const selected = document.querySelector('input[name="mode"]:checked');
    inventoryFields.hidden = !selected || selected.value !== "inventory";
    document.querySelector("#calculation-mode").textContent =
        selected?.value === "inventory" ? "在庫母材・残材活用" : "必要母材算出";
}

function displayCalculationIdentity(number = "", timestamp = "") {
    document.querySelector("#calculation-management-number").textContent = number || "未発行";
    if (timestamp) {
        document.querySelector("#calculation-datetime").textContent =
            new Intl.DateTimeFormat("ja-JP", {dateStyle: "medium", timeStyle: "medium"}).format(new Date(timestamp));
    }
}

document.querySelectorAll('input[name="mode"]').forEach((input) => {
    input.addEventListener("change", updateMode);
});

document.querySelectorAll("[data-add]").forEach((button) => {
    button.addEventListener("click", () => {
        const target = document.querySelector(`#${button.dataset.add}`);
        const templateName = button.dataset.add === "part-rows" ? "part-row-template" : "remnant-row-template";
        target.append(document.querySelector(`#${templateName}`).content.cloneNode(true));
    });
});

document.addEventListener("click", (event) => {
    if (event.target.matches(".remove")) {
        event.target.closest(".input-row").remove();
        setDirty(true);
    }
    if (event.target.closest("[data-add]")) setDirty(true);
});

form.addEventListener("submit", (event) => {
    if (calculationSubmitting) {
        event.preventDefault();
        return;
    }
    calculationSubmitting = true;
    suppressBeforeUnload = true;
    sessionStorage.setItem(calculationScrollKey, "1");
    const button = form.querySelector(".calculate-button");
    button.disabled = true;
    document.querySelector("#processing").hidden = false;
    setTimeout(() => {
        if (event.defaultPrevented) {
            sessionStorage.removeItem(calculationScrollKey);
            resetCalculationSubmission();
        }
    }, 0);
});

updateMode();

const resultTabs = document.querySelector(".result-tabs");
const firstFieldError = document.querySelector(".field-error-input");
const shouldScrollToResults = sessionStorage.getItem(calculationScrollKey) === "1";
sessionStorage.removeItem(calculationScrollKey);
if (resultTabs) {
    const panels = document.querySelectorAll(".result-panel");
    function showResultView(targetId) {
        form.hidden = targetId !== "calculation-form";
        panels.forEach((panel) => {
            panel.hidden = panel.id !== targetId;
        });
        resultTabs.querySelectorAll("button").forEach((button) => {
            const active = button.dataset.resultView === targetId;
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        });
    }
    resultTabs.addEventListener("click", (event) => {
        const button = event.target.closest("[data-result-view]");
        if (button) showResultView(button.dataset.resultView);
    });
    showResultView("dashboard-view");
    if (shouldScrollToResults) {
        window.addEventListener("pageshow", () => {
            showResultView("dashboard-view");
            resultTabs.scrollIntoView({behavior: "smooth", block: "start"});
        }, {once: true});
    }
}
if (firstFieldError) {
    window.addEventListener("pageshow", () => {
        firstFieldError.focus({preventScroll: true});
        firstFieldError.scrollIntoView({behavior: "smooth", block: "center"});
    }, {once: true});
}

const saveButton = document.querySelector("#save-record");
const loadButton = document.querySelector("#load-record");
const jsonButton = document.querySelector("#download-json");
const htmlButton = document.querySelector("#download-html");
const newButton = document.querySelector("#new-record");
const resetButton = document.querySelector("#reset-input");
const recordSelect = document.querySelector("#record-select");
const numberDisplay = document.querySelector("#management-number");
const statusDisplay = document.querySelector("#save-status");
const messageDisplay = document.querySelector("#file-message");
const unsavedDialog = document.querySelector("#unsaved-dialog");
let managementNumber = "";
let dirty = Boolean(resultTabs);
let saving = false;
let calculationSubmitting = false;
let suppressBeforeUnload = false;
let pendingAction = null;

function resetCalculationSubmission() {
    calculationSubmitting = false;
    suppressBeforeUnload = false;
    form.querySelector(".calculate-button").disabled = false;
    document.querySelector("#processing").hidden = true;
}

function setDirty(value) {
    dirty = value;
    statusDisplay.textContent = value ? "未保存" : "保存済み";
    statusDisplay.classList.toggle("unsaved", value);
    statusDisplay.classList.toggle("saved", !value);
}

function formInput() {
    const data = new FormData(form);
    const parts = data.getAll("part_length").map((length, index) => ({
        length_mm: Number(length), quantity: Number(data.getAll("part_quantity")[index]),
    })).filter((item) => item.length_mm || item.quantity);
    const input = {
        mode: data.get("mode"),
        metadata: {title: data.get("title"), material_type: data.get("material_type"), author: data.get("author"), notes: data.get("notes")},
        cutting_conditions: {new_stock_length_mm: Number(data.get("new_stock_length_mm")), kerf_mm: Number(data.get("kerf_mm")), left_trim_mm: Number(data.get("left_trim_mm"))},
        required_parts: parts,
    };
    if (input.mode === "inventory") {
        input.inventory = {
            new_stock_quantity: Number(data.get("new_stock_quantity")),
            remnants: data.getAll("remnant_length").map((length, index) => ({length_mm: Number(length), quantity: Number(data.getAll("remnant_quantity")[index])})).filter((item) => item.length_mm || item.quantity),
        };
    }
    return input;
}

async function saveRecord(overwrite = false) {
    if (saving) return false;
    saving = true;
    saveButton.disabled = true;
    messageDisplay.textContent = "保存中です…";
    try {
        const response = await fetch("/api/save", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({input: formInput(), management_number: managementNumber, overwrite})});
        const data = await response.json();
        if (data.confirm_overwrite && window.confirm(data.message)) { saving = false; return await saveRecord(true); }
        if (!response.ok || !data.ok) throw new Error(data.message || "保存に失敗しました。");
        managementNumber = data.management_number;
        numberDisplay.textContent = managementNumber;
        displayCalculationIdentity(managementNumber, data.updated_at);
        jsonButton.disabled = false;
        htmlButton.disabled = false;
        setDirty(false);
        messageDisplay.textContent = "正式保存が完了しました。";
        return true;
    } catch (error) {
        setDirty(true);
        messageDisplay.textContent = error.message || "保存に失敗しました。";
        return false;
    } finally {
        saving = false;
        saveButton.disabled = false;
    }
}

function replaceRows(containerId, templateId, items, lengthName, quantityName) {
    const container = document.querySelector(`#${containerId}`);
    container.replaceChildren();
    (items.length ? items : [{}]).forEach((item) => {
        const row = document.querySelector(`#${templateId}`).content.cloneNode(true);
        row.querySelector(`[name="${lengthName}"]`).value = item.length_mm ?? "";
        row.querySelector(`[name="${quantityName}"]`).value = item.quantity ?? "";
        container.append(row);
    });
}

function populate(record) {
    const input = record.input;
    for (const name of ["title", "material_type", "author", "notes"]) form.elements[name].value = input.metadata[name] || "";
    form.elements.mode.value = input.mode;
    form.elements.new_stock_length_mm.value = input.cutting_conditions.new_stock_length_mm;
    form.elements.kerf_mm.value = input.cutting_conditions.kerf_mm;
    form.elements.left_trim_mm.value = input.cutting_conditions.left_trim_mm;
    form.elements.new_stock_quantity.value = input.inventory?.new_stock_quantity ?? 0;
    replaceRows("part-rows", "part-row-template", input.required_parts, "part_length", "part_quantity");
    replaceRows("remnant-rows", "remnant-row-template", input.inventory?.remnants || [], "remnant_length", "remnant_quantity");
    managementNumber = record.management_number;
    numberDisplay.textContent = managementNumber;
    displayCalculationIdentity(managementNumber, record.updated_at);
    jsonButton.disabled = false;
    htmlButton.disabled = false;
    updateMode();
    setDirty(false);
    messageDisplay.textContent = "保存済みJSONを読み込みました。再計算できます。";
}

async function loadSelected() {
    if (!recordSelect.value) { messageDisplay.textContent = "読込対象を選択してください。"; return; }
    loadButton.disabled = true;
    try {
        const response = await fetch(`/api/records/${encodeURIComponent(recordSelect.value)}`);
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.message || "読込に失敗しました。");
        populate(data.record);
    } catch (error) { messageDisplay.textContent = error.message; }
    finally { loadButton.disabled = false; }
}

function protectedAction(action) {
    if (!dirty) { action(); return; }
    pendingAction = action;
    unsavedDialog.showModal();
}

unsavedDialog.addEventListener("click", async (event) => {
    if (!event.target.value) return;
    const choice = event.target.value;
    unsavedDialog.close();
    if (choice === "cancel") { pendingAction = null; return; }
    if (choice === "save" && !(await saveRecord())) { pendingAction = null; return; }
    const action = pendingAction;
    pendingAction = null;
    if (action) action();
});

form.addEventListener("input", (event) => {
    setDirty(true);
    const input = event.target.closest(".field-error-input");
    if (!input) return;
    const messageId = input.getAttribute("aria-describedby");
    input.classList.remove("field-error-input");
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
    if (messageId) document.querySelector(`#${messageId}`)?.remove();
});
form.addEventListener("change", () => setDirty(true));
saveButton.addEventListener("click", () => saveRecord());
loadButton.addEventListener("click", () => protectedAction(loadSelected));
newButton.addEventListener("click", () => protectedAction(() => window.location.assign("/")));
resetButton.addEventListener("click", () => protectedAction(() => { form.reset(); window.location.assign("/"); }));
jsonButton.addEventListener("click", () => { if (managementNumber) window.location.assign(`/download/${managementNumber}.json`); });
htmlButton.addEventListener("click", () => { if (managementNumber) window.location.assign(`/download/${managementNumber}.html`); });
window.addEventListener("beforeunload", (event) => {
    if (dirty && !suppressBeforeUnload) {
        event.preventDefault();
        event.returnValue = "";
    }
});
window.addEventListener("pageshow", resetCalculationSubmission);
setDirty(dirty);
