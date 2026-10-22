(() => {
    const filters = document.querySelector('.task-directory-filters__extra');
    if (!filters) return;
    const mobile = window.matchMedia('(max-width: 767.98px)');
    const updateLayout = () => {
        filters.open = !mobile.matches || filters.dataset.active === 'true';
    };
    mobile.addEventListener('change', updateLayout);
    updateLayout();
})();
