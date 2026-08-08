const inventoryFields = document.querySelector(".inventory-fields");
const form = document.querySelector("#calculation-form");
const requiredPartsFields = document.querySelector("#part-rows").closest(".card");
const calculateButton = form.querySelector(".calculate-button");
const calculationScrollKey = "nesting1d-scroll-to-results";
const INPUT_ROW_LIMITS = {"part-rows": 20, "remnant-rows": 10};

function updateAddRowButton(button) {
    const target = document.querySelector(`#${button.dataset.add}`);
    button.disabled = target.querySelectorAll(".input-row").length >= INPUT_ROW_LIMITS[button.dataset.add];
}

function updateMode() {
    const selected = document.querySelector('input[name="mode"]:checked');
    const inventoryMode = selected?.value === "inventory";
    inventoryFields.hidden = !inventoryMode;
    form.insertBefore(inventoryFields, inventoryMode ? requiredPartsFields : calculateButton);
    document.querySelector("#calculation-mode").textContent =
        inventoryMode ? "在庫母材・残材活用" : "必要母材算出";
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
        if (target.querySelectorAll(".input-row").length >= INPUT_ROW_LIMITS[button.dataset.add]) return;
        const templateName = button.dataset.add === "part-rows" ? "part-row-template" : "remnant-row-template";
        target.append(document.querySelector(`#${templateName}`).content.cloneNode(true));
        updateAddRowButton(button);
    });
    updateAddRowButton(button);
});

