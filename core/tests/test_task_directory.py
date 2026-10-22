import re
from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from core.forms import EventTaskForm
from core.models import Event, EventTask, TeamMemberProfile
from core.views import safe_task_return_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="task_operator", first_name="Анна", last_name="Иванова")
    TeamMemberProfile.objects.create(user=user, can_manage_events=True, can_manage_system=True)
    client.force_login(user)
    return user


def task_data(event, **changes):
    data = {"event": event.pk, "title": "Новая задача", "description": "",
            "deadline": timezone.localdate().isoformat(), "deadline_offset_days": "0", "status": "todo"}
    data.update(changes)
    return data


def test_combined_search_event_mine_and_summary(client, operator, crm_objects, django_user_model):
    event = crm_objects["event"]
    task = crm_objects["task"]
    task.title = "Согласовать ПЛОЩАДКУ"
    task.responsible = operator
    task.deadline = timezone.localdate() - timedelta(days=1)
    task.save()
    done = EventTask.objects.create(event=event, title="Площадку оплатить", responsible=operator, status="done")
    EventTask.objects.create(event=event, title="Площадку проверить")
    other = Event.objects.create(client=event.client, title="Другой проект", date=event.date)
    EventTask.objects.create(event=other, title="Площадку утвердить", responsible=operator)
    response = client.get(reverse("core:tasks"), {"q": "площадку", "event": event.pk, "mine": "1", "filter": "overdue"})
    assert list(response.context["tasks"]) == [task]
    assert response.context["task_stats"] == {"total": 2, "open": 1, "overdue": 1, "done": 1}
    tabs = response.context["task_tabs"]
    done_tab = next(tab for tab in tabs if "filter=done" in tab["url"])
    assert list(client.get(done_tab["url"]).context["tasks"]) == [done]
    assert "mine=1" in done_tab["url"] and "page=" not in done_tab["url"]


@pytest.mark.parametrize("state,expected", [("all", 4), ("open", 3), ("overdue", 1), ("done", 1)])
def test_status_and_deadline_boundaries(client, operator, crm_objects, state, expected):
    event = crm_objects["event"]
    crm_objects["task"].delete()
    today = timezone.localdate()
    for status, offset in [("todo", -1), ("in_progress", 0), ("todo", 1), ("done", -2)]:
        EventTask.objects.create(event=event, title=f"{status}:{offset}", status=status, deadline=today + timedelta(days=offset))
    response = client.get(reverse("core:tasks"), {"filter": state})
    assert len(response.context["tasks"]) == expected


def test_priority_and_explicit_sort(client, operator, crm_objects):
    event = crm_objects["event"]
    task = crm_objects["task"]
    task.status = "done"
    task.deadline = timezone.localdate() - timedelta(days=20)
    task.save()
    late = EventTask.objects.create(event=event, title="Позже", deadline=timezone.localdate() + timedelta(days=2))
    urgent = EventTask.objects.create(event=event, title="Срочно", deadline=timezone.localdate() - timedelta(days=2))
    no_date = EventTask.objects.create(event=event, title="Без срока")
    EventTask.objects.filter(pk=no_date.pk).update(deadline=None)
    url = reverse("core:tasks")
    assert list(client.get(url).context["tasks"]) == [urgent, late, no_date, task]
    assert list(client.get(url, {"sort": "deadline"}).context["tasks"]) == [task, urgent, late, no_date]
    assert list(client.get(url, {"sort": "deadline_desc"}).context["tasks"]) == [late, urgent, task, no_date]
    assert list(client.get(url, {"sort": "newest"}).context["tasks"]) == [no_date, urgent, late, task]


def test_pages_and_out_of_range_return(client, operator, crm_objects):
    event = crm_objects["event"]
    for index in range(22):
        EventTask.objects.create(event=event, title=f"Задача {index}", responsible=operator)
    url = reverse("core:tasks")
    response = client.get(url, {"mine": "1", "sort": "newest", "page": "2"})
    assert response.context["paginator"].count == 22
    assert len(response.context["tasks"]) == 2
    assert "page=2" in response.context["task_return_url"]
    assert "mine=1" in response.context["pagination_query"]
    assert "page=" not in response.context["pagination_query"]
    assert client.get(url, {"mine": "1", "page": "999"}).context["page_obj"].number == 2
    assert client.get(url, {"page": "oops", "filter": "oops", "event": "9" * 100, "sort": "oops"}).status_code == 200


