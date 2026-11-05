(() => {
    const source = document.getElementById('timeline-responsible-contacts');
    const vendor = document.getElementById('id_responsible_vendor');
    const name = document.getElementById('id_responsible');
    const phone = document.getElementById('id_responsible_phone');
    if (!source || !vendor || !name || !phone) return;
    const contacts = JSON.parse(source.textContent);
    const update = () => {
        const contact = contacts[vendor.value];
        name.readOnly = phone.readOnly = Boolean(contact);
        if (contact) {
            name.value = contact.name;
            phone.value = contact.phone;
        }
    };
    vendor.addEventListener('change', update);
    update();
})();