document.addEventListener("click", (event) => {
    if (event.target.matches(".remove")) {
        const rowContainer = event.target.closest(".rows");
        event.target.closest(".input-row").remove();
        updateAddRowButton(document.querySelector(`[data-add="${rowContainer.id}"]`));
        invalidateCalculationResult();
    }
    if (event.target.closest("[data-add]")) invalidateCalculationResult();
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
const hasResult = resultTabs?.dataset.hasResult === "true";
const firstFieldError = document.querySelector(".field-error-input");
const shouldScrollToResults = sessionStorage.getItem(calculationScrollKey) === "1";
sessionStorage.removeItem(calculationScrollKey);
if (resultTabs) {
    const panels = document.querySelectorAll(".result-panel");
    function showResultView(targetId) {
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
    showResultView(hasResult ? "dashboard-view" : "conditions-view");
    if (shouldScrollToResults && hasResult) {
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

const localJsonFileInput = document.querySelector("#local-json-file");
const localJsonLoadButton = document.querySelector("#load-local-json");
const localJsonFilename = document.querySelector("#local-json-filename");
const localJsonError = document.querySelector("#local-json-error");
const jsonButton = document.querySelector("#download-json");
const htmlButton = document.querySelector("#download-html");
const resetButton = document.querySelector("#reset-input");
const numberDisplay = document.querySelector("#management-number");
const statusDisplay = document.querySelector("#save-status");
const messageDisplay = document.querySelector("#file-message");
const unsavedDialog = document.querySelector("#unsaved-dialog");
const managementNumberInput = document.querySelector("#result-management-number");
const managementNumberStateInput = document.querySelector("#management-number-state");
const createdAtInput = document.querySelector("#result-created-at");
const updatedAtInput = document.querySelector("#result-updated-at");
let managementNumber = managementNumberInput.value;
let createdAt = createdAtInput.value;
let updatedAt = updatedAtInput.value;
let hasValidResult = hasResult;
let jsonExported = false;
let htmlExported = false;
let requiresManagementNumberReissue = managementNumberStateInput.value === "reissue";
let dirty = hasResult;
let exportingJson = false;
let exportingHtml = false;
let calculationSubmitting = false;
let suppressBeforeUnload = false;
let pendingAction = null;
let jsonLoadedPendingCalculation = false;

const LOCAL_JSON_MAX_BYTES = 5 * 1024 * 1024;
const LOCAL_JSON_MAX_DEPTH = 8;
const LOCAL_JSON_MAX_PART_ROWS = 20;
const LOCAL_JSON_MAX_REMNANT_ROWS = 10;
const LEGACY_MANAGEMENT_NUMBER = /^NEST-\d{8}-\d{3}$/;
const CURRENT_MANAGEMENT_NUMBER = /^NEST-\d{8}-\d{6}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}$/;
const TOKYO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+09:00$/;

class LocalJsonValidationError extends Error {}

function resetCalculationSubmission() {
    calculationSubmitting = false;
    suppressBeforeUnload = false;
    form.querySelector(".calculate-button").disabled = false;
    document.querySelector("#processing").hidden = true;
}

function setDirty(value) {
    dirty = value;
}

function updateOutputStatus() {
    let text = "未計算";
    if (jsonLoadedPendingCalculation) text = "JSON読込済み・再計算前";
    if (!hasValidResult && dirty) text = "入力変更あり・再計算が必要";
    if (hasValidResult) text = "計算済み・未出力";
    if (hasValidResult && jsonExported) text = "JSON出力済み";
    if (hasValidResult && htmlExported) text = "HTML出力済み";
    if (hasValidResult && jsonExported && htmlExported) text = "JSON・HTML出力済み";
    statusDisplay.textContent = text;
    statusDisplay.hidden = false;
    const hasAnyExport = jsonExported || htmlExported;
    statusDisplay.classList.toggle("unsaved", dirty || (hasValidResult && !hasAnyExport));
    statusDisplay.classList.toggle("saved", !dirty && (!hasValidResult || hasAnyExport));
}

function invalidateCalculationResult() {
    jsonLoadedPendingCalculation = false;
    setDirty(true);
    hasValidResult = false;
    jsonExported = false;
    htmlExported = false;
    requiresManagementNumberReissue = true;
    managementNumber = "";
    createdAt = "";
    updatedAt = "";
    managementNumberInput.value = "";
    managementNumberStateInput.value = "reissue";
    createdAtInput.value = "";
    updatedAtInput.value = "";
    numberDisplay.textContent = "未発行";
    displayCalculationIdentity("", "");
    document.querySelector("#calculation-datetime").textContent = "再計算が必要";
    jsonButton.disabled = true;
    htmlButton.disabled = true;
    updateOutputStatus();
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

function replaceRows(containerId, templateId, items, lengthName, quantityName) {
    const container = document.querySelector(`#${containerId}`);
    container.replaceChildren();
    (items.length ? items : [{}]).forEach((item) => {
        const row = document.querySelector(`#${templateId}`).content.cloneNode(true);
        row.querySelector(`[name="${lengthName}"]`).value = item.length_mm ?? "";
        row.querySelector(`[name="${quantityName}"]`).value = item.quantity ?? "";
        container.append(row);
    });
    updateAddRowButton(document.querySelector(`[data-add="${containerId}"]`));
}

function applyRecord(record, message) {
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
    managementNumberInput.value = managementNumber;
    managementNumberStateInput.value = "maintain";
    createdAt = record.created_at;
    updatedAt = record.updated_at;
    createdAtInput.value = createdAt;
    updatedAtInput.value = updatedAt;
    requiresManagementNumberReissue = false;
    hasValidResult = false;
    jsonExported = false;
    htmlExported = false;
    jsonLoadedPendingCalculation = true;
    numberDisplay.textContent = managementNumber;
    displayCalculationIdentity(managementNumber, record.updated_at);
    jsonButton.disabled = true;
    htmlButton.disabled = true;
    updateMode();
    setDirty(false);
    updateOutputStatus();
    messageDisplay.textContent = message;
}

function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exceedsJsonDepth(value, depth = 0) {
    if (depth > LOCAL_JSON_MAX_DEPTH) return true;
    if (Array.isArray(value)) return value.some((item) => exceedsJsonDepth(item, depth + 1));
    if (isPlainObject(value)) return Object.values(value).some((item) => exceedsJsonDepth(item, depth + 1));
    return false;
}

function requireSafeInteger(value, minimum, maximum) {
    if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    return value;
}

function requireText(value) {
    if (typeof value !== "string" || value.length > LOCAL_JSON_MAX_BYTES) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    return value;
}

function normalizeRows(rows, minimumRows, maximumRows, maximumQuantity) {
    if (!Array.isArray(rows) || rows.length < minimumRows || rows.length > maximumRows) {
        throw new LocalJsonValidationError("必要な入力情報が不足しています");
    }
    return rows.map((row) => {
        if (!isPlainObject(row)) throw new LocalJsonValidationError("JSONの形式が正しくありません");
        return {
            length_mm: requireSafeInteger(row.length_mm, 1, 1000000),
            quantity: requireSafeInteger(row.quantity, 1, maximumQuantity),
        };
    });
}

function validateLocalRecord(record) {
    if (!isPlainObject(record) || exceedsJsonDepth(record)) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    for (const key of ["format_version", "app_version", "management_number", "created_at", "updated_at", "input", "calculation_result"]) {
        if (!(key in record)) throw new LocalJsonValidationError("必要な入力情報が不足しています");
    }
    if (record.format_version !== "1.0") {
        throw new LocalJsonValidationError("このJSON形式のバージョンには対応していません");
    }
    if (!LEGACY_MANAGEMENT_NUMBER.test(record.management_number) && !CURRENT_MANAGEMENT_NUMBER.test(record.management_number)) {
        throw new LocalJsonValidationError("管理番号の形式が正しくありません");
    }
    if (!TOKYO_TIMESTAMP.test(record.created_at) || !TOKYO_TIMESTAMP.test(record.updated_at)
        || Number.isNaN(Date.parse(record.created_at)) || Number.isNaN(Date.parse(record.updated_at))) {
        throw new LocalJsonValidationError("日時の形式が正しくありません");
    }
    if (typeof record.app_version !== "string" || !isPlainObject(record.input) || !isPlainObject(record.calculation_result)) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    const input = record.input;
    if (!isPlainObject(input.metadata) || !isPlainObject(input.cutting_conditions)
        || !["required_stock", "inventory"].includes(input.mode)) {
        throw new LocalJsonValidationError("必要な入力情報が不足しています");
    }
    const metadata = {};
    for (const name of ["title", "material_type", "author", "notes"]) metadata[name] = requireText(input.metadata[name]);
    const normalizedInput = {
        mode: input.mode,
        metadata,
        cutting_conditions: {
            new_stock_length_mm: requireSafeInteger(input.cutting_conditions.new_stock_length_mm, 1, 1000000),
            kerf_mm: requireSafeInteger(input.cutting_conditions.kerf_mm, 0, 10000),
            left_trim_mm: requireSafeInteger(input.cutting_conditions.left_trim_mm, 0, 10000),
        },
        required_parts: normalizeRows(input.required_parts, 1, LOCAL_JSON_MAX_PART_ROWS, 500),
    };
    if (normalizedInput.required_parts.reduce((total, row) => total + row.quantity, 0) > 1000000) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    if (input.mode === "inventory") {
        if (!isPlainObject(input.inventory)) throw new LocalJsonValidationError("必要な入力情報が不足しています");
        normalizedInput.inventory = {
            new_stock_quantity: requireSafeInteger(input.inventory.new_stock_quantity, 0, 100000),
            remnants: normalizeRows(input.inventory.remnants, 0, LOCAL_JSON_MAX_REMNANT_ROWS, 100000),
        };
    } else if ("inventory" in input && input.inventory !== null) {
        throw new LocalJsonValidationError("JSONの形式が正しくありません");
    }
    return {
        format_version: record.format_version,
        app_version: record.app_version,
        management_number: record.management_number,
        created_at: record.created_at,
        updated_at: record.updated_at,
        input: normalizedInput,
        calculation_result: {},
    };
}

function captureCurrentState() {
    const data = new FormData(form);
    return {
        record: {
            management_number: managementNumber,
            created_at: createdAt,
            updated_at: updatedAt,
            input: {
                mode: data.get("mode"),
                metadata: Object.fromEntries(["title", "material_type", "author", "notes"].map((name) => [name, form.elements[name].value])),
                cutting_conditions: Object.fromEntries(["new_stock_length_mm", "kerf_mm", "left_trim_mm"].map((name) => [name, form.elements[name].value])),
                required_parts: data.getAll("part_length").map((length, index) => ({length_mm: length, quantity: data.getAll("part_quantity")[index]})),
                inventory: {new_stock_quantity: form.elements.new_stock_quantity.value, remnants: data.getAll("remnant_length").map((length, index) => ({length_mm: length, quantity: data.getAll("remnant_quantity")[index]}))},
            },
        },
        hasValidResult, jsonExported, htmlExported,
        requiresManagementNumberReissue, dirty, jsonLoadedPendingCalculation,
    };
}

function restoreCurrentState(snapshot) {
    applyRecord(snapshot.record, "");
    hasValidResult = snapshot.hasValidResult;
    jsonExported = snapshot.jsonExported;
    htmlExported = snapshot.htmlExported;
    requiresManagementNumberReissue = snapshot.requiresManagementNumberReissue;
    dirty = snapshot.dirty;
    jsonLoadedPendingCalculation = snapshot.jsonLoadedPendingCalculation;
    managementNumberStateInput.value = requiresManagementNumberReissue ? "reissue" : "maintain";
    jsonButton.disabled = !hasValidResult;
    htmlButton.disabled = !hasValidResult;
    updateOutputStatus();
}

async function loadLocalJson() {
    localJsonError.textContent = "";
    if (localJsonFileInput.files.length !== 1) {
        localJsonError.textContent = "JSONファイルを選択してください";
        return;
    }
    const file = localJsonFileInput.files[0];
    localJsonFilename.textContent = file.name;
    localJsonLoadButton.disabled = true;
    const previousState = captureCurrentState();
    try {
        if (!file.name.toLowerCase().endsWith(".json")) throw new LocalJsonValidationError("読み込めるJSONファイルではありません");
        const mimeType = file.type.toLowerCase();
        if (mimeType && mimeType !== "application/json" && mimeType !== "text/json" && !mimeType.endsWith("+json")) {
            throw new LocalJsonValidationError("読み込めるJSONファイルではありません");
        }
        if (file.size > LOCAL_JSON_MAX_BYTES) throw new LocalJsonValidationError("JSONファイルが大きすぎます");
        const text = await file.text();
        let parsed;
        try { parsed = JSON.parse(text); }
        catch (_error) { throw new LocalJsonValidationError("JSONの形式が正しくありません"); }
        const record = validateLocalRecord(parsed);
        try { applyRecord(record, "端末のJSONを読み込みました。再計算してください。"); }
        catch (_error) {
            restoreCurrentState(previousState);
            throw new Error("local apply failed");
        }
    } catch (error) {
        localJsonError.textContent = error instanceof LocalJsonValidationError
            ? error.message : "読込に失敗しました。現在の入力内容は変更されていません";
    } finally {
        localJsonFileInput.value = "";
        localJsonLoadButton.disabled = false;
    }
}

function protectedAction(action) {
    if (!dirty) { action(); return; }
    pendingAction = action;
    unsavedDialog.showModal();
}

unsavedDialog.addEventListener("click", (event) => {
    if (!event.target.value) return;
    const choice = event.target.value;
    unsavedDialog.close();
    if (choice === "cancel") { pendingAction = null; return; }
    const action = pendingAction;
    pendingAction = null;
    if (action) action();
});

form.addEventListener("input", (event) => {
    invalidateCalculationResult();
    const input = event.target.closest(".field-error-input");
    if (!input) return;
    const messageId = input.getAttribute("aria-describedby");
    input.classList.remove("field-error-input");
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
    if (messageId) document.querySelector(`#${messageId}`)?.remove();
});
form.addEventListener("change", invalidateCalculationResult);
document.querySelector(".common-information").addEventListener("input", invalidateCalculationResult);
document.querySelector(".common-information").addEventListener("change", invalidateCalculationResult);
localJsonFileInput.addEventListener("change", () => {
    localJsonFilename.textContent = localJsonFileInput.files.length === 1 ? localJsonFileInput.files[0].name : "ファイル未選択";
    localJsonError.textContent = "";
});
localJsonLoadButton.addEventListener("click", () => protectedAction(loadLocalJson));
resetButton.addEventListener("click", () => protectedAction(() => {
    setDirty(false);
    window.location.assign("/");
}));
function downloadFilename(response) {
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    return match?.[1] || `${managementNumber}.json`;
}

async function downloadJson() {
    if (!hasValidResult || requiresManagementNumberReissue || !managementNumber || exportingJson) {
        messageDisplay.textContent = "有効な計算結果がありません。再計算してください。";
        return false;
    }
    exportingJson = true;
    jsonButton.disabled = true;
    let objectUrl = "";
    try {
        const response = await fetch("/api/export/json", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({input: formInput(), management_number: managementNumber, created_at: createdAt, updated_at: updatedAt}),
        });
        if (!response.ok) throw new Error("JSON出力に失敗しました。");
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = downloadFilename(response);
        link.click();
        jsonExported = true;
        setDirty(false);
        updateOutputStatus();
        messageDisplay.textContent = "JSON出力済み";
        return true;
    } catch (error) {
        jsonExported = false;
        updateOutputStatus();
        messageDisplay.textContent = error.message || "JSON出力に失敗しました。";
        return false;
    } finally {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        exportingJson = false;
        jsonButton.disabled = !hasValidResult;
    }
}

jsonButton.addEventListener("click", downloadJson);

async function downloadHtml() {
    if (!hasValidResult || requiresManagementNumberReissue || !managementNumber || exportingHtml) {
        messageDisplay.textContent = "有効な計算結果がありません。再計算してください。";
        return false;
    }
    exportingHtml = true;
    htmlButton.disabled = true;
    let objectUrl = "";
    try {
        const response = await fetch("/api/export/html", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({input: formInput(), management_number: managementNumber, created_at: createdAt, updated_at: updatedAt}),
        });
        if (!response.ok) throw new Error("HTML出力に失敗しました。");
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = `${managementNumber}.html`;
        link.click();
        htmlExported = true;
        setDirty(false);
        updateOutputStatus();
        messageDisplay.textContent = "HTML出力済み";
        return true;
    } catch (error) {
        htmlExported = false;
        updateOutputStatus();
        messageDisplay.textContent = error.message || "HTML出力に失敗しました。";
        return false;
    } finally {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        exportingHtml = false;
        htmlButton.disabled = !hasValidResult;
    }
}

htmlButton.addEventListener("click", downloadHtml);
window.addEventListener("beforeunload", (event) => {
    if (dirty && !suppressBeforeUnload) {
        event.preventDefault();
        event.returnValue = "";
    }
});
window.addEventListener("pageshow", resetCalculationSubmission);
managementNumberInput.value = managementNumber;
managementNumberStateInput.value = requiresManagementNumberReissue ? "reissue" : "maintain";
createdAtInput.value = createdAt;
updatedAtInput.value = updatedAt;
jsonButton.disabled = !hasValidResult;
htmlButton.disabled = !hasValidResult;
updateOutputStatus();
