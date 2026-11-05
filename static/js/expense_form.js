(() => {
    const preview = document.querySelector('[data-expense-preview]');
    if (!preview) return;
    const amount = document.getElementById('id_amount');
    const paid = document.getElementById('id_paid_amount');
    const cents = (value) => {
        const text = value.trim().replace(',', '.');
        if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null;
        const [whole, fraction = ''] = text.split('.');
        return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
    };
    const money = new Intl.NumberFormat('ru-RU', {style: 'currency', currency: 'RUB', minimumFractionDigits: 0, maximumFractionDigits: 2});
    const update = () => {
        const total = cents(amount.value);
        const payment = cents(paid.value);
        preview.hidden = false;
        if (total === null || payment === null || payment > total) {
            preview.textContent = 'Укажите неотрицательные суммы. Оплата не может превышать сумму расхода.';
            return;
        }
        const status = payment === 0 ? 'Запланировано' : payment < total ? 'Частично оплачено' : 'Оплачено';
        preview.textContent = `Осталось оплатить: ${money.format((total - payment) / 100)} · ${status}`;
    };
    amount.addEventListener('input', update);
    paid.addEventListener('input', update);
    update();
})();
