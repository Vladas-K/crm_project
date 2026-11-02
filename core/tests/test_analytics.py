from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import PropertyMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from core.models import Client, CRMRole, Event, EventExpense, ExpenseCategory, Lead, PipelineStage, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def report_today(monkeypatch):
    today = date(2026, 11, 2)
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: today)
    return today


@pytest.fixture
def analyst(client, django_user_model):
    user = django_user_model.objects.create_user(username="report_analyst")
    TeamMemberProfile.objects.create(
        user=user, role=CRMRole.PROJECT_MANAGER, can_view_analytics=True, can_view_finance=True,
    )
    client.force_login(user)
    return user


@pytest.fixture
def report_lead():
    def create(created_on=date(2026, 7, 15), **kwargs):
        lead = Lead.objects.create(name="Лид отчёта", **kwargs)
        Lead.objects.filter(pk=lead.pk).update(
            created_at=timezone.make_aware(datetime.combine(created_on, time(12))),
        )
        return lead
    return create


@pytest.fixture
def report_event():
    customer = Client.objects.create(name="Клиент мероприятий")

    def create(**kwargs):
        values = {
            "client": customer, "title": "Мероприятие отчёта", "city": "Москва",
            "date": date(2026, 7, 15), "planned_budget": Decimal("100000.50"),
        }
        return Event.objects.create(**(values | kwargs))
    return create


def row_query(row):
    return parse_qs(urlsplit(row["url"]).query)


def test_conversion_uses_lead_to_client_link_and_ignores_manual_customers(client, analyst, report_lead):
    converted = report_lead()
    report_lead()
    report_lead()
    Client.objects.create(name="Из лида", lead=converted)
    for index in range(5):
        Client.objects.create(name=f"Клиент без лида {index}")

    response = client.get(reverse("core:analytics"))

    assert response.context["total_leads"] == 3
    assert response.context["converted_leads"] == 1
    assert response.context["metrics"]["conversion"] == 33.3


def test_conversion_period_uses_lead_cohort_instead_of_client_creation_date(
    client, analyst, report_today, report_lead,
):
    recent_lead = report_lead(created_on=date(2026, 7, 1))
    report_lead(created_on=report_today)
    old_lead = report_lead(created_on=date(2025, 1, 1))
    old_customer = Client.objects.create(name="Связанный клиент", lead=recent_lead)
    Client.objects.filter(pk=old_customer.pk).update(
        created_at=timezone.make_aware(datetime(2025, 1, 1, 12)),
    )
    Client.objects.create(name="Сегодня из старого лида", lead=old_lead)
    Client.objects.create(name="Сегодня вручную")

    response = client.get(reverse("core:analytics"), {"period": "6m"})

    assert response.context["total_leads"] == 2
    assert response.context["converted_leads"] == 1
    assert response.context["metrics"]["conversion"] == 50.0


def test_no_leads_has_no_invented_conversion(client, analyst, report_today):
    Client.objects.create(name="Только ручной клиент")

    response = client.get(reverse("core:analytics"))

    assert response.context["metrics"]["conversion"] is None
    assert response.context["total_leads"] == response.context["converted_leads"] == 0
    assert response.context["pipeline_chart"] == response.context["source_chart"] == []


@pytest.mark.parametrize("period,months,start", [
    ("6m", 6, date(2026, 6, 1)), ("12m", 12, date(2025, 12, 1)),
])
def test_period_contains_zero_months_and_exact_calendar_bounds(
    client, analyst, report_today, period, months, start,
):
    response = client.get(reverse("core:analytics"), {"period": period})

    assert response.context["analytics_period_start"] == start
    assert response.context["analytics_period_end"] == report_today
    assert len(response.context["monthly_chart"]) == months
    assert len(response.context["finance_monthly_chart"]) == months
    assert all(item["total"] == 0 for item in response.context["monthly_chart"])
    assert all(item["budget"] == item["expenses"] == 0 for item in response.context["finance_monthly_chart"])
    assert response.context["metrics"]["average_check"] is None
    assert response.context["metrics"]["profit"] is None
    assert row_query(response.context["monthly_chart"][-1])["date_to"] == [report_today.isoformat()]


