(() => {
    const filters = document.querySelector('.team-filter-extra');
    if (!filters) return;
    // Без JavaScript все фильтры остаются доступными в открытом details.
    const mobile = window.matchMedia('(max-width: 767.98px)');
    const updateLayout = () => {
        filters.open = !mobile.matches || filters.dataset.active === 'true';
    };
    filters.classList.add('is-enhanced');
    mobile.addEventListener('change', updateLayout);
    updateLayout();
})();
