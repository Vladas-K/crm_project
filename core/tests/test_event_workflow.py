import pytest
from decimal import Decimal
from django.urls import reverse

from core.models import CRMRole, EventExpense, EventTask, EventVendor, TeamMemberProfile


def login_user(client, django_user_model, **profile_flags):
    user = django_user_model.objects.create_user(username="workflow_user", password="TestPass123!")
    defaults = {
        "role": CRMRole.PROJECT_MANAGER,
        "can_view_finance": False,
        "can_view_clients": True,
        "can_view_analytics": False,
        "can_manage_system": False,
    }
    defaults.update(profile_flags)
    TeamMemberProfile.objects.create(user=user, **defaults)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_nested_task_create_returns_to_tasks_tab(client, django_user_model, crm_objects):
    """Создание задачи из карточки мероприятия возвращает на вкладку задач."""
    login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_task_create', kwargs={'event_pk': event.pk})}?return_tab=tasks",
        {
            "title": "Проверить монтаж",
            "description": "Контрольный созвон с площадкой",
            "deadline_offset_days": "0",
            "status": EventTask.Status.TODO,
            "return_tab": "tasks",
        },
    )
    task = event.tasks.get(title="Проверить монтаж")

    assert task.event == event
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=tasks"


@pytest.mark.django_db
def test_nested_task_update_returns_to_tasks_tab(client, django_user_model, crm_objects):
    """Редактирование задачи из карточки мероприятия возвращает на вкладку задач."""
    login_user(client, django_user_model)
    task = crm_objects["task"]

    response = client.post(
        f"{reverse('core:task_update', kwargs={'pk': task.pk})}?return_tab=tasks",
        {
            "event": task.event.pk,
            "title": "Подготовить обновлённый бриф",
            "description": "Обновить вводные по проекту",
            "deadline_offset_days": "0",
            "status": EventTask.Status.IN_PROGRESS,
            "return_tab": "tasks",
        },
    )
    task.refresh_from_db()

    assert task.title == "Подготовить обновлённый бриф"
    assert task.status == EventTask.Status.IN_PROGRESS
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': task.event.pk})}?tab=tasks"


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


@pytest.mark.django_db
def test_nested_expense_create_returns_to_expenses_tab(client, django_user_model, crm_objects):
    """Создание расхода из карточки мероприятия возвращает на вкладку расходов."""
    login_user(client, django_user_model, can_view_finance=True)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_expense_create', kwargs={'event_pk': event.pk})}?return_tab=expenses",
        {
            "category": "Кейтеринг",
            "vendor_name": "Food Team",
            "amount": "45000.00",
            "prepayment": "15000.00",
            "payment_status": EventExpense.PaymentStatus.PARTIAL,
            "return_tab": "expenses",
        },
    )
    expense = event.expenses.get(category="Кейтеринг")

    assert expense.event == event
    assert expense.amount == Decimal("45000.00")
    assert expense.prepayment == Decimal("15000.00")
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=expenses"


@pytest.mark.django_db
def test_nested_expense_update_returns_to_expenses_tab(client, django_user_model, crm_objects):
    """Редактирование расхода из карточки мероприятия возвращает на вкладку расходов."""
    login_user(client, django_user_model, can_view_finance=True)
    expense = crm_objects["expense"]

    response = client.post(
        f"{reverse('core:event_expense_update', kwargs={'pk': expense.pk})}?return_tab=expenses",
        {
            "event": expense.event.pk,
            "category": "Площадка обновлена",
            "vendor_name": "Venue Team",
            "amount": "65000.00",
            "prepayment": "25000.00",
            "payment_status": EventExpense.PaymentStatus.PAID,
            "return_tab": "expenses",
        },
    )
    expense.refresh_from_db()

    assert expense.category == "Площадка обновлена"
    assert expense.amount == Decimal("65000.00")
    assert expense.prepayment == Decimal("25000.00")
    assert expense.payment_status == EventExpense.PaymentStatus.PAID
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': expense.event.pk})}?tab=expenses"
