from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from core.forms import LeadForm, PipelineStageForm
from core.models import CRMRole, Lead, PipelineStage
from core.tests.test_permissions import create_user_with_profile

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(client, django_user_model):
    user = create_user_with_profile(django_user_model, "pipeline_operator")
    client.force_login(user)
    return user


def group_for(response, stage):
    return next(group for group in response.context["pipeline_groups"] if group["stage"] == stage)


def test_pipeline_limits_previews_and_links_to_complete_filtered_list(client, operator):
    stage = PipelineStage.objects.create(name="Переговоры превью", code="preview", probability=40)
    leads = [Lead.objects.create(name=f"Анна {index}", stage=stage, manager=operator) for index in range(6)]
    Lead.objects.filter(pk__in=[lead.pk for lead in leads]).update(created_at=timezone.now() - timezone.timedelta(days=2))
    Lead.objects.create(name="Другой лид", stage=stage)
    params = {"q": "анна", "manager": str(operator.pk), "attention": "needs_response", "stage": str(stage.pk)}

    response = client.get(reverse("core:pipeline"), params)
    group = group_for(response, stage)

    assert response.status_code == 200
    assert group["total"] == 6
    assert [lead.pk for lead in group["leads"]] == [lead.pk for lead in reversed(leads[-4:])]
    assert "Показаны 4 из 6" in response.content.decode()
    assert parse_qs(urlsplit(group["all_url"]).query) == {key: [value] for key, value in params.items()}
    assert response.context["filtered_count"] == 6
    assert response.context["pipeline_metrics"]["total"] == 7
    assert set(client.get(group["all_url"]).context["leads"]) == set(leads)


def test_pipeline_recovers_leads_after_stage_deletion(client, operator):
    stage = PipelineStage.objects.create(name="Временный", code="temporary")
    lead = Lead.objects.create(name="Без этапа", stage=stage)
    stage.delete()
    response = client.get(reverse("core:pipeline"), {"stage": "unassigned", "manager": "unassigned"})
    group = group_for(response, None)
    assert group["total"] == 1
    assert [item.pk for item in group["leads"]] == [lead.pk]
    assert list(client.get(group["all_url"]).context["leads"])[0].pk == lead.pk


@pytest.mark.parametrize("query", ["АННА", "99900", "EXAMPLE.COM"])
def test_pipeline_search_matches_contacts_case_insensitively(client, operator, query):
    lead = Lead.objects.create(name="Анна", phone="+79990001122", email="anna@example.com")
    Lead.objects.create(name="Пётр")
    response = client.get(reverse("core:pipeline"), {"q": query})
    assert [item.pk for item in group_for(response, None)["leads"]] == [lead.pk]


def test_pipeline_empty_search_and_invalid_filters(client, operator):
    Lead.objects.create(name="Анна")
    response = client.get(reverse("core:pipeline"), {"q": "нет совпадений", "stage": "bad", "manager": "bad", "attention": "bad"})
    assert response.status_code == 200
    assert response.context["filtered_count"] == 0
    assert response.context["stage_filter"] == response.context["manager_filter"] == response.context["attention_filter"] == ""
    assert "По выбранным условиям лиды не найдены" in response.content.decode()


def test_pipeline_respects_configured_stage_order(client, operator):
    response = client.get(reverse("core:pipeline"))
    assert response.context["stages"] == list(PipelineStage.objects.order_by("order", "pk"))


@pytest.mark.parametrize("manage_leads,manage_system", [(False, False), (True, False), (False, True), (True, True)])
def test_pipeline_independent_action_permissions(client, django_user_model, manage_leads, manage_system):
    user = create_user_with_profile(django_user_model, "permissions", can_manage_leads=manage_leads, can_manage_system=manage_system)
    client.force_login(user)
    stage = PipelineStage.objects.create(name="Этап", code="permissions")
    lead = Lead.objects.create(name="Лид", stage=stage)
    html = client.get(reverse("core:pipeline")).content.decode()
    assert (reverse("core:pipeline_update", args=[stage.pk]) in html) == manage_system
    assert (reverse("core:pipeline_delete", args=[stage.pk]) in html) == manage_system
    assert (reverse("core:lead_stage_update", args=[lead.pk]) in html) == manage_leads
    assert reverse("core:lead_detail", args=[lead.pk]) in html
    assert client.get(reverse("core:lead_stage_update", args=[lead.pk])).status_code == (200 if manage_leads else 403)
    response = client.post(reverse("core:lead_stage_update", args=[lead.pk]), {"stage": ""})
    assert response.status_code == (302 if manage_leads else 403)