@pytest.mark.parametrize("target", ["https://evil.example/tasks/", "//evil.example/tasks/", "/clients/", "http://[", "/tasks/../clients/", r"/tasks/\evil"])
def test_return_rejects_external_or_unrelated_target(target):
    assert safe_task_return_url(target) is None


def test_return_strips_unknown_parameters():
    assert safe_task_return_url("/tasks/?mine=1&sort=newest&page=2&next=https://evil.example") == "/tasks/?mine=1&sort=newest&page=2"


@pytest.mark.parametrize("operation", ["create", "update", "delete", "status"])
def test_list_actions_preserve_origin(client, operator, crm_objects, operation):
    event = crm_objects["event"]
    task = crm_objects["task"]
    origin = "/tasks/?q=бриф&filter=open&event=%s&mine=1&sort=newest&page=2" % event.pk
    if operation == "create":
        url = reverse("core:task_create")
    else:
        url = reverse("core:" + {"update": "task_update", "delete": "task_delete", "status": "task_status_update"}[operation], args=[task.pk])
    if operation != "status":
        get = client.get(url, {"return_to": origin})
        assert get.status_code == 200
        cancel = get.context["cancel_url"]
        if operation == "update":
            assert urlsplit(cancel).path == reverse("core:task_detail", args=[task.pk])
            cancel = parse_qs(urlsplit(cancel).query)["return_to"][0]
        assert parse_qs(urlsplit(cancel).query)["page"] == ["2"]
        assert 'name="return_to"' in get.content.decode()
    payload = task_data(event, return_to=origin) if operation in {"create", "update"} else {"return_to": origin, "status": "done"}
    response = client.post(url, payload)
    assert response.status_code == 302
    if operation in {"create", "update"}:
        saved_task = EventTask.objects.get(title="Новая задача")
        assert urlsplit(response.url).path == reverse("core:task_detail", args=[saved_task.pk])
        list_url = parse_qs(urlsplit(response.url).query)["return_to"][0]
    else:
        assert urlsplit(response.url).path == "/tasks/"
        list_url = response.url
    assert parse_qs(urlsplit(list_url).query) == parse_qs(urlsplit(origin).query)
    if operation == "status":
        task.refresh_from_db()
        assert task.status == "done"


def test_invalid_form_keeps_list_context(client, operator, crm_objects):
    response = client.post(reverse("core:task_create"), task_data(crm_objects["event"], title="", return_to="/tasks/?mine=1&page=2"))
    assert response.status_code == 200
    assert response.context["cancel_url"] == "/tasks/?mine=1&page=2"
    assert response.context["return_tab"] == ""


def test_detail_passes_origin_to_edit_and_delete(client, operator, crm_objects):
    response = client.get(reverse("core:task_detail", args=[crm_objects["task"].pk]), {"return_to": "/tasks/?filter=overdue"})
    assert response.context["task_return_url"] == "/tasks/?filter=overdue"
    assert "return_to=" in response.context["task_return_query"]
    html = response.content.decode()
    list_link = re.search(r'<a href="([^"]+)"[^>]*>← К списку задач</a>', html)
    assert unescape(list_link.group(1)) == "/tasks/?filter=overdue"
    assert reverse("core:event_update", args=[crm_objects["event"].pk]) not in html
    assert reverse("core:event_detail", args=[crm_objects["event"].pk]) in html


@pytest.mark.parametrize("inactive,profile", [(True, True), (False, False)])
def test_responsible_choices_preserve_only_current_exception(django_user_model, operator, crm_objects, inactive, profile):
    current = django_user_model.objects.create_user(username="current", is_active=not inactive)
    outsider = django_user_model.objects.create_user(username="outsider", is_active=not inactive)
    if profile:
        TeamMemberProfile.objects.create(user=current)
        TeamMemberProfile.objects.create(user=outsider)
    event = crm_objects["event"]
    create_form = EventTaskForm(task_data(event, responsible=outsider.pk))
    assert not create_form.is_valid() and "responsible" in create_form.errors
    task = crm_objects["task"]
    task.responsible = current
    task.save()
    retained = EventTaskForm(task_data(event, responsible=current.pk), instance=task)
    assert retained.is_valid(), retained.errors
    replacement = EventTaskForm(task_data(event, responsible=operator.pk), instance=task)
    assert replacement.is_valid(), replacement.errors
    cleared = EventTaskForm(task_data(event, responsible=""), instance=task)
    assert cleared.is_valid(), cleared.errors
    assert "Анна Иванова" in str(EventTaskForm()["responsible"])


