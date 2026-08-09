import pytest
from decimal import Decimal
from django.urls import reverse

from core.models import (
    CRMRole,
    EventCommunication,
    EventDocument,
    EventExpense,
    EventOutcome,
    EventRisk,
    EventTask,
    EventTimelineItem,
    EventVendor,
    TeamMemberProfile,
)


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
def test_nested_timeline_create_returns_to_timeline_tab(client, django_user_model, crm_objects):
    """Создание блока тайминга из карточки мероприятия возвращает на вкладку тайминга."""
    login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_timeline_create', kwargs={'event_pk': event.pk})}?return_tab=timeline",
        {
            "event": event.pk,
            "time": "10:30",
            "block": "Регистрация гостей",
            "description": "Встреча гостей и выдача бейджей",
            "responsible": "Координатор",
            "return_tab": "timeline",
        },
    )
    item = event.timeline_items.get(block="Регистрация гостей")

    assert item.event == event
    assert item.time.strftime("%H:%M") == "10:30"
    assert item.responsible == "Координатор"
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=timeline"


@pytest.mark.django_db
def test_nested_timeline_update_returns_to_timeline_tab(client, django_user_model, crm_objects):
    """Редактирование блока тайминга возвращает на вкладку тайминга."""
    login_user(client, django_user_model)
    item = EventTimelineItem.objects.create(
        event=crm_objects["event"],
        time="09:00",
        block="Сбор команды",
        description="Подготовка площадки",
        responsible="Продюсер",
    )

    response = client.post(
        f"{reverse('core:event_timeline_update', kwargs={'pk': item.pk})}?return_tab=timeline",
        {
            "event": item.event.pk,
            "time": "11:15",
            "block": "Открытие",
            "description": "Приветственное слово",
            "responsible": "Ведущий",
            "return_tab": "timeline",
        },
    )
    item.refresh_from_db()

    assert item.time.strftime("%H:%M") == "11:15"
    assert item.block == "Открытие"
    assert item.description == "Приветственное слово"
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': item.event.pk})}?tab=timeline"


@pytest.mark.django_db
def test_nested_risk_create_returns_to_risks_tab(client, django_user_model, crm_objects):
    """Создание риска из карточки мероприятия возвращает на вкладку рисков."""
    login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_risk_create', kwargs={'event_pk': event.pk})}?return_tab=risks",
        {
            "event": event.pk,
            "description": "Площадка может задержать монтаж",
            "probability": EventRisk.Probability.HIGH,
            "plan_b": "Перенести монтаж на резервную площадку",
            "return_tab": "risks",
        },
    )
    risk = event.risks.get(description="Площадка может задержать монтаж")

    assert risk.event == event
    assert risk.probability == EventRisk.Probability.HIGH
    assert risk.plan_b == "Перенести монтаж на резервную площадку"
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=risks"


@pytest.mark.django_db
def test_nested_risk_update_returns_to_risks_tab(client, django_user_model, crm_objects):
    """Редактирование риска из карточки мероприятия возвращает на вкладку рисков."""
    login_user(client, django_user_model)
    risk = EventRisk.objects.create(
        event=crm_objects["event"],
        description="Сбой доставки оборудования",
        probability=EventRisk.Probability.MEDIUM,
        plan_b="Подготовить резервный транспорт",
    )

    response = client.post(
        f"{reverse('core:event_risk_update', kwargs={'pk': risk.pk})}?return_tab=risks",
        {
            "event": risk.event.pk,
            "description": "Сбой доставки обновлённого оборудования",
            "probability": EventRisk.Probability.LOW,
            "plan_b": "Использовать локального поставщика",
            "return_tab": "risks",
        },
    )
    risk.refresh_from_db()

    assert risk.description == "Сбой доставки обновлённого оборудования"
    assert risk.probability == EventRisk.Probability.LOW
    assert risk.plan_b == "Использовать локального поставщика"
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': risk.event.pk})}?tab=risks"


@pytest.mark.django_db
def test_nested_outcome_create_returns_to_outcome_tab(client, django_user_model, crm_objects):
    """Создание итогов из карточки мероприятия возвращает на вкладку итогов."""
    login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_outcome_create', kwargs={'event_pk': event.pk})}?return_tab=outcome",
        {
            "event": event.pk,
            "client_feedback": "Клиент отметил точную организацию программы",
            "final_profit": "125000.00",
            "lessons_learned": "Закладывать больше времени на монтаж",
            "media_links": "https://example.com/event-media",
            "project_rating": "5",
            "return_tab": "outcome",
        },
    )
    outcome = event.outcome

    assert outcome.event == event
    assert outcome.final_profit == Decimal("125000.00")
    assert outcome.project_rating == 5
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=outcome"


@pytest.mark.django_db
def test_nested_outcome_update_returns_to_outcome_tab(client, django_user_model, crm_objects):
    """Редактирование итогов из карточки мероприятия возвращает на вкладку итогов."""
    login_user(client, django_user_model)
    outcome = EventOutcome.objects.create(
        event=crm_objects["event"],
        client_feedback="Хорошая работа",
        final_profit=90000,
        lessons_learned="Согласовывать тайминг заранее",
        project_rating=4,
    )

    response = client.post(
        f"{reverse('core:event_outcome_update', kwargs={'pk': outcome.pk})}?return_tab=outcome",
        {
            "event": outcome.event.pk,
            "client_feedback": "Клиент рекомендовал нас партнёрам",
            "final_profit": "110000.00",
            "lessons_learned": "Сохранить текущий процесс согласований",
            "media_links": "https://example.com/final-materials",
            "project_rating": "5",
            "return_tab": "outcome",
        },
    )
    outcome.refresh_from_db()

    assert outcome.client_feedback == "Клиент рекомендовал нас партнёрам"
    assert outcome.final_profit == Decimal("110000.00")
    assert outcome.project_rating == 5
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': outcome.event.pk})}?tab=outcome"


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


