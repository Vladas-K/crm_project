from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import PropertyMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from core.models import (
    CRMRole,
    Client,
    Event,
    EventDocument,
    EventExpense,
    EventFormat,
    EventRisk,
    EventTask,
    EventVendor,
    ExpenseCategory,
    TeamMemberProfile,
    Vendor,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def directory_viewer(client, django_user_model):
    user = django_user_model.objects.create_user(username="event_directory_viewer")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_finance=False,
        can_manage_events=False,
        can_manage_system=False,
    )
    client.force_login(user)
    return user


@pytest.fixture
def event_factory():
    customer = Client.objects.create(name="Клиент каталога")

    def create_event(**kwargs):
        values = {
            "client": customer,
            "title": "Мероприятие каталога",
            "city": "Москва",
            "date": date(2026, 10, 21),
        }
        values.update(kwargs)
        return Event.objects.create(**values)

    return create_event


@pytest.fixture
def directory_today(monkeypatch):
    today = date(2026, 10, 21)
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: today)
    return today


@pytest.mark.parametrize(
    "params, statuses",
    [
        ({}, {Event.Status.PLANNING, Event.Status.IN_PROGRESS}),
        ({"scope": "active"}, {Event.Status.PLANNING, Event.Status.IN_PROGRESS}),
        ({"scope": "all"}, set(Event.Status.values)),
        ({"scope": "archive"}, {Event.Status.COMPLETED, Event.Status.CANCELLED}),
        ({"status": Event.Status.COMPLETED}, {Event.Status.COMPLETED}),
        ({"status": Event.Status.CANCELLED}, {Event.Status.CANCELLED}),
        ({"scope": "active", "status": Event.Status.COMPLETED}, set()),
    ],
)
def test_event_directory_scopes_and_legacy_archived_status(
    client, directory_viewer, event_factory, params, statuses
):
    """Активные проекты отделены от архива; прежние ссылки на статус работают."""
    for status in Event.Status.values:
        event_factory(status=status)

    response = client.get(reverse("core:events"), params)

    assert response.status_code == 200
    assert {item.status for item in response.context["events"]} == statuses


@pytest.mark.parametrize(
    "period, offsets, expected_offsets",
    [
        ("all", [-60, -1, 0, 29, 30, 60], [-60, -1, 0, 29, 30, 60]),
        ("this_month", [-21, -20, 0, 10, 11], [-20, 0, 10]),
        ("next_30", [-1, 0, 29, 30], [0, 29]),
    ],
)
def test_event_directory_periods_include_only_calendar_boundaries(
    client, directory_viewer, directory_today, event_factory, period, offsets, expected_offsets
):
    """Календарный месяц и следующие 30 дней включают обе границы периода."""
    events = {
        offset: event_factory(date=directory_today + timedelta(days=offset))
        for offset in offsets
    }

    response = client.get(reverse("core:events"), {"period": period})

    assert list(response.context["events"]) == [events[offset] for offset in expected_offsets]


@pytest.mark.parametrize("explicit_period", [False, True])
def test_event_directory_custom_period_includes_both_boundaries(
    client, directory_viewer, event_factory, explicit_period
):
    """Новый период и прежние ссылки с датами применяют одинаковый диапазон."""
    events = {
        day: event_factory(date=date(2026, 10, day))
        for day in (9, 10, 15, 20, 21)
    }
    params = {"date_from": "2026-10-10", "date_to": "2026-10-20"}
    if explicit_period:
        params["period"] = "custom"

    response = client.get(reverse("core:events"), params)

    assert list(response.context["events"]) == [events[day] for day in (10, 15, 20)]


@pytest.mark.parametrize("field, boundary, expected_days", [
    ("date_from", "2026-10-15", [15, 20]),
    ("date_to", "2026-10-15", [10, 15]),
])
def test_event_directory_custom_period_supports_one_open_boundary(
    client, directory_viewer, event_factory, field, boundary, expected_days
):
    events = {day: event_factory(date=date(2026, 10, day)) for day in (10, 15, 20)}

    response = client.get(reverse("core:events"), {"period": "custom", field: boundary})

    assert list(response.context["events"]) == [events[day] for day in expected_days]


