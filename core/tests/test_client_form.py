from decimal import Decimal

import pytest
from django.urls import reverse

from core.forms import ClientForm
from core.models import CRMRole, Client, Lead, TeamMemberProfile


@pytest.fixture
def operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="client_form_operator", password="TestPass123!")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.SALES_MANAGER, can_view_clients=True, can_manage_clients=True)
    client.force_login(user)
    return user


@pytest.fixture
def payload():
    return {"creation_mode": "manual", "client_type": "b2c", "name": "Новый клиент", "segment": "standard"}


@pytest.mark.django_db
@pytest.mark.parametrize("can_view_finance", [False, True])
def test_manual_client_creation_ignores_finance_and_history(client, operator, payload, can_view_finance):
    profile = operator.crm_profile
    profile.can_view_finance = can_view_finance
    profile.save()
    response = client.get(reverse("core:client_create"))
    html = response.content.decode()
    assert response.status_code == 200
    assert 'aria-current="page">Клиенты' in html
    assert "Создать клиента" in html
    assert "Django admin" not in html
    assert {"telegram", "whatsapp", "max_messenger", "instagram", "facebook", "vk"}.issubset(response.context["form"].fields)
    for field in ("ltv", "event_history", "messenger"):
        assert f'name="{field}"' not in html
    response = client.post(reverse("core:client_create"), dict(payload, ltv="777777", event_history="Подмена"))
    saved = Client.objects.get(name=payload["name"])
    assert response.status_code == 302
    assert saved.ltv == 0
    assert saved.event_history == ""
    assert saved.lead is None


@pytest.mark.django_db
def test_client_created_from_lead_without_javascript_preserves_manual_fields(client, operator, payload):
    lead = Lead.objects.create(name="Имя из лида", phone="89991234567", email="lead@example.com", telegram="@contact", instagram="photo")
    response = client.post(reverse("core:client_create"), dict(payload, creation_mode="lead", lead=lead.pk, name="Ручное имя"))
    saved = Client.objects.get(lead=lead)
    assert response.status_code == 302
    assert saved.name == "Ручное имя"
    assert saved.phone == "+79991234567"
    assert saved.email == lead.email
    assert saved.telegram == lead.telegram
    assert saved.instagram == lead.instagram


@pytest.mark.django_db
def test_client_prefills_name_and_contacts_from_lead(client, operator, payload):
    lead = Lead.objects.create(name="Клиент из лида", email="lead@example.com", whatsapp="89991234567")
    response = client.get(reverse("core:client_create"), {"lead": lead.pk})
    form = response.context["form"]
    assert form["creation_mode"].value() == "lead"
    assert form["name"].value() == lead.name
    response = client.post(reverse("core:client_create"), dict(payload, creation_mode="lead", lead=lead.pk, name=""))
    assert response.status_code == 302
    saved = Client.objects.get(lead=lead)
    assert saved.name == lead.name
    assert saved.whatsapp == "+79991234567"


@pytest.mark.django_db
def test_manual_mode_ignores_stale_lead_selection(client, operator, payload):
    lead = Lead.objects.create(name="Не выбранный лид", email="other@example.com")
    response = client.post(reverse("core:client_create"), dict(payload, lead=lead.pk))
    saved = Client.objects.get(name=payload["name"])
    assert response.status_code == 302
    assert saved.lead is None
    assert saved.email == ""


@pytest.mark.django_db
def test_client_can_clear_imported_contact_before_saving(client, operator, payload):
    lead = Lead.objects.create(name="Клиент из лида", email="old@example.com")
    response = client.post(reverse("core:client_create"), dict(
        payload, creation_mode="lead", lead=lead.pk, lead_contacts_loaded=str(lead.pk), email="",
    ))
    assert response.status_code == 302
    assert Client.objects.get(lead=lead).email == ""


@pytest.mark.django_db
@pytest.mark.parametrize("lead_id", ["", "invalid", "9999999"])
def test_client_requires_valid_lead_in_lead_mode(client, operator, payload, lead_id):
    response = client.post(reverse("core:client_create"), dict(payload, creation_mode="lead", lead=lead_id))
    assert response.status_code == 200
    assert "lead" in response.context["form"].errors
    assert not Client.objects.exists()


