import pytest
from django.urls import reverse

from core.models import EventTask, EventVendor


def login_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="workflow_user", password="TestPass123!")
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_task_status_quick_action_updates_status_and_returns_to_tasks_tab(client, django_user_model, crm_objects):
    """Быстрое действие карточки меняет статус задачи и возвращает на вкладку задач."""
    login_user(client, django_user_model)
    task = crm_objects["task"]

    response = client.post(
        reverse("core:task_status_update", kwargs={"pk": task.pk}),
        {"status": EventTask.Status.IN_PROGRESS},
    )
    task.refresh_from_db()

    assert task.status == EventTask.Status.IN_PROGRESS
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': task.event.pk})}?tab=tasks"


@pytest.mark.django_db
def test_task_status_quick_action_ignores_invalid_status(client, django_user_model, crm_objects):
    """Невалидный быстрый статус не меняет задачу."""
    login_user(client, django_user_model)
    task = crm_objects["task"]
    original_status = task.status

    response = client.post(
        reverse("core:task_status_update", kwargs={"pk": task.pk}),
        {"status": "not_a_real_status"},
    )
    task.refresh_from_db()

    assert task.status == original_status
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': task.event.pk})}?tab=tasks"


@pytest.mark.django_db
def test_event_vendor_status_quick_action_updates_status_and_returns_to_vendors_tab(
    client,
    django_user_model,
    crm_objects,
):
    """Быстрое действие карточки меняет статус подрядчика и возвращает на вкладку подрядчиков."""
    login_user(client, django_user_model)
    assignment = crm_objects["event_vendor"]

    response = client.post(
        reverse("core:event_vendor_status_update", kwargs={"pk": assignment.pk}),
        {"status": EventVendor.Status.APPROVED},
    )
    assignment.refresh_from_db()

    assert assignment.status == EventVendor.Status.APPROVED
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': assignment.event.pk})}?tab=vendors"


@pytest.mark.django_db
def test_event_vendor_status_quick_action_ignores_invalid_status(client, django_user_model, crm_objects):
    """Невалидный быстрый статус не меняет назначение подрядчика."""
    login_user(client, django_user_model)
    assignment = crm_objects["event_vendor"]
    original_status = assignment.status

    response = client.post(
        reverse("core:event_vendor_status_update", kwargs={"pk": assignment.pk}),
        {"status": "not_a_real_status"},
    )
    assignment.refresh_from_db()

    assert assignment.status == original_status
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': assignment.event.pk})}?tab=vendors"