def test_event_directory_legacy_month_includes_last_day_and_preserves_value(
    client, directory_viewer, event_factory
):
    events = {
        value: event_factory(date=date.fromisoformat(value))
        for value in ("2026-09-30", "2026-10-01", "2026-10-31", "2026-11-01")
    }

    response = client.get(reverse("core:events"), {"month": "2026-10"})

    assert list(response.context["events"]) == [events["2026-10-01"], events["2026-10-31"]]
    assert response.context["event_month_filter"] == "2026-10"


@pytest.mark.parametrize(
    "params",
    [
        {"period": "custom", "date_from": "wrong"},
        {"period": "custom", "date_to": "2026-02-30"},
        {"period": "custom", "date_from": "2026-10-20", "date_to": "2026-10-10"},
        {"month": "0000-10"},
        {"month": "2026-13"},
        {"month": "not-a-month"},
    ],
)
def test_event_directory_invalid_dates_show_errors_and_no_results(
    client, directory_viewer, event_factory, params
):
    """Повреждённые ссылки показывают ошибку фильтра, сохраняя страницу доступной."""
    event_factory()

    response = client.get(reverse("core:events"), params)

    assert response.status_code == 200
    assert response.context["filter_form"].errors
    assert list(response.context["events"]) == []
    html = response.content.decode()
    for errors in response.context["filter_form"].errors.values():
        for error in errors:
            assert str(escape(error)) in html


@pytest.mark.parametrize(
    "sort, expected",
    [("date_asc", [1, 0, 2]), ("date_desc", [2, 0, 1]), ("created_desc", [1, 2, 0])],
)
def test_event_directory_sorting(client, directory_viewer, event_factory, sort, expected):
    events = [event_factory(date=date(2026, 10, day)) for day in (15, 10, 20)]
    for index, days_old in enumerate((3, 1, 2)):
        Event.objects.filter(pk=events[index].pk).update(
            created_at=timezone.now() - timedelta(days=days_old)
        )

    response = client.get(reverse("core:events"), {"sort": sort})

    assert list(response.context["events"]) == [events[index] for index in expected]


def test_event_directory_paginates_twenty_records_with_stable_ties(
    client, directory_viewer, event_factory
):
    first_event = event_factory()
    Event.objects.bulk_create([
        Event(client=first_event.client, title=f"Мероприятие {index}", date=first_event.date, city="Москва")
        for index in range(20)
    ])

    first = client.get(reverse("core:events"), {"sort": "date_asc"})
    second = client.get(reverse("core:events"), {"sort": "date_asc", "page": 2})

    assert first.context["paginator"].count == 21
    assert len(first.context["events"]) == 20
    assert len(second.context["events"]) == 1
    assert set(first.context["events"]).isdisjoint(second.context["events"])
    assert set(first.context["events"]) | set(second.context["events"]) == set(Event.objects.all())


def test_event_directory_keeps_filters_in_pagination_scope_tabs_and_get_form(
    client, directory_viewer, event_factory
):
    event_format = EventFormat.objects.create(name="Формат каталога")
    for index in range(21):
        event = event_factory(manager=directory_viewer, event_format=event_format)
        EventRisk.objects.create(event=event, description=f"Риск {index}")
    params = {
        "q": "мероприятие",
        "scope": "all",
        "period": "custom",
        "date_from": "2026-10-01",
        "date_to": "2026-10-31",
        "manager": str(directory_viewer.pk),
        "event_format": str(event_format.pk),
        "attention": "risks",
        "sort": "date_desc",
        "page": "2",
    }

    response = client.get(reverse("core:events"), params)
    pagination_params = parse_qs(response.context["pagination_query"])

    assert len(response.context["events"]) == 1
    assert pagination_params == {key: [value] for key, value in params.items() if key != "page"}
    for tab in response.context["scope_tabs"]:
        tab_params = parse_qs(urlsplit(tab["url"]).query)
        assert "page" not in tab_params
        for key, value in params.items():
            if key not in {"page", "scope"}:
                if key == "attention" and tab_params["scope"] == ["archive"]:
                    assert "attention" not in tab_params
                else:
                    assert tab_params[key] == [value]
    html = response.content.decode()
    assert 'name="attention"' in html
    assert 'value="risks"' in html
    assert response.context["event_attention_filter"] == "risks"