@pytest.mark.django_db
def test_used_lead_is_excluded_and_cannot_be_reused(client, operator, payload):
    lead = Lead.objects.create(name="Уже связан")
    existing = Client.objects.create(name="Существующий", lead=lead)
    assert not ClientForm().fields["lead"].queryset.filter(pk=lead.pk).exists()
    assert ClientForm(instance=existing).fields["lead"].queryset.filter(pk=lead.pk).exists()
    response = client.post(reverse("core:client_create"), dict(payload, creation_mode="lead", lead=lead.pk))
    assert response.status_code == 200
    assert "lead" in response.context["form"].errors
    assert Client.objects.count() == 1
    assert client.get(reverse("core:client_lead_data"), {"lead_id": lead.pk}).status_code == 404
    assert client.get(reverse("core:client_lead_data"), {"lead_id": lead.pk, "client_id": existing.pk}).status_code == 200


@pytest.mark.django_db
def test_client_edit_preserves_finance_legacy_notes_and_shows_real_events(client, operator, payload, crm_objects):
    existing = crm_objects["client"]
    existing.ltv = Decimal("87654.32")
    existing.event_history = "Прежние заметки"
    existing.messenger = "Сохранённый контакт"
    existing.save()
    url = reverse("core:client_update", kwargs={"pk": existing.pk})
    response = client.get(url)
    html = response.content.decode()
    assert "87654" not in html
    assert "Прежние заметки" in html
    assert "Сохранённый контакт" in html
    assert reverse("core:event_detail", kwargs={"pk": crm_objects["event"].pk}) in html
    response = client.post(url, dict(payload, lead=existing.lead_id, ltv="1", event_history="Подмена", messenger="Подмена", telegram="@new"))
    existing.refresh_from_db()
    assert response.status_code == 302
    assert existing.ltv == Decimal("87654.32")
    assert existing.event_history == "Прежние заметки"
    assert existing.messenger == "Сохранённый контакт"
    assert existing.telegram == "@new"


@pytest.mark.django_db
def test_client_invalid_submission_keeps_input_and_company_label(client, operator, payload):
    response = client.post(reverse("core:client_create"), dict(payload, client_type="b2b", email="invalid"))
    assert response.status_code == 200
    form = response.context["form"]
    assert "email" in form.errors
    assert form["name"].value() == payload["name"]
    assert form["name"].label == "Название компании"
    assert not Client.objects.exists()


@pytest.mark.django_db
def test_client_lead_search_and_contact_endpoint(client, operator):
    free = Lead.objects.create(name="Свободный лид", telegram="@person", facebook="social")
    used = Lead.objects.create(name="Свободный уже связан")
    Client.objects.create(name="Существующий", lead=used)
    url = reverse("core:client_lead_data")
    response = client.get(url, {"q": "свободный"})
    assert [item["id"] for item in response.json()["results"]] == [free.pk]
    response = client.get(url, {"lead_id": free.pk})
    assert response.json()["fields"]["telegram"] == "@person"
    assert response.json()["fields"]["facebook"] == "social"
    assert response["Cache-Control"] == "no-store"
    assert client.get(url, {"lead_id": "invalid"}).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["can_manage_clients", "can_view_clients"])
def test_client_lead_endpoint_requires_both_client_permissions(client, operator, flag):
    profile = operator.crm_profile
    setattr(profile, flag, False)
    profile.save()
    assert client.get(reverse("core:client_lead_data")).status_code == 403


@pytest.mark.django_db
def test_client_lead_endpoint_requires_login(client):
    response = client.get(reverse("core:client_lead_data"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_client_ltv_list_visibility_requires_finance(client, operator):
    Client.objects.create(name="Проверка финансов", ltv=Decimal("87654.32"))
    url = reverse("core:clients")
    response = client.get(url)
    assert "LTV" not in response.content.decode()
    assert "87654" not in response.content.decode()
    profile = operator.crm_profile
    profile.can_view_finance = True
    profile.save()
    response = client.get(url)
    assert "LTV" in response.content.decode()
    assert "87654" in response.content.decode()
