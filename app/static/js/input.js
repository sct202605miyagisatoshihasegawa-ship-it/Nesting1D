const inventoryFields = document.querySelector(".inventory-fields");
const form = document.querySelector("#calculation-form");

function updateMode() {
    const selected = document.querySelector('input[name="mode"]:checked');
    inventoryFields.hidden = !selected || selected.value !== "inventory";
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
    }
});

form.addEventListener("submit", () => {
    const button = form.querySelector(".calculate-button");
    button.disabled = true;
    document.querySelector("#processing").hidden = false;
});

updateMode();

const resultTabs = document.querySelector(".result-tabs");
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
}
