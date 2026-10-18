(() => {
    const form = document.querySelector('[data-lead-stage-form]');
    if (!form) return;
    const stage = form.elements.stage;
    const reason = form.querySelector('[data-loss-reason]');
    const lostIds = JSON.parse(stage.dataset.lostStageIds);
    const updateReason = () => {
        const isLost = lostIds.includes(stage.value);
        reason.hidden = !isLost;
        form.elements.loss_reason.required = isLost;
    };
    stage.addEventListener('change', updateReason);
    updateReason();
})();
