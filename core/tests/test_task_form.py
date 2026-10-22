from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils import timezone

from core.forms import EventTaskForm
from core.models import EventTask, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def form_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="task_form_operator")
    TeamMemberProfile.objects.create(user=user, can_manage_events=True)
    client.force_login(user)
    return user


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


def payload(event_obj, **changes):
    data = {"title": "Согласовать концепцию", "event": event_obj.pk, "responsible": "", "description": "Подробности задачи",
            "deadline": "", "deadline_offset_days": "0", "status": "todo"}
    data.update(changes)
    return data


@pytest.mark.parametrize("editing", [False, True])
def test_structured_task_form_and_return(client, form_operator, crm_objects, editing):
    task = crm_objects["task"]
    url = reverse("core:task_update", args=[task.pk]) if editing else reverse("core:task_create")
    response = client.get(url, {"return_to": "/tasks/?mine=1&filter=open"})
    assert response.status_code == 200
    assert "core/task_form.html" in [template.name for template in response.templates]
    html = response.content.decode()
    assert ("Сохранить изменения" if editing else "Создать задачу") in html
    assert "Django admin" not in html
    assert html.index('id="id_title"') < html.index('id="id_event"') < html.index('id="id_description"') < html.index('id="id_deadline"')
    assert 'novalidate' in html
    expected_cancel = "/tasks/?filter=open&mine=1"
    if editing:
        expected_cancel = reverse("core:task_detail", args=[task.pk]) + "?" + urlencode({"return_to": expected_cancel})
    assert response.context["cancel_url"] == expected_cancel
    assert ("← К задаче" if editing else "← К списку задач") in html
    assert 'name="return_to"' in html
    assert set(response.context["form"].fields) == {"title", "event", "responsible", "description", "deadline", "deadline_offset_days", "status"}


@pytest.mark.parametrize("offset,opened", [(0, False), (-7, True), (2, True)])
def test_saved_calculation_settings_visibility(client, form_operator, crm_objects, offset, opened):
    task = crm_objects["task"]
    task.deadline_offset_days = offset
    task.save()
    response = client.get(reverse("core:task_update", args=[task.pk]))
    details = next(attrs for tag, attrs in Elements(response.content.decode()).items if tag == "details" and attrs.get("class") == "task-form-deadline-settings")
    assert ("open" in details) is opened


def test_invalid_calculation_expands_settings_and_preserves_input(client, form_operator, crm_objects):
    response = client.post(reverse("core:task_create"), payload(crm_objects["event"], deadline_offset_days="не число", return_to="/tasks/?mine=1"))
    assert response.status_code == 200
    form = response.context["form"]
    assert "deadline_offset_days" in form.errors
    assert form["title"].value() == "Согласовать концепцию"
    html = response.content.decode()
    elements = Elements(html).items
    details = next(attrs for tag, attrs in elements if tag == "details" and attrs.get("class") == "task-form-deadline-settings")
    assert "open" in details
    widget = next(attrs for tag, attrs in elements if attrs.get("id") == "id_deadline_offset_days")
    assert widget["aria-invalid"] == "true"
    assert "id_deadline_offset_days_helptext" in widget["aria-describedby"]
    assert "id_deadline_offset_days_error" in widget["aria-describedby"]
    assert 'href="#id_deadline_offset_days"' in html
    assert response.context["cancel_url"] == "/tasks/?mine=1"
    assert not EventTask.objects.filter(title="Согласовать концепцию").exists()


def test_title_error_is_linked_to_field(client, form_operator, crm_objects):
    response = client.post(reverse("core:task_create"), payload(crm_objects["event"], title=""))
    elements = Elements(response.content.decode()).items
    assert any(attrs.get("role") == "alert" for _, attrs in elements)
    widget = next(attrs for _, attrs in elements if attrs.get("id") == "id_title")
    assert widget["aria-invalid"] == "true"
    assert "id_title_error" in widget["aria-describedby"]
    assert 'href="#id_title"' in response.content.decode()


def test_blank_date_calculates_from_event_without_javascript(client, form_operator, crm_objects):
    event = crm_objects["event"]
    response = client.post(reverse("core:task_create"), payload(event, deadline_offset_days="-7"))
    assert response.status_code == 302
    task = EventTask.objects.get(title="Согласовать концепцию")
    assert response.url == reverse("core:task_detail", args=[task.pk]) + "?" + urlencode({"return_to": "/tasks/"})
    assert task.deadline == event.date - timedelta(days=7)
    assert task.responsible is None


