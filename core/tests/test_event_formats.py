import pytest
from django.urls import reverse

from core.models import CRMRole, Event, EventFormat, TeamMemberProfile


pytestmark = pytest.mark.django_db


@pytest.fixture
def format_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="format_operator")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_manage_system=True,
        can_view_finance=False,
    )
    client.force_login(user)
    return user


@pytest.mark.parametrize("update", [False, True])
def test_format_form_exposes_only_name_and_description(client, format_operator, crm_objects, update):
    kwargs = {"pk": crm_objects["event_format"].pk} if update else {}
    response = client.get(reverse("core:format_update" if update else "core:format_create", kwargs=kwargs))

    assert response.status_code == 200
    assert "core/format_form.html" in [template.name for template in response.templates]
    form = response.context["form"]
    assert list(form.fields) == ["name", "description"]
    assert form.fields["name"].label == "Название формата"
    assert form.fields["name"].required is True
    assert form.fields["description"].required is False
    assert response.context["cancel_url"] == reverse("core:formats")
    assert response.context["submit_label"] == ("Сохранить изменения" if update else "Создать формат")


def test_format_crud_updates_reference_data_without_changing_event_content(client, format_operator, crm_objects):
    event = crm_objects["event"]
    event_pk = event.pk
    relations = ("tasks", "timeline_items", "expenses", "event_vendors")
    expected_records = {relation: list(getattr(event, relation).order_by("pk").values()) for relation in relations}
    planned_budget = event.planned_budget

    response = client.post(
        reverse("core:format_create"),
        {"name": "Корпоративный выезд", "description": "Совместный отдых команды", "default_budget": "900000"},
    )

    assert response.status_code == 302
    assert response.url == reverse("core:formats")
    event_format = EventFormat.objects.get(name="Корпоративный выезд")
    assert event_format.description == "Совместный отдых команды"
    event.event_format = event_format
    event.save(update_fields=["event_format"])

    response = client.post(
        reverse("core:format_update", args=[event_format.pk]),
        {"name": "Выезд команды", "description": "", "default_budget": "1"},
    )

    assert response.status_code == 302
    assert response.url == reverse("core:formats")
    event_format.refresh_from_db()
    assert event_format.name == "Выезд команды"
    assert event_format.description == ""

    response = client.post(reverse("core:format_delete", args=[event_format.pk]))

    assert response.status_code == 302
    assert response.url == reverse("core:formats")
    assert not EventFormat.objects.filter(pk=event_format.pk).exists()
    event = Event.objects.get(pk=event_pk)
    assert event.event_format_id is None
    assert event.planned_budget == planned_budget
    for relation in relations:
        assert list(getattr(event, relation).order_by("pk").values()) == expected_records[relation]


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_format_mutating_posts_require_system_permission(
    client, format_operator, crm_objects, action
):
    profile = format_operator.crm_profile
    profile.can_manage_system = False
    profile.can_manage_events = True
    profile.save(update_fields=["can_manage_system", "can_manage_events"])
    event_format = crm_objects["event_format"]
    original_count = EventFormat.objects.count()
    original_name, original_description = event_format.name, event_format.description
    kwargs = {"pk": event_format.pk} if action != "create" else {}

    response = client.post(
        reverse(f"core:format_{action}", kwargs=kwargs),
        {"name": "Попытка изменения", "description": "Нет системного доступа"},
    )

    assert response.status_code == 403
    assert EventFormat.objects.count() == original_count
    event_format.refresh_from_db()
    assert event_format.name == original_name
    assert event_format.description == original_description