@pytest.mark.django_db
def test_nested_event_vendor_create_returns_to_vendors_tab(client, django_user_model, crm_objects):
    """Создание назначения подрядчика возвращает на вкладку подрядчиков."""
    login_user(client, django_user_model)
    event = crm_objects["event"]
    vendor = crm_objects["vendor"]

    response = client.post(
        f"{reverse('core:event_vendor_create', kwargs={'event_pk': event.pk})}?return_tab=vendors",
        {
            "event": event.pk,
            "vendor": vendor.pk,
            "role": "Координатор",
            "cost": "35000.00",
            "status": EventVendor.Status.PROPOSED,
            "return_tab": "vendors",
        },
    )
    assignment = event.event_vendors.get(role="Координатор")

    assert assignment.event == event
    assert assignment.vendor == vendor
    assert assignment.cost == Decimal("35000.00")
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=vendors"


@pytest.mark.django_db
def test_nested_event_vendor_update_returns_to_vendors_tab(client, django_user_model, crm_objects):
    """Редактирование назначения подрядчика возвращает на вкладку подрядчиков."""
    login_user(client, django_user_model)
    assignment = crm_objects["event_vendor"]

    response = client.post(
        f"{reverse('core:event_vendor_update', kwargs={'pk': assignment.pk})}?return_tab=vendors",
        {
            "event": assignment.event.pk,
            "vendor": assignment.vendor.pk,
            "role": "Технический координатор",
            "cost": "65000.00",
            "status": EventVendor.Status.APPROVED,
            "return_tab": "vendors",
        },
    )
    assignment.refresh_from_db()

    assert assignment.role == "Технический координатор"
    assert assignment.cost == Decimal("65000.00")
    assert assignment.status == EventVendor.Status.APPROVED
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': assignment.event.pk})}?tab=vendors"


@pytest.mark.django_db
def test_nested_communication_create_returns_to_communications_tab(client, django_user_model, crm_objects):
    """Создание коммуникации из карточки мероприятия возвращает на вкладку коммуникаций."""
    user = login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_communication_create', kwargs={'event_pk': event.pk})}?return_tab=communications",
        {
            "event": event.pk,
            "communication_type": EventCommunication.Type.MEETING,
            "date": "2026-08-09 14:30",
            "comment": "Встреча с клиентом по финальным деталям",
            "manager": user.pk,
            "return_tab": "communications",
        },
    )
    communication = event.communications.get(comment="Встреча с клиентом по финальным деталям")

    assert communication.event == event
    assert communication.communication_type == EventCommunication.Type.MEETING
    assert communication.manager == user
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=communications"


@pytest.mark.django_db
def test_nested_communication_update_returns_to_communications_tab(client, django_user_model, crm_objects):
    """Редактирование коммуникации из карточки мероприятия возвращает на вкладку коммуникаций."""
    user = login_user(client, django_user_model)
    communication = crm_objects["communication"]

    response = client.post(
        f"{reverse('core:event_communication_update', kwargs={'pk': communication.pk})}?return_tab=communications",
        {
            "event": communication.event.pk,
            "communication_type": EventCommunication.Type.MESSAGE,
            "date": "2026-08-09 16:00",
            "comment": "Отправлены обновлённые материалы",
            "manager": user.pk,
            "return_tab": "communications",
        },
    )
    communication.refresh_from_db()

    assert communication.communication_type == EventCommunication.Type.MESSAGE
    assert communication.comment == "Отправлены обновлённые материалы"
    assert communication.manager == user
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': communication.event.pk})}?tab=communications"


@pytest.mark.django_db
def test_nested_document_create_returns_to_documents_tab(client, django_user_model, crm_objects):
    """Создание документа из карточки мероприятия возвращает на вкладку документов."""
    login_user(client, django_user_model)
    event = crm_objects["event"]

    response = client.post(
        f"{reverse('core:event_document_create', kwargs={'event_pk': event.pk})}?return_tab=documents",
        {
            "event": event.pk,
            "document_type": EventDocument.Type.INVOICE,
            "status": EventDocument.Status.DRAFT,
            "return_tab": "documents",
        },
    )
    document = event.documents.get(document_type=EventDocument.Type.INVOICE)

    assert document.event == event
    assert document.status == EventDocument.Status.DRAFT
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab=documents"


@pytest.mark.django_db
def test_nested_document_update_returns_to_documents_tab(client, django_user_model, crm_objects):
    """Редактирование документа из карточки мероприятия возвращает на вкладку документов."""
    login_user(client, django_user_model)
    document = crm_objects["document"]

    response = client.post(
        f"{reverse('core:event_document_update', kwargs={'pk': document.pk})}?return_tab=documents",
        {
            "event": document.event.pk,
            "document_type": EventDocument.Type.CONTRACT,
            "status": EventDocument.Status.SIGNED,
            "return_tab": "documents",
        },
    )
    document.refresh_from_db()

    assert document.document_type == EventDocument.Type.CONTRACT
    assert document.status == EventDocument.Status.SIGNED
    assert response.status_code == 302
    assert response.url == f"{reverse('core:event_detail', kwargs={'pk': document.event.pk})}?tab=documents"