def test_event_directory_counts_and_finance_are_not_multiplied_by_related_rows(
    client, directory_viewer, directory_today, event_factory
):
    """Несколько задач, документов и одинаковых расходов не искажают сводку."""
    directory_viewer.crm_profile.can_view_finance = True
    directory_viewer.crm_profile.save(update_fields=["can_view_finance"])
    event = event_factory(planned_budget=Decimal("1000.00"))
    for status, offset in (
        (EventTask.Status.TODO, -1),
        (EventTask.Status.IN_PROGRESS, 0),
        (EventTask.Status.TODO, 1),
        (EventTask.Status.DONE, -2),
    ):
        EventTask.objects.create(event=event, title="Задача", status=status,
                                 deadline=directory_today + timedelta(days=offset))
    vendor = Vendor.objects.create(name="Подрядчик каталога")
    for role in ("Звук", "Свет"):
        EventVendor.objects.create(event=event, vendor=vendor, role=role)
    for status in (EventDocument.Status.SIGNED, EventDocument.Status.SIGNED, EventDocument.Status.DRAFT):
        EventDocument.objects.create(event=event, document_type=EventDocument.Type.CONTRACT, status=status)
    category = ExpenseCategory.objects.create(name="Расходы каталога")
    for amount in ("100.00", "100.00", "50.00"):
        EventExpense.objects.create(event=event, category=category, amount=Decimal(amount))
    archived_event = event_factory(status=Event.Status.COMPLETED)
    EventExpense.objects.create(event=archived_event, category=category, amount=Decimal("999.00"))

    response = client.get(reverse("core:events"))
    item = response.context["events"][0]

    assert item.open_tasks_count == 3
    assert item.overdue_tasks_count == 1
    assert item.vendors_count == 2
    assert item.documents_count == 3
    assert item.signed_documents_count == 2
    assert item.directory_total_expenses == Decimal("250.00")
    assert item.directory_margin == Decimal("75.00")


def test_event_directory_date_attention_excludes_archived_projects(
    client, directory_viewer, directory_today, event_factory
):
    active = event_factory(date=directory_today - timedelta(days=1))
    finished = event_factory(date=directory_today - timedelta(days=2), status=Event.Status.COMPLETED)

    response = client.get(reverse("core:events"), {"scope": "all"})
    events = {item.pk: item for item in response.context["events"]}

    assert events[active.pk].directory_days_until == -1
    assert events[active.pk].directory_date_overdue is True
    assert events[finished.pk].directory_date_overdue is False


def test_event_directory_does_not_read_or_render_finance_without_permission(
    client, directory_viewer, event_factory
):
    event = event_factory(planned_budget=Decimal("7654321.12"))
    category = ExpenseCategory.objects.create(name="Скрытые расходы")
    EventExpense.objects.create(event=event, category=category, amount=Decimal("123456.78"))
    with (
        patch.object(Event, "margin", new_callable=PropertyMock, side_effect=AssertionError("finance read")),
        patch.object(Event, "total_expenses", new_callable=PropertyMock, side_effect=AssertionError("finance read")),
        CaptureQueriesContext(connection) as queries,
    ):
        response = client.get(reverse("core:events"))
    item = response.context["events"][0]
    html = response.content.decode()

    assert response.status_code == 200
    assert not hasattr(item, "directory_margin")
    assert not hasattr(item, "directory_budget_display")
    assert not any('"core_eventexpense"' in query["sql"] for query in queries)
    assert "Бюджет" not in html
    assert "Плановая маржа" not in html
    assert "7654321" not in html
    assert "7\xa0654\xa0321" not in html


