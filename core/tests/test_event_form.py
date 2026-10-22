from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.forms import EventForm
from core.models import (
    CRMRole,
    Event,
    EventFormat,
    Lead,
    TeamMemberProfile,
)


pytestmark = pytest.mark.django_db


class FormHTMLParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def attributes_for(self, element_id):
        return next(attrs for _, attrs in self.elements if attrs.get("id") == element_id)


@pytest.fixture
def event_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="event_form_operator")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_manage_events=True,
        can_view_finance=True,
    )
    client.force_login(user)
    return user


@pytest.fixture
def event_payload(crm_objects):
    event = crm_objects["event"]
    return {
        "client": event.client_id,
        "lead": "",
        "event_format": event.event_format_id,
        "title": "Новое мероприятие через форму",
        "date": event.date.isoformat(),
        "city": "Санкт-Петербург",
        "guests_count": "50",
        "planned_budget": "250000.00",
        "goal": "Встреча команды",
        "preferences": "Открытая площадка",
        "stop_factors": "Без громкой музыки",
        "status": Event.Status.PLANNING,
        "manager": "",
    }


def event_form_url(crm_objects, *, update):
    kwargs = {"pk": crm_objects["event"].pk} if update else {}
    return reverse("core:event_update" if update else "core:event_create", kwargs=kwargs)


@pytest.mark.parametrize("budget", [Decimal("-0.01"), Decimal("-1000.00")])
def test_event_model_rejects_negative_budget(crm_objects, budget):
    event = crm_objects["event"]
    event.planned_budget = budget

    with pytest.raises(ValidationError) as error:
        event.full_clean()

    assert "planned_budget" in error.value.message_dict


@pytest.mark.parametrize("budget", ["0.00", "250000.50"])
def test_event_model_and_form_allow_zero_and_positive_budget(crm_objects, event_payload, budget):
    event = crm_objects["event"]
    event.planned_budget = Decimal(budget)
    event.full_clean()
    form = EventForm(dict(event_payload, planned_budget=budget), can_view_finance=True)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["planned_budget"] == Decimal(budget)


@pytest.mark.parametrize("update", [False, True])
def test_event_post_rejects_negative_budget_without_saving(
    client, event_operator, crm_objects, event_payload, update
):
    event = crm_objects["event"]
    original_count = Event.objects.count()
    original_budget, original_title = event.planned_budget, event.title

    response = client.post(event_form_url(crm_objects, update=update), dict(event_payload, planned_budget="-0.01"))

    assert response.status_code == 200
    assert "planned_budget" in response.context["form"].errors
    assert Event.objects.count() == original_count
    event.refresh_from_db()
    assert event.planned_budget == original_budget
    assert event.title == original_title


def test_event_manager_choices_include_active_crm_staff_from_every_role(django_user_model):
    staff = []
    for role in CRMRole.values:
        user = django_user_model.objects.create_user(username=f"event_{role}", first_name="Анна", last_name=role)
        TeamMemberProfile.objects.create(user=user, role=role)
        staff.append(user)
    no_profile = django_user_model.objects.create_user(username="outside_crm")
    inactive = django_user_model.objects.create_user(username="inactive_crm", is_active=False)
    TeamMemberProfile.objects.create(user=inactive, role=CRMRole.PROJECT_MANAGER)

    field = EventForm().fields["manager"]

    assert set(field.queryset) == set(staff)
    assert not field.required
    assert field.empty_label == "Без ответственного"
    assert field.label_from_instance(staff[0]) == staff[0].get_full_name()
    assert no_profile not in field.queryset
    assert inactive not in field.queryset


def test_event_manager_choices_fall_back_to_username(django_user_model):
    user = django_user_model.objects.create_user(username="manager_without_full_name")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.PROJECT_MANAGER)

    assert EventForm().fields["manager"].label_from_instance(user) == user.username


