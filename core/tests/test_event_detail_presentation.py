import re
from datetime import timedelta
from html import unescape

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import Event, TeamMemberProfile


@pytest.fixture
def detail_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="detail_manager", first_name="Елена", last_name="Смирнова")
    TeamMemberProfile.objects.create(user=user, can_view_finance=True, can_manage_events=True)
    client.force_login(user)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("status,days,warning", [
    (Event.Status.PLANNING, -1, True),
    (Event.Status.IN_PROGRESS, -1, True),
    (Event.Status.COMPLETED, -1, False),
    (Event.Status.CANCELLED, -1, False),
    (Event.Status.PLANNING, 0, False),
    (Event.Status.PLANNING, 1, False),
])
def test_past_date_warning_only_for_active_events(client, detail_user, crm_objects, status, days, warning):
    event = crm_objects["event"]
    event.date = timezone.localdate() + timedelta(days=days)
    event.status = status
    event.save()
    response = client.get(reverse("core:event_detail", args=[event.pk]))
    assert ("Дата прошла — проверьте статус мероприятия." in response.content.decode()) is warning


@pytest.mark.django_db
@pytest.mark.parametrize("has_expenses", [False, True])
def test_financial_explanation_and_permissions(client, detail_user, crm_objects, has_expenses):
    event = crm_objects["event"]
    event.planned_budget = "1100000.25"
    event.save()
    if not has_expenses:
        event.expenses.all().delete()
    url = reverse("core:event_detail", args=[event.pk])
    html = client.get(url).content.decode()
    assert "1\xa0100\xa0000,25 ₽" in html
    assert "Расчётная прибыль" in html
    assert "Расчётная маржа" in html
    assert "Оплачено по расходам" in html
    assert ("Расходы ещё не добавлены." in html) is (not has_expenses)
    detail_user.crm_profile.can_view_finance = False
    detail_user.crm_profile.save()
    html = client.get(url).content.decode()
    assert "1\xa0100\xa0000,25" not in html
    assert "Расчётная прибыль" not in html
    assert "Оплачено по расходам" not in html


@pytest.mark.django_db
def test_detail_links_and_manager_name(client, detail_user, crm_objects):
    event = crm_objects["event"]
    event.manager = detail_user
    event.save()
    task = crm_objects["task"]
    task.deadline = timezone.localdate() - timedelta(days=1)
    task.save()
    url = reverse("core:event_detail", args=[event.pk])
    html = client.get(url).content.decode()
    active_links = re.findall(r'<a class="crm-nav__link"[^>]*aria-current="page"[^>]*>([^<]+)</a>', html)
    assert active_links == ["Мероприятия"]
    assert "Елена Смирнова" in html
    overdue_url = f"{url}?tab=tasks&task_filter=overdue#event-tabs"
    assert overdue_url in unescape(html)
    filtered = client.get(overdue_url)
    assert list(filtered.context["detail_tasks"]) == [task]
    assert reverse("core:task_update", args=[task.pk]) + "?return_tab=tasks" in html
