from datetime import date
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from django.urls import reverse

from core.models import Event, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar_user", first_name="Елена", last_name="Иванова")
    TeamMemberProfile.objects.create(user=user, can_manage_events=False)
    client.force_login(user)
    return user


def test_calendar_limits_month_and_groups_all_events(client, calendar_user, crm_objects):
    event = crm_objects["event"]
    event.date = date(2028, 2, 29)
    event.manager = calendar_user
    event.save()
    second = Event.objects.create(client=event.client, title="Второе событие", date=event.date, city="Казань")
    Event.objects.create(client=event.client, title="Другой месяц", date=date(2028, 3, 1), city="Москва")
    response = client.get(reverse("core:calendar"), {"month": "2028-02"})
    assert [e.pk for e in response.context["events"]] == [event.pk, second.pk]
    assert len(response.context["agenda_days"]) == 1
    days = [day for week in response.context["calendar_weeks"] for day in week]
    assert days[0]["date"].weekday() == 0
    assert sum(day["in_month"] for day in days) == 29
    assert sum(len(day["events"]) for day in days) == 2
    html = response.content.decode()
    assert reverse("core:event_detail", args=[event.pk]) in html
    assert "Елена Иванова" in html
    assert 'aria-current="page">Календарь</a>' in html
    assert 'href="' + reverse("core:event_create") + '"' not in html


@pytest.mark.parametrize("month", ["", "bad", "2026-13", "0001-01", "9999-12", "2026-01-01"])
def test_calendar_invalid_month_defaults_to_local_today(client, calendar_user, month):
    with patch("core.views.timezone.localdate", return_value=date(2026, 10, 28)):
        response = client.get(reverse("core:calendar"), {"month": month})
    assert response.status_code == 200
    assert response.context["calendar_month"] == date(2026, 10, 1)
    days = [day for week in response.context["calendar_weeks"] for day in week]
    assert [day["date"] for day in days if day["today"]] == [date(2026, 10, 28)]


def test_calendar_filters_and_navigation_preserve_selection(client, calendar_user, crm_objects):
    event = crm_objects["event"]
    event.date, event.manager, event.status = date(2026, 12, 5), calendar_user, Event.Status.IN_PROGRESS
    event.save()
    response = client.get(reverse("core:calendar"), {"month": "2026-12", "manager": calendar_user.pk, "status": "in_progress"})
    assert list(response.context["events"]) == [event]
    params = parse_qs(urlsplit(response.context["next_url"]).query)
    assert params == {"month": ["2027-01"], "manager": [str(calendar_user.pk)], "status": ["in_progress"]}
    assert parse_qs(urlsplit(response.context["previous_url"]).query)["month"] == ["2026-11"]
    empty = client.get(reverse("core:calendar"), {"month": "2026-12", "manager": "unassigned"})
    assert not empty.context["events"]
    assert "По выбранным фильтрам мероприятий нет" in empty.content.decode()
    ignored = client.get(reverse("core:calendar"), {"month": "2026-12", "manager": "9999999999999999999999999", "status": "invalid"})
    assert list(ignored.context["events"]) == [event]
    assert ignored.context["calendar_manager"] == ignored.context["calendar_status"] == ""


def test_calendar_empty_month_and_create_permission(client, calendar_user):
    response = client.get(reverse("core:calendar"), {"month": "2026-01"})
    assert "В этом месяце мероприятий пока нет" in response.content.decode()
    profile = calendar_user.crm_profile
    profile.can_manage_events = True
    profile.save()
    response = client.get(reverse("core:calendar"), {"month": "2026-01"})
    assert 'href="' + reverse("core:event_create") + '"' in response.content.decode()


def test_calendar_event_relations_are_loaded_without_extra_queries(client, calendar_user, crm_objects, django_assert_num_queries):
    response = client.get(reverse("core:calendar"))
    with django_assert_num_queries(0):
        for event in response.context["events"]:
            str(event)
            str(event.client)
            str(event.event_format)
            str(event.manager)
