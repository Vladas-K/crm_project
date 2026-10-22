(() => {
    const sidebar = document.querySelector('.crm-shell > .crm-sidebar');
    const dialog = document.querySelector('#crm-mobile-navigation');
    const trigger = document.querySelector('.crm-mobile-bar button');
    if (!sidebar || !dialog || !trigger || typeof dialog.showModal !== 'function') return;

    const mobile = window.matchMedia('(max-width: 991.98px)');
    const anchor = document.createComment('sidebar position');
    sidebar.after(anchor);

    const updateClosedState = () => {
        document.body.classList.remove('crm-navigation-open');
        trigger.setAttribute('aria-expanded', 'false');
    };
    const close = () => {
        dialog.close();
        updateClosedState();
    };
    const updateLayout = () => {
        if (dialog.open) close();
        if (mobile.matches) dialog.append(sidebar);
        else anchor.before(sidebar);
    };
    trigger.addEventListener('click', () => {
        if (!mobile.matches) return;
        dialog.showModal();
        document.body.classList.add('crm-navigation-open');
        trigger.setAttribute('aria-expanded', 'true');
    });
    dialog.querySelector('button').addEventListener('click', close);
    dialog.addEventListener('close', updateClosedState);
    dialog.addEventListener('click', (event) => {
        const rect = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) close();
        if (event.target.closest('a[href]')) close();
    });
    mobile.addEventListener('change', updateLayout);
    window.addEventListener('pageshow', () => { if (dialog.open) close(); });
    updateLayout();
    document.body.classList.add('crm-mobile-navigation-ready');
})();