@pytest.mark.parametrize("finance", [False, True])
@pytest.mark.parametrize("search", ["", "мероприятие"])
def test_event_directory_query_count_does_not_grow_per_card(
    client, directory_viewer, event_factory, finance, search
):
    directory_viewer.crm_profile.can_view_finance = finance
    directory_viewer.crm_profile.save(update_fields=["can_view_finance"])
    event_factory(planned_budget=Decimal("1000.00"), manager=directory_viewer)
    params = {"q": search}
    client.get(reverse("core:events"), params)
    with CaptureQueriesContext(connection) as one_card:
        client.get(reverse("core:events"), params)
    for _ in range(5):
        event_factory(planned_budget=Decimal("1000.00"), manager=directory_viewer)
    with CaptureQueriesContext(connection) as six_cards:
        response = client.get(reverse("core:events"), params)

    assert len(response.context["events"]) == 6
    assert len(six_cards) <= len(one_card) + 1


def test_event_directory_escapes_user_text_in_cards(client, directory_viewer, event_factory):
    title = '<img src=x onerror="alert(1)">'
    city = '<script>alert("city")</script>'
    event = event_factory(title=title, city=city)
    event.client.name = '<svg onload="alert(2)">'
    event.client.save(update_fields=["name"])

    response = client.get(reverse("core:events"))
    html = response.content.decode()

    for value in (title, city, event.client.name):
        assert value not in html
        assert str(escape(value)) in html


@pytest.mark.parametrize("status", [Event.Status.COMPLETED, Event.Status.CANCELLED])
def test_event_autocomplete_links_archived_suggestions_directly_to_detail(
    client, directory_viewer, event_factory, status
):
    """Подсказка открывает архивный проект независимо от активной вкладки каталога."""
    event = event_factory(title="https://example.com/архив?q=<script>", status=status)

    assert list(client.get(reverse("core:events")).context["events"]) == []
    response = client.get(reverse("core:event_autocomplete"), {"q": "АРХИВ"})
    suggestion = response.json()["results"][0]

    assert suggestion["id"] == event.pk
    assert suggestion["title"] == event.title
    assert suggestion["url"] == reverse("core:event_detail", args=[event.pk])
    detail_response = client.get(suggestion["url"])
    assert detail_response.status_code == 200
    assert detail_response.context["event"] == event


@pytest.mark.parametrize(
    "scope, statuses",
    [
        ("active", [Event.Status.PLANNING, Event.Status.IN_PROGRESS]),
        ("archive", [Event.Status.COMPLETED, Event.Status.CANCELLED]),
        ("all", Event.Status.values),
    ],
)
def test_event_directory_status_options_match_selected_scope(
    client, directory_viewer, scope, statuses
):
    response = client.get(reverse("core:events"), {"scope": scope})

    assert [value for value, label in response.context["event_statuses"]] == statuses


@pytest.mark.parametrize("chart_name", ["monthly_chart", "team_chart", "finance_monthly_chart"])
def test_analytics_event_chart_links_include_matching_archived_projects(
    client, directory_viewer, event_factory, chart_name
):
    """Числа в аналитике и каталог по ссылке учитывают один и тот же архив."""
    profile = directory_viewer.crm_profile
    profile.can_view_analytics = True
    profile.can_view_finance = chart_name == "finance_monthly_chart"
    profile.save(update_fields=["can_view_analytics", "can_view_finance"])
    archived = event_factory(status=Event.Status.COMPLETED, manager=directory_viewer)
    event_factory(date=date(2026, 11, 1))

    analytics = client.get(reverse("core:analytics"))
    chart_item = analytics.context[chart_name][0]
    params = parse_qs(urlsplit(chart_item["url"]).query)
    directory = client.get(chart_item["url"])

    assert params["scope"] == ["all"]
    assert directory.status_code == 200
    assert list(directory.context["events"]) == [archived]
    if chart_name != "finance_monthly_chart":
        assert chart_item["total"] == directory.context["paginator"].count


def test_dashboard_event_count_links_to_directory_including_archive(
    client, directory_viewer, event_factory
):
    active = event_factory()
    archived = event_factory(status=Event.Status.COMPLETED)
    target_url = f"{reverse('core:events')}?scope=all"

    dashboard = client.get(reverse("core:dashboard"))
    directory = client.get(target_url)

    assert f'href="{target_url}"' in dashboard.content.decode()
    assert set(directory.context["events"]) == {active, archived}
