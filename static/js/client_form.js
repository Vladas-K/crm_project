document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("client-form");
    if (!form) return;
    const lead = form.elements.lead;
    const manager = form.elements.manager;
    const managerSelectionChanged = form.elements.manager_selection_changed;
    const canImportManager = () => !form.dataset.clientId && !["true", "1", "on"].includes(managerSelectionChanged.value.toLowerCase());
    manager.addEventListener("change", () => { managerSelectionChanged.value = "true"; });
    const type = form.elements.client_type;
    const name = form.elements.name;
    const nameLabel = form.querySelector(`label[for="${name.id}"]`);
    const section = form.querySelector("[data-lead-section]");
    const search = document.getElementById("client-lead-search");
    const status = document.getElementById("client-lead-status");
    let imported = {};
    let searchController;
    let contactController;
    let timer;
    const endpoint = (params) => {
        const url = new URL(form.dataset.leadUrl, window.location.origin);
        Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
        if (form.dataset.clientId) url.searchParams.set("client_id", form.dataset.clientId);
        return url;
    };
    const updateType = () => {
        nameLabel.firstChild.textContent = type.value === "b2b" ? "Название компании" : "Имя клиента";
        name.autocomplete = type.value === "b2b" ? "organization" : "name";
    };
    const updateMode = (event) => {
        const mode = form.querySelector('input[name="creation_mode"]:checked');
        section.hidden = Boolean(mode && mode.value === "manual");
        lead.disabled = section.hidden;
        if (section.hidden) {
            lead.value = "";
            form.elements.lead_contacts_loaded.value = "";
            contactController?.abort();
            if (event && canImportManager()) manager.value = "";
        }
    };
    type.addEventListener("change", updateType);
    form.querySelectorAll('input[name="creation_mode"]').forEach((radio) => radio.addEventListener("change", updateMode));
    updateType();
    updateMode();
    form.querySelectorAll("[data-russian-phone]").forEach((input) => input.addEventListener("input", () => {
        const value = input.value.trimStart();
        if (value.startsWith("8")) input.value = `+7${value.slice(1)}`;
    }));
    search.addEventListener("input", () => {
        clearTimeout(timer);
        searchController?.abort();
        const query = search.value.trim();
        if (query.length < 2) {
            status.textContent = "Для поиска введите не менее двух символов.";
            return;
        }
        timer = setTimeout(async () => {
            searchController = new AbortController();
            try {
                const response = await fetch(endpoint({ q: query }), { signal: searchController.signal });
                if (!response.ok) throw new Error();
                const data = await response.json();
                const selected = lead.selectedOptions[0]?.cloneNode(true);
                lead.replaceChildren(new Option("Выберите исходный лид", ""));
                if (selected?.value) lead.add(selected);
                data.results.forEach((item) => {
                    if (selected?.value !== String(item.id)) lead.add(new Option(`${item.name}${item.contact ? ` · ${item.contact}` : ""}`, item.id));
                });
                lead.value = selected?.value || "";
                status.textContent = data.results.length ? "Выберите лид из найденных вариантов." : "Доступных лидов не найдено.";
            } catch (error) {
                if (error.name !== "AbortError") status.textContent = "Поиск недоступен. Можно выбрать лид из списка или повторить поиск.";
            }
        }, 250);
    });
    lead.addEventListener("change", async () => {
        contactController?.abort();
        if (!lead.value) {
            if (canImportManager()) manager.value = "";
            return;
        }
        const selectedId = lead.value;
        contactController = new AbortController();
        status.textContent = "Загружаем контакты лида…";
        try {
            const response = await fetch(endpoint({ lead_id: selectedId }), { signal: contactController.signal });
            if (!response.ok) throw new Error();
            const data = await response.json();
            if (lead.value !== selectedId || lead.disabled) return;
            if (canImportManager()) manager.value = data.manager_id == null ? "" : String(data.manager_id);
            Object.entries(data.fields).forEach(([key, value]) => {
                const input = form.elements[key];
                if (input && (!input.value.trim() || input.value === imported[key])) input.value = value;
            });
            imported = data.fields;
            form.elements.lead_contacts_loaded.value = selectedId;
            if (["max_messenger", "instagram", "facebook", "vk"].some((key) => form.elements[key].value)) {
                form.querySelector("details").open = true;
            }
            status.textContent = "Контакты лида перенесены. Проверьте данные перед сохранением.";
        } catch (error) {
            if (error.name !== "AbortError") status.textContent = "Не удалось загрузить контакты. Проверьте лид и повторите выбор.";
        }
    });
});
