(() => {
    const vendor = document.getElementById('id_vendor');
    const role = document.getElementById('id_role');
    if (!vendor || !role) return;
    const roles = JSON.parse(vendor.dataset.roleMap || '{}');
    const update = (selected = '') => {
        const choices = roles[vendor.value] || [];
        const placeholder = !vendor.value ? 'Сначала выберите подрядчика'
            : choices.length ? 'Выберите роль' : 'Добавьте роль в профиле подрядчика';
        role.replaceChildren(new Option(placeholder, ''));
        choices.forEach(name => role.add(new Option(name, name)));
        role.value = choices.includes(selected) ? selected : '';
    };
    vendor.addEventListener('change', () => update());
    update(role.value);
})();