@pytest.mark.parametrize("update", [False, True])
@pytest.mark.parametrize("invalid_manager", ["inactive", "no_profile", "unknown"])
def test_event_post_rejects_new_ineligible_manager(
    client, event_operator, django_user_model, crm_objects, event_payload, update, invalid_manager
):
    manager_id = 999999
    if invalid_manager != "unknown":
        manager = django_user_model.objects.create_user(
            username="ineligible_event_manager", is_active=invalid_manager != "inactive"
        )
        if invalid_manager == "inactive":
            TeamMemberProfile.objects.create(user=manager, role=CRMRole.PROJECT_MANAGER)
        manager_id = manager.pk
    original_count = Event.objects.count()

    response = client.post(event_form_url(crm_objects, update=update), dict(event_payload, manager=manager_id))

    assert response.status_code == 200
    assert "manager" in response.context["form"].errors
    assert Event.objects.count() == original_count
    crm_objects["event"].refresh_from_db()
    assert crm_objects["event"].manager_id is None


@pytest.mark.parametrize("legacy_manager", ["inactive", "no_profile"])
@pytest.mark.parametrize("selection", ["retain", "replace", "clear"])
def test_event_edit_can_retain_replace_or_clear_current_legacy_manager(
    client, event_operator, django_user_model, crm_objects, event_payload, legacy_manager, selection
):
    event = crm_objects["event"]
    manager = django_user_model.objects.create_user(username="current_event_manager", is_active=False)
    if legacy_manager == "inactive":
        TeamMemberProfile.objects.create(user=manager, role=CRMRole.PROJECT_MANAGER)
    else:
        manager.is_active = True
        manager.save(update_fields=["is_active"])
    event.manager = manager
    event.save(update_fields=["manager"])
    another_ineligible = django_user_model.objects.create_user(username="other_ineligible_manager", is_active=False)
    field = EventForm(instance=event).fields["manager"]
    assert field.queryset.filter(pk=manager.pk).exists()
    assert not field.queryset.filter(pk=another_ineligible.pk).exists()
    assert not EventForm().fields["manager"].queryset.filter(pk=manager.pk).exists()
    selected_id = {"retain": manager.pk, "replace": event_operator.pk, "clear": ""}[selection]

    response = client.post(event_form_url(crm_objects, update=True), dict(event_payload, manager=selected_id))

    assert response.status_code == 302
    event.refresh_from_db()
    assert event.manager_id == (selected_id or None)


@pytest.mark.parametrize("update", [False, True])
@pytest.mark.parametrize("can_view_finance", [False, True])
def test_event_form_uses_dedicated_template_and_permission_aware_fields(
    client, event_operator, crm_objects, update, can_view_finance
):
    profile = event_operator.crm_profile
    profile.can_view_finance = can_view_finance
    profile.save(update_fields=["can_view_finance"])

    response = client.get(event_form_url(crm_objects, update=update))
    html = response.content.decode()
    form = response.context["form"]

    assert response.status_code == 200
    assert "core/event_form.html" in [template.name for template in response.templates]
    for section in ("Основное", "Параметры", "Запрос клиента", "Организация работы"):
        assert section in html
    assert "Django admin" not in html
    assert "Ответственный менеджер" in html
    assert "Исходный лид" in html
    assert ("planned_budget" in form.fields) is can_view_finance
    assert ('name="planned_budget"' in html) is can_view_finance
    expected_submit = "Сохранить изменения" if update else "Создать мероприятие"
    assert expected_submit in html
    assert "novalidate" in html
    assert form.fields["client"].required
    assert form.fields["date"].required
    assert form.fields["city"].required
    assert not form.fields["title"].required
    assert not form.fields["event_format"].required
    assert not form.fields["lead"].required
    assert not form.fields["manager"].required
    expected_cancel = reverse("core:event_detail", kwargs={"pk": crm_objects["event"].pk}) if update else reverse("core:events")
    assert str(response.context["cancel_url"]) == expected_cancel


def test_invalid_event_form_keeps_input_and_connects_error_to_field(
    client, event_operator, crm_objects, event_payload
):
    title = 'Мероприятие <script>alert("x")</script>'
    response = client.post(
        event_form_url(crm_objects, update=False),
        dict(event_payload, title=title, city="", planned_budget="-20.00"),
    )
    html = response.content.decode()
    parsed = FormHTMLParser(html)

    assert response.status_code == 200
    assert response.context["form"]["title"].value() == title
    assert title not in html
    assert parsed.attributes_for("id_title")["value"] == title
    assert parsed.attributes_for("id_planned_budget")["value"] == "-20.00"
    assert set(response.context["form"].errors) == {"city", "planned_budget"}
    budget_attrs = parsed.attributes_for("id_planned_budget")
    assert budget_attrs.get("aria-invalid") == "true"
    described_ids = budget_attrs.get("aria-describedby", "").split()
    assert described_ids
    element_ids = {attrs.get("id") for _, attrs in parsed.elements}
    assert set(described_ids).issubset(element_ids)
    assert not Event.objects.filter(title=title).exists()