def test_list_post_cannot_redirect_to_external_site(client, operator, crm_objects):
    task = crm_objects["task"]
    for target in ("https://evil.example/", "//evil.example/tasks/", "/clients/"):
        response = client.post(reverse("core:task_status_update", args=[task.pk]), {"status": "in_progress", "return_to": target})
        assert response.url == reverse("core:event_detail", args=[task.event_id]) + "?tab=tasks#event-tabs"


def test_status_permission_is_checked_before_change(client, operator, crm_objects):
    operator.crm_profile.can_manage_events = False
    operator.crm_profile.save()
    task = crm_objects["task"]
    response = client.post(reverse("core:task_status_update", args=[task.pk]), {"status": "done", "return_to": "/tasks/"})
    assert response.status_code == 403
    task.refresh_from_db()
    assert task.status == "todo"


def test_nested_event_return_has_priority_over_list_url(client, operator, crm_objects):
    event = crm_objects["event"]
    response = client.post(reverse("core:event_task_create", kwargs={"event_pk": event.pk}), task_data(event, return_to="/tasks/"))
    task = EventTask.objects.get(title="Новая задача")
    assert response.url == reverse("core:task_detail", args=[task.pk]) + "?return_tab=tasks"


def test_task_create_rejects_inactive_responsible_post(client, operator, crm_objects, django_user_model):
    inactive = django_user_model.objects.create_user(username="inactive_injected", is_active=False)
    TeamMemberProfile.objects.create(user=inactive)
    response = client.post(reverse("core:task_create"), task_data(crm_objects["event"], responsible=inactive.pk))
    assert response.status_code == 200
    assert "responsible" in response.context["form"].errors
    assert not EventTask.objects.filter(title="Новая задача").exists()


@pytest.mark.parametrize("status,target", [("todo", "in_progress"), ("in_progress", "done")])
@pytest.mark.parametrize("origin", [None, "/tasks/?filter=open&mine=1&page=2"])
def test_detail_quick_action_stays_on_task(client, operator, crm_objects, status, target, origin):
    task = crm_objects["task"]
    task.status = status
    task.save()
    response = client.get(reverse("core:task_detail", args=[task.pk]), {"return_to": origin} if origin else {})
    html = response.content.decode()
    assert 'name="return_task" value="1"' in html
    assert ('>В работу</button>' if status == "todo" else '>Завершить</button>') in html
    payload = {"return_task": "1", "status": target}
    if origin:
        payload["return_to"] = origin
    response = client.post(reverse("core:task_status_update", args=[task.pk]), payload)
    assert urlsplit(response.url).path == reverse("core:task_detail", args=[task.pk])
    if origin:
        assert parse_qs(urlsplit(response.url).query)["return_to"] == [origin]
    task.refresh_from_db()
    assert task.status == target


@pytest.mark.parametrize("can_manage,status", [(False, "todo"), (False, "in_progress"), (True, "done")])
def test_detail_quick_action_visibility(client, operator, crm_objects, can_manage, status):
    operator.crm_profile.can_manage_events = can_manage
    operator.crm_profile.save()
    task = crm_objects["task"]
    task.status = status
    task.save()
    html = client.get(reverse("core:task_detail", args=[task.pk])).content.decode()
    assert reverse("core:task_status_update", args=[task.pk]) not in html
    if not can_manage:
        response = client.post(reverse("core:task_status_update", args=[task.pk]), {"return_task": "1", "status": "done"})
        assert response.status_code == 403
        task.refresh_from_db()
        assert task.status == status


def test_detail_return_discards_external_destination(client, operator, crm_objects):
    task = crm_objects["task"]
    response = client.post(reverse("core:task_status_update", args=[task.pk]), {"return_task": "1", "status": "in_progress", "return_to": "https://evil.example/"})
    assert response.url == reverse("core:task_detail", args=[task.pk])


@pytest.mark.parametrize("status,offset,expected", [("todo", -1, "overdue"), ("todo", 0, "today"), ("done", -1, "none"), ("todo", None, "none")])
def test_detail_deadline_states(client, operator, crm_objects, status, offset, expected):
    task = crm_objects["task"]
    EventTask.objects.filter(pk=task.pk).update(status=status, deadline=timezone.localdate() + timedelta(days=offset) if offset is not None else None)
    response = client.get(reverse("core:task_detail", args=[task.pk]))
    assert response.context["is_overdue"] is (expected == "overdue")
    assert response.context["is_due_today"] is (expected == "today")
    html = response.content.decode()
    assert "Смещение дедлайна" not in html
    assert "metric-card" not in html
    if offset is None:
        assert "Не задан" in html