def test_stage_change_updates_only_stage_probability_and_reason(client, operator):
    initial = PipelineStage.objects.create(name="Новый", code="initial", probability=10)
    target = PipelineStage.objects.create(name="Договор целевой", code="target", probability=80)
    lead = Lead.objects.create(name="Исходное имя", phone="+79990001122", stage=initial, probability=17, manager=operator, comment="Заметка")
    params = {"q": "Имя & контакт", "stage": str(initial.pk), "manager": str(operator.pk), "attention": "needs_response"}
    url = reverse("core:lead_stage_update", args=[lead.pk]) + "?" + urlencode(dict(params, next="https://example.com"))
    get_response = client.get(url)
    assert parse_qs(urlsplit(get_response.context["cancel_url"]).query) == {key: [value] for key, value in params.items()}
    lead.refresh_from_db()
    assert lead.stage == initial
    response = client.post(url, {"stage": target.pk, "loss_reason": "", "name": "Подмена", "manager": "", "phone": "", "probability": 1, "comment": "Подмена"})
    assert response.status_code == 302
    assert urlsplit(response.url).path == reverse("core:pipeline")
    assert parse_qs(urlsplit(response.url).query) == {key: [value] for key, value in params.items()}
    lead.refresh_from_db()
    assert (lead.stage, lead.probability) == (target, 80)
    assert (lead.name, lead.phone, lead.manager, lead.comment) == ("Исходное имя", "+79990001122", operator, "Заметка")


def test_same_stage_preserves_custom_probability_and_clearing_resets_it(client, operator):
    stage = PipelineStage.objects.create(name="Этап", code="same", probability=60)
    lead = Lead.objects.create(name="Лид", stage=stage, probability=37)
    url = reverse("core:lead_stage_update", args=[lead.pk])
    assert client.post(url, {"stage": stage.pk}).status_code == 302
    lead.refresh_from_db()
    assert lead.probability == 37
    assert client.post(url, {"stage": ""}).status_code == 302
    lead.refresh_from_db()
    assert lead.stage is None
    assert lead.probability == 0


@pytest.mark.parametrize("reason", ["", "   "])
def test_lost_stage_requires_reason_and_keeps_current_stage_on_error(client, operator, reason):
    initial = PipelineStage.objects.create(name="Текущий", code="active", probability=30)
    lost = PipelineStage.objects.create(name="Отказ", code="lost_test", is_lost=True)
    lead = Lead.objects.create(name="Лид", stage=initial)
    response = client.post(reverse("core:lead_stage_update", args=[lead.pk]), {"stage": lost.pk, "loss_reason": reason})
    assert response.status_code == 200
    assert "loss_reason" in response.context["form"].errors
    assert response.context["current_stage"] == initial.name
    lead.refresh_from_db()
    assert lead.stage == initial
    assert lead.probability == 30


def test_lost_stage_accepts_reason_without_assigning_an_unassigned_manager(client, operator, django_user_model):
    lead = Lead.objects.create(name="Лид")
    sales = create_user_with_profile(django_user_model, "sales")
    sales.crm_profile.role = CRMRole.SALES_MANAGER
    sales.crm_profile.save()
    lost = PipelineStage.objects.create(name="Отказ", code="lost_valid", is_lost=True, probability=0)
    response = client.post(reverse("core:lead_stage_update", args=[lead.pk]), {"stage": lost.pk, "loss_reason": "Не подошла цена"})
    assert response.status_code == 302
    lead.refresh_from_db()
    assert lead.stage == lost
    assert lead.loss_reason == "Не подошла цена"
    assert lead.manager is None


def test_stage_change_authentication_and_missing_object(client, operator, django_user_model):
    url = reverse("core:lead_stage_update", args=[999999])
    assert client.get(url).status_code == 404
    client.logout()
    assert client.get(url).status_code == 302
    assert client.post(url, {}).status_code == 302
    client.force_login(django_user_model.objects.create_user(username="no_profile"))
    assert client.get(url).status_code == 403
    assert client.post(url, {}).status_code == 403


@pytest.mark.parametrize("value,valid", [(-1, False), (101, False), (150, False), (0, True), (100, True)])
def test_probability_range_is_validated_by_stage_and_lead_forms(value, valid):
    stage_form = PipelineStageForm(data={"name": "Этап", "code": "range", "order": 1, "probability": value})
    lead_form = LeadForm(data={"name": "Лид", "probability": value})
    assert stage_form.is_valid() == valid
    assert lead_form.is_valid() == valid
    if not valid:
        assert "probability" in stage_form.errors
        assert "probability" in lead_form.errors
        with pytest.raises(ValidationError):
            Lead(name="Лид", probability=value).save()