@pytest.mark.parametrize("status", [Event.Status.PLANNING, Event.Status.COMPLETED, Event.Status.CANCELLED])
def test_event_create_redirects_to_its_detail_including_archived_statuses(
    client, event_operator, crm_objects, event_payload, status
):
    response = client.post(event_form_url(crm_objects, update=False), dict(event_payload, status=status, planned_budget="0"))

    assert response.status_code == 302
    event = Event.objects.get(title=event_payload["title"])
    assert response.url == reverse("core:event_detail", kwargs={"pk": event.pk})
    assert event.status == status
    assert event.planned_budget == Decimal("0")
    assert event.manager_id is None


@pytest.mark.parametrize("can_view_finance", [False, True])
def test_event_update_redirects_to_detail_and_saves_allowed_changes(
    client, event_operator, crm_objects, event_payload, can_view_finance
):
    profile = event_operator.crm_profile
    profile.can_view_finance = can_view_finance
    profile.save(update_fields=["can_view_finance"])
    event = crm_objects["event"]
    original_budget = event.planned_budget

    response = client.post(event_form_url(crm_objects, update=True), dict(event_payload, manager=event_operator.pk))

    assert response.status_code == 302
    assert response.url == reverse("core:event_detail", kwargs={"pk": event.pk})
    event.refresh_from_db()
    assert event.title == event_payload["title"]
    assert event.manager == event_operator
    assert event.planned_budget == (Decimal(event_payload["planned_budget"]) if can_view_finance else original_budget)


@pytest.mark.parametrize("update", [False, True])
def test_negative_budget_forgery_without_finance_permission_is_ignored(
    client, event_operator, crm_objects, event_payload, update
):
    profile = event_operator.crm_profile
    profile.can_view_finance = False
    profile.save(update_fields=["can_view_finance"])
    event = crm_objects["event"]
    event.planned_budget = 0
    event.save(update_fields=["planned_budget"])

    response = client.post(
        event_form_url(crm_objects, update=update),
        dict(event_payload, planned_budget="-100", can_view_finance="1"),
    )

    assert response.status_code == 302
    saved = Event.objects.get(title=event_payload["title"])
    assert saved.planned_budget == Decimal("0")


@pytest.mark.parametrize("select_lead", [False, True])
def test_event_client_and_source_lead_remain_independent(
    client, event_operator, crm_objects, event_payload, select_lead
):
    other_lead = Lead.objects.create(name="Новый запрос существующего клиента", manager=event_operator)
    response = client.post(
        event_form_url(crm_objects, update=False),
        dict(event_payload, lead=other_lead.pk if select_lead else ""),
    )

    assert response.status_code == 302
    event = Event.objects.get(title=event_payload["title"])
    assert event.client_id == crm_objects["client"].pk
    assert event.lead_id == (other_lead.pk if select_lead else None)
    assert event.client.lead_id == crm_objects["lead"].pk
    assert event.manager_id is None
    assert event.planned_budget == Decimal(event_payload["planned_budget"])


@pytest.mark.parametrize("update", [False, True])
def test_event_post_only_assigns_selected_format_without_changing_operational_records(
    client, event_operator, crm_objects, event_payload, update
):
    event_format = EventFormat.objects.create(name="Корпоративный выезд", description="Тип мероприятия")
    original = crm_objects["event"]
    relations = ("tasks", "timeline_items", "expenses", "event_vendors")
    expected_records = [
        list(getattr(original, relation).order_by("pk").values()) if update else []
        for relation in relations
    ]

    response = client.post(
        event_form_url(crm_objects, update=update), dict(event_payload, event_format=event_format.pk)
    )

    assert response.status_code == 302
    event = Event.objects.get(title=event_payload["title"])
    assert event.event_format == event_format
    assert event.planned_budget == Decimal(event_payload["planned_budget"])
    assert [list(getattr(event, relation).order_by("pk").values()) for relation in relations] == expected_records