def test_report_excludes_cancelled_and_preserves_decimal_financial_amounts(
    client, analyst, report_today, report_event,
):
    completed = report_event(status=Event.Status.COMPLETED, planned_budget=Decimal("100.05"))
    active = report_event(planned_budget=Decimal("200.15"))
    cancelled = report_event(status=Event.Status.CANCELLED, planned_budget=Decimal("9000000"))
    category = ExpenseCategory.objects.create(name="Смета")
    for event, amount in [(completed, "20.01"), (active, "30.02"), (cancelled, "999.99")]:
        EventExpense.objects.create(event=event, category=category, amount=Decimal(amount))

    response = client.get(reverse("core:analytics"), {"period": "6m"})

    assert response.context["total_events"] == 2
    assert response.context["metrics"]["average_check"] == Decimal("150.10")
    assert response.context["metrics"]["profit"] == Decimal("250.17")
    assert sum(row["total"] for row in response.context["monthly_chart"]) == 2
    assert sum(row["budget"] for row in response.context["finance_monthly_chart"]) == Decimal("300.20")
    assert sum(row["expenses"] for row in response.context["finance_monthly_chart"]) == Decimal("50.03")


def test_finance_data_is_absent_and_properties_not_evaluated_without_permission(
    client, analyst, report_today, report_event,
):
    report_event(planned_budget=Decimal("919191.91"))
    TeamMemberProfile.objects.filter(user=analyst).update(can_view_finance=False)

    with patch.object(Event, "profit", new_callable=PropertyMock, side_effect=AssertionError("finance accessed")), \
            patch.object(Event, "total_expenses", new_callable=PropertyMock, side_effect=AssertionError("finance accessed")):
        response = client.get(reverse("core:analytics"))

    assert response.context["metrics"]["average_check"] is None
    assert response.context["metrics"]["profit"] is None
    assert response.context["finance_monthly_chart"] == []
    html = response.content.decode()
    assert "919191" not in html
    assert "Средний плановый бюджет" not in html and "Расчётная прибыль" not in html


def test_team_is_current_active_work_independent_of_report_dates(
    client, analyst, report_today, report_event, django_user_model,
):
    manager = django_user_model.objects.create_user(username="pm", first_name="Анна", last_name="Орлова")
    future = report_event(manager=manager, date=date(2027, 7, 1))
    overdue = report_event(manager=manager, date=date(2020, 1, 1), status=Event.Status.IN_PROGRESS)
    report_event(manager=manager, status=Event.Status.COMPLETED)
    report_event(manager=manager, status=Event.Status.CANCELLED)
    report_event(date=date(2028, 1, 1))

    for period in ["all", "6m", "12m"]:
        response = client.get(reverse("core:analytics"), {"period": period})
        rows = response.context["team_chart"]
        manager_row = next(row for row in rows if row["label"] == "Анна Орлова")
        assert manager_row["total"] == 2
        assert row_query(manager_row) == {"scope": ["active"], "manager": [str(manager.pk)]}
        directory = client.get(manager_row["url"])
        assert set(directory.context["events"]) == {future, overdue}
        unassigned = next(row for row in rows if row_query(row).get("manager") == ["unassigned"])
        assert unassigned["total"] == 1
        assert client.get(unassigned["url"]).context["paginator"].count == 1


def test_team_does_not_drop_ninth_manager_or_account_without_profile(
    client, analyst, report_event, django_user_model,
):
    for index in range(10):
        manager = django_user_model.objects.create_user(username=f"manager_{index}")
        report_event(manager=manager)

    rows = client.get(reverse("core:analytics")).context["team_chart"]

    assert len(rows) == 10
    assert sum(row["total"] for row in rows) == 10
    assert {row["label"] for row in rows} == {f"manager_{index}" for index in range(10)}


@pytest.mark.parametrize("unassigned", [False, True])
def test_stage_drilldown_matches_period_count_in_pipeline_and_full_lead_list(
    client, analyst, report_today, report_lead, unassigned,
):
    stage = None if unassigned else PipelineStage.objects.create(name="В работе", code="work", order=1)
    included = report_lead(created_on=date(2026, 6, 1), stage=stage)
    report_lead(created_on=date(2026, 5, 31), stage=stage)
    report_lead(created_on=date(2026, 11, 3), stage=stage)

    response = client.get(reverse("core:analytics"), {"period": "6m"})
    row = next(item for item in response.context["pipeline_chart"] if item["total"])
    params = row_query(row)
    assert params["stage"] == ["unassigned" if unassigned else str(stage.pk)]
    assert params["date_from"] == ["2026-06-01"]
    assert params["date_to"] == ["2026-11-02"]
    board = client.get(row["url"])
    assert board.context["filtered_count"] == row["total"] == 1
    assert list(client.get(board.context["filtered_leads_url"]).context["leads"]) == [included]
    group = next(item for item in board.context["pipeline_groups"] if item["total"])
    listing = client.get(group["all_url"])
    assert list(listing.context["leads"]) == [included]


