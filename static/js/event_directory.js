(() => {
    const form = document.querySelector('[data-event-filters]');
    if (!form) return;
    const period = form.querySelector('[data-event-period]');
    const dateRange = form.querySelector('[data-event-date-range]');
    const updatePeriod = () => {
        const custom = period.value === 'custom';
        dateRange.hidden = !custom;
        dateRange.querySelectorAll('input').forEach((input) => { input.disabled = !custom; });
    };
    period.addEventListener('change', updatePeriod);
    updatePeriod();

    const wrapper = form.querySelector('[data-event-search]');
    const input = wrapper.querySelector('input');
    const suggestions = wrapper.querySelector('[role="listbox"]');
    const status = wrapper.querySelector('[data-search-status]');
    let timer;
    let controller;
    let version = 0;
    let activeIndex = -1;

    const hide = () => {
        suggestions.hidden = true;
        suggestions.replaceChildren();
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        activeIndex = -1;
    };
    const dismiss = () => {
        clearTimeout(timer);
        controller?.abort();
        version += 1;
        hide();
    };
    const activate = (index) => {
        const options = [...suggestions.children];
        if (!options.length) return;
        activeIndex = (index + options.length) % options.length;
        options.forEach((option, position) => option.setAttribute('aria-selected', String(position === activeIndex)));
        input.setAttribute('aria-activedescendant', options[activeIndex].id);
        options[activeIndex].scrollIntoView({block: 'nearest'});
    };
    const render = (results) => {
        hide();
        status.textContent = results.length ? `Подсказок: ${results.length}. Используйте стрелки и Enter.` : 'Совпадений в подсказках нет.';
        results.forEach((item, index) => {
            const option = document.createElement('button');
            const name = document.createElement('strong');
            const context = document.createElement('span');
            option.type = 'button';
            option.tabIndex = -1;
            option.id = `event-suggestion-${index}`;
            option.className = 'crm-suggestions__item';
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false');
            name.textContent = item.title;
            context.textContent = `${item.client} · ${item.city}`;
            option.append(name, context);
            option.addEventListener('click', () => {
                dismiss();
                window.location.assign(item.url);
            });
            suggestions.append(option);
        });
        suggestions.hidden = !results.length;
        input.setAttribute('aria-expanded', String(Boolean(results.length)));
    };
    input.addEventListener('input', () => {
        dismiss();
        status.textContent = '';
        const query = input.value.trim();
        if (query.length < 2) return;
        const requestVersion = version;
        timer = setTimeout(async () => {
            const currentController = new AbortController();
            controller = currentController;
            const url = new URL(wrapper.dataset.autocompleteUrl, window.location.origin);
            url.searchParams.set('q', query);
            try {
                const response = await fetch(url, {signal: currentController.signal});
                if (!response.ok) throw new Error('Search unavailable');
                const data = await response.json();
                if (version === requestVersion) render(data.results);
            } catch (error) {
                if (error.name !== 'AbortError' && version === requestVersion) {
                    hide();
                    status.textContent = 'Подсказки недоступны. Для поиска нажмите «Показать».';
                }
            }
        }, 250);
    });
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' || event.key === 'Tab') dismiss();
        if (suggestions.hidden) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            activate(event.key === 'ArrowDown' ? activeIndex + 1 : (activeIndex < 0 ? -1 : activeIndex - 1));
        } else if (event.key === 'Enter' && activeIndex >= 0) {
            event.preventDefault();
            suggestions.children[activeIndex].click();
        }
    });
    document.addEventListener('click', (event) => {
        if (!wrapper.contains(event.target)) dismiss();
    });
    form.addEventListener('submit', dismiss);
})();