def test_explicit_date_keeps_priority_after_offset_edit(client, form_operator, crm_objects):
    event = crm_objects["event"]
    explicit_date = timezone.localdate() + timedelta(days=10)
    response = client.post(reverse("core:task_create"), payload(event, deadline=explicit_date.isoformat(), deadline_offset_days="-7"))
    assert response.status_code == 302
    task = EventTask.objects.get(title="Согласовать концепцию")
    response = client.post(reverse("core:task_update", args=[task.pk]), payload(event, deadline=explicit_date.isoformat(), deadline_offset_days="-14"))
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.deadline == explicit_date
    assert task.deadline_offset_days == -14


def test_nested_creation_keeps_event_fixed_and_opens_task(client, form_operator, crm_objects):
    event = crm_objects["event"]
    url = reverse("core:event_task_create", kwargs={"event_pk": event.pk})
    response = client.get(url)
    assert response.context["form"].fields["event"].disabled
    assert response.context["cancel_url"] == reverse("core:event_detail", args=[event.pk]) + "?tab=tasks#event-tabs"
    response = client.post(url, payload(event, event="999999999"))
    assert response.status_code == 302
    task = EventTask.objects.get(title="Согласовать концепцию")
    assert response.url == reverse("core:task_detail", args=[task.pk]) + "?return_tab=tasks"
    assert task.event == event


def test_create_form_is_clear_and_calculation_settings_start_closed(client, form_operator):
    response = client.get(reverse("core:task_create"))
    html = response.content.decode()
    form = response.context["form"]
    assert form.fields["event"].empty_label == "Выберите мероприятие"
    assert form.fields["title"].widget.attrs["placeholder"]
    assert form.fields["deadline"].label == "Срок задачи"
    assert not form.deadline_settings_open
    assert "Обязательные поля" in html
    assert "Указанная дата имеет приоритет" in html


@pytest.mark.parametrize("origin", ["/tasks/?filter=open&mine=1&page=2", "https://evil.example/", ""])
def test_edit_save_and_cancel_open_task_with_safe_list_context(client, form_operator, crm_objects, origin):
    task = crm_objects["task"]
    url = reverse("core:task_update", args=[task.pk])
    safe_origin = origin if origin.startswith("/tasks/") else "/tasks/"
    expected = reverse("core:task_detail", args=[task.pk]) + "?" + urlencode({"return_to": safe_origin})
    response = client.get(url, {"return_to": origin})
    assert response.context["cancel_url"] == expected
    invalid = client.post(url, payload(task.event, title="", return_to=origin))
    assert invalid.status_code == 200
    assert invalid.context["cancel_url"] == expected
    saved = client.post(url, payload(task.event, return_to=origin))
    assert saved.url == expected
    detail = client.get(saved.url)
    assert detail.context["task_return_url"] == safe_origin
    assert "← К списку задач" in detail.content.decode()


def test_event_edit_cancel_and_save_stay_in_tasks_tab(client, form_operator, crm_objects):
    task = crm_objects["task"]
    url = reverse("core:task_update", args=[task.pk])
    expected = reverse("core:event_detail", args=[task.event_id]) + "?tab=tasks#event-tabs"
    response = client.get(url, {"return_tab": "tasks", "return_to": "/tasks/?mine=1"})
    assert response.context["cancel_url"] == expected
    assert response.context["cancel_label"] == "← К мероприятию"
    saved = client.post(url, payload(task.event, return_tab="tasks", return_to="/tasks/?mine=1"))
    assert saved.url == expected


def test_task_created_from_event_keeps_event_context_through_status(client, form_operator, crm_objects):
    task = crm_objects["task"]
    detail_url = reverse("core:task_detail", args=[task.pk]) + "?return_tab=tasks"
    response = client.get(detail_url)
    html = response.content.decode()
    assert response.context["task_event_return_url"] == reverse("core:event_detail", args=[task.event_id]) + "?tab=tasks#event-tabs"
    assert "← К мероприятию" in html
    assert '?return_tab=tasks" class="btn btn-outline-secondary"' in html
    assert 'name="return_tab" value="tasks"' in html
    changed = client.post(reverse("core:task_status_update", args=[task.pk]), {"return_task": "1", "return_tab": "tasks", "status": "in_progress"})
    assert changed.url == detail_url