@pytest.mark.parametrize("source", ["", "Сайт & реклама"])
def test_source_drilldown_matches_exact_source_and_period(client, analyst, report_today, report_lead, source):
    included = report_lead(source=source)
    report_lead(created_on=date(2025, 1, 1), source=source)
    report_lead(source="Другой канал")

    response = client.get(reverse("core:analytics"), {"period": "6m"})
    row = next(item for item in response.context["source_chart"] if item["label"] == (source or "Не указан"))
    params = row_query(row)
    assert params["date_from"] == ["2026-06-01"]
    assert params["date_to"] == ["2026-11-02"]
    assert params.get("source_empty") == (["1"] if not source else None)
    assert params.get("source") == ([source] if source else None)
    listing = client.get(row["url"])
    assert list(listing.context["leads"]) == [included]
    assert len(listing.context["leads"]) == row["total"]


def test_current_month_drilldown_excludes_future_days_and_cancelled_events(
    client, analyst, report_today, report_event,
):
    included = report_event(date=report_today, status=Event.Status.COMPLETED)
    report_event(date=report_today + timedelta(days=1))
    report_event(date=report_today, status=Event.Status.CANCELLED)

    response = client.get(reverse("core:analytics"), {"period": "6m"})

    for chart_name in ["monthly_chart", "finance_monthly_chart"]:
        row = response.context[chart_name][-1]
        params = row_query(row)
        assert params["month"] == ["2026-11"]
        assert params["date_from"] == ["2026-11-01"]
        assert params["date_to"] == ["2026-11-02"]
        assert params["status"] == ["not_cancelled"]
        directory = client.get(row["url"])
        assert list(directory.context["events"]) == [included]
        if chart_name == "monthly_chart":
            assert row["total"] == directory.context["paginator"].count == 1


@pytest.mark.parametrize("route", ["leads", "pipeline"])
@pytest.mark.parametrize("params,error_field", [
    ({"date_from": "2026-13-01", "date_to": "2026-11-02"}, "date_from"),
    ({"date_from": "2026-06-01", "date_to": "not-a-date"}, "date_to"),
    ({"date_from": "2026-11-02", "date_to": "2026-06-01"}, "date_to"),
])
def test_invalid_drilldown_dates_fail_closed_with_visible_errors_and_bound_values(
    client, analyst, report_lead, route, params, error_field,
):
    report_lead()

    response = client.get(reverse(f"core:{route}"), params)

    assert response.status_code == 200
    assert error_field in response.context["lead_date_form"].errors
    assert 'role="alert"' in response.content.decode()
    assert "Проверьте период" in response.content.decode()
    for field, value in params.items():
        assert response.context["lead_date_form"][field].value() == value
    if route == "pipeline":
        assert response.context["filtered_count"] == 0
        assert all(group["total"] == 0 for group in response.context["pipeline_groups"])
    else:
        assert not list(response.context["leads"])


@pytest.mark.parametrize("route", ["leads", "pipeline"])
def test_valid_drilldown_dates_are_preserved_in_get_form(client, analyst, report_lead, route):
    report_lead()
    params = {"date_from": "2026-06-01", "date_to": "2026-11-02"}

    response = client.get(reverse(f"core:{route}"), params)

    assert not response.context["lead_date_form"].errors
    html = response.content.decode()
    for field, value in params.items():
        assert f'name="{field}"' in html
        assert f'value="{value}"' in html


def test_charts_use_real_links_without_canvas_or_external_chart_dependency(
    client, analyst, report_today, report_lead, report_event,
):
    report_lead()
    report_event()
    response = client.get(reverse("core:analytics"))
    html = response.content.decode()

    assert 'id="pipeline-chart"' in html
    assert 'id="monthly-chart"' in html
    assert "<canvas" not in html
    assert "chart.js" not in html.lower()
    assert "Средний плановый бюджет" in html
    assert "Расчётная прибыль" in html
    for chart_name in ["pipeline_chart", "source_chart", "team_chart", "monthly_chart", "finance_monthly_chart"]:
        for row in response.context[chart_name]:
            # Все значения доступны обычными ссылками, без canvas hit testing.
            assert f'href="{escape(row["url"])}"' in html
