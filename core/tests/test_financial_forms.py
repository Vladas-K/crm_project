from decimal import Decimal

import pytest
from django.urls import reverse

from core.models import CRMRole, Event, EventOutcome, TeamMemberProfile


@pytest.fixture(params=["event_create", "event_update", "event_outcome_create", "event_outcome_update"])
def financial_form_case(request, crm_objects):
    """Готовит четыре публичных сценария работы с финансовыми полями."""
    event = crm_objects["event"]
    original_value = Decimal("98765.43")
    is_update = request.param.endswith("update")
    if "outcome" in request.param:
        model = EventOutcome
        instance = EventOutcome.objects.create(event=event, final_profit=original_value) if is_update else None
        kwargs = {"pk": instance.pk} if is_update else {"event_pk": event.pk}
        field = "final_profit"
        ordinary_field = "client_feedback"
        payload = {
            "event": event.pk,
            "client_feedback": "Проверка сохранения обычных данных",
            "lessons_learned": "Согласовывать тайминг заранее",
            "media_links": "https://example.com/event-materials",
            "project_rating": "4",
        }
        expected_value = original_value if is_update else None
    else:
        model = Event
        event.planned_budget = original_value
        event.save(update_fields=["planned_budget"])
        instance = event if is_update else None
        kwargs = {"pk": event.pk} if is_update else {}
        field = "planned_budget"
        ordinary_field = "title"
        payload = {
            "client": event.client_id,
            "event_format": event.event_format_id,
            "title": "Проверка сохранения обычных данных",
            "date": event.date.isoformat(),
            "city": "Москва",
            "guests_count": "30",
            "status": event.status,
        }
        expected_value = original_value if is_update else Decimal("0")
    return {
        "url": reverse(f"core:{request.param}", kwargs=kwargs),
        "model": model,
        "instance": instance,
        "field": field,
        "ordinary_field": ordinary_field,
        "payload": payload,
        "expected_value": expected_value,
    }


def login_operator(client, django_user_model, *, can_view_finance, can_manage_events=True):
    user = django_user_model.objects.create_user(username="financial_form_operator", password="TestPass123!")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_finance=can_view_finance,
        can_manage_events=can_manage_events,
    )
    client.force_login(user)


@pytest.mark.django_db
@pytest.mark.parametrize("submitted_value", [None, "765432.10", "invalid"])
def test_financial_form_restricts_fields_without_finance_access(
    client, django_user_model, financial_form_case, submitted_value
):
    """Скрытые поля не раскрываются и не меняются при подмене POST или отсутствии значения."""
    login_operator(client, django_user_model, can_view_finance=False)
    case = financial_form_case

    response = client.get(case["url"])
    html = response.content.decode()

    assert response.status_code == 200
    assert case["field"] not in response.context["form"].fields
    assert f'name="{case["field"]}"' not in html
    assert "98765.43" not in html
    assert "98765,43" not in html

    payload = dict(case["payload"], can_view_finance="1")
    if submitted_value is not None:
        payload[case["field"]] = submitted_value
    original_count = case["model"].objects.count()
    response = client.post(case["url"], payload)

    assert response.status_code == 302
    saved = case["model"].objects.get(**{case["ordinary_field"]: payload[case["ordinary_field"]]})
    assert getattr(saved, case["field"]) == case["expected_value"]
    assert case["model"].objects.count() == original_count + (case["instance"] is None)
    if case["instance"] is not None:
        assert saved.pk == case["instance"].pk


@pytest.mark.django_db
@pytest.mark.parametrize("submitted_value", ["765432.10", "0.00"])
def test_financial_form_allows_both_permissions(client, django_user_model, financial_form_case, submitted_value):
    """Оба права позволяют просматривать и сохранять суммы, включая реальный ноль."""
    login_operator(client, django_user_model, can_view_finance=True)
    case = financial_form_case

    response = client.get(case["url"])

    assert response.status_code == 200
    assert case["field"] in response.context["form"].fields
    assert f'name="{case["field"]}"' in response.content.decode()

    payload = dict(case["payload"])
    payload[case["field"]] = submitted_value
    response = client.post(case["url"], payload)

    assert response.status_code == 302
    saved = case["model"].objects.get(**{case["ordinary_field"]: payload[case["ordinary_field"]]})
    assert getattr(saved, case["field"]) == Decimal(submitted_value)
    if case["instance"] is not None:
        assert saved.pk == case["instance"].pk


@pytest.mark.django_db
def test_financial_form_requires_event_management(client, django_user_model, financial_form_case):
    """Финансовое право само по себе не разрешает создание или редактирование."""
    login_operator(client, django_user_model, can_view_finance=True, can_manage_events=False)
    case = financial_form_case
    original_count = case["model"].objects.count()
    payload = dict(case["payload"], can_manage_events="1")
    payload[case["field"]] = "765432.10"

    assert client.get(case["url"]).status_code == 403
    assert client.post(case["url"], payload).status_code == 403
    assert case["model"].objects.count() == original_count
    if case["instance"] is not None:
        case["instance"].refresh_from_db()
        assert getattr(case["instance"], case["field"]) == case["expected_value"]
        assert getattr(case["instance"], case["ordinary_field"]) != payload[case["ordinary_field"]]


@pytest.mark.django_db
@pytest.mark.parametrize("final_profit", [None, Decimal("0")])
def test_outcome_form_preserves_empty_or_zero_profit(client, django_user_model, crm_objects, final_profit):
    """Редактирование обычных итогов сохраняет различие между NULL и нулевой прибылью."""
    login_operator(client, django_user_model, can_view_finance=False)
    outcome = EventOutcome.objects.create(event=crm_objects["event"], final_profit=final_profit)

    response = client.post(
        reverse("core:event_outcome_update", kwargs={"pk": outcome.pk}),
        {
            "event": outcome.event_id,
            "client_feedback": "Обновлённый отзыв",
            "project_rating": "4",
            "final_profit": "765432.10",
        },
    )
    outcome.refresh_from_db()

    assert response.status_code == 302
    assert outcome.client_feedback == "Обновлённый отзыв"
    assert outcome.final_profit == final_profit
