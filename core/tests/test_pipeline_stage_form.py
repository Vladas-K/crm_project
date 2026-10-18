import re

import pytest
from django.test import Client as CSRFClient
from django.urls import reverse

from core.forms import PipelineStageForm
from core.models import PipelineStage
from core.tests.test_permissions import create_user_with_profile


pytestmark = pytest.mark.django_db


@pytest.fixture
def stage_admin(client, django_user_model):
    user = create_user_with_profile(django_user_model, "stage_admin", can_manage_system=True)
    client.force_login(user)
    return user


def test_new_stage_form_uses_next_position_without_saving_on_get(client, stage_admin):
    PipelineStage.objects.create(name="Последний этап", code="last_stage", order=17)
    count = PipelineStage.objects.count()

    response = client.get(reverse("core:pipeline_create"))

    assert response.status_code == 200
    assert "core/pipeline_stage_form.html" in [template.name for template in response.templates]
    assert response.context["form"]["order"].value() == 18
    assert response.context["cancel_url"] == reverse("core:pipeline")
    assert response.context["submit_label"] == "Создать этап"
    assert not response.context["form"].fields["code"].required
    html = response.content.decode()
    assert "Название этапа" in html
    assert "Дополнительные настройки" in html
    assert "Django admin" not in html
    assert '<details class="lead-form-more">' in html
    assert PipelineStage.objects.count() == count


def test_next_position_starts_at_one_and_honors_explicit_initial():
    PipelineStage.objects.all().delete()
    assert PipelineStageForm()["order"].value() == 1
    assert PipelineStageForm(initial={"order": 0})["order"].value() == 0


def test_edit_stage_preserves_initial_zero_position(client, stage_admin):
    stage = PipelineStage.objects.create(name="Этап в начале", code="first", order=0, probability=25)

    response = client.get(reverse("core:pipeline_update", args=[stage.pk]))

    assert response.status_code == 200
    assert response.context["form"]["order"].value() == 0
    assert response.context["form"]["code"].value() == "first"
    assert response.context["submit_label"] == "Сохранить изменения"
    assert "core/pipeline_stage_form.html" in [template.name for template in response.templates]


def test_create_stage_generates_code_and_returns_to_pipeline(client, stage_admin):
    initial = client.get(reverse("core:pipeline_create")).context["form"]["order"].value()

    response = client.post(reverse("core:pipeline_create"), {
        "name": "Согласование сметы", "order": initial, "probability": 45,
    })

    assert response.status_code == 302
    assert response.url == reverse("core:pipeline")
    stage = PipelineStage.objects.get(name="Согласование сметы")
    assert re.fullmatch(r"stage-[0-9a-f]{32}", stage.code)
    assert stage.order == initial
    assert stage.probability == 45
    assert not stage.is_lost


def test_generated_codes_are_distinct_for_non_latin_names():
    codes = []
    for name in ("Ожидаем документы", "Подтверждаем площадку"):
        form = PipelineStageForm(data={"name": name, "order": 12, "probability": 20})
        assert form.is_valid(), form.errors
        codes.append(form.save().code)
    assert len(set(codes)) == 2
    assert all(code.isascii() and len(code) <= 50 for code in codes)


@pytest.mark.parametrize("code_data", [{}, {"code": ""}, {"code": "   "}])
def test_edit_preserves_existing_code_when_omitted_or_blank(client, stage_admin, code_data):
    stage = PipelineStage.objects.create(name="Прежний этап", code="stable_code", order=6, probability=50)

    response = client.post(reverse("core:pipeline_update", args=[stage.pk]), dict(
        {"name": "Новое название этапа", "order": 0, "probability": 0, "is_lost": "on"}, **code_data,
    ))

    assert response.status_code == 302
    assert response.url == reverse("core:pipeline")
    stage.refresh_from_db()
    assert stage.code == "stable_code"
    assert stage.name == "Новое название этапа"
    assert stage.order == 0
    assert stage.probability == 0
    assert stage.is_lost


@pytest.mark.parametrize("editing", [False, True])
def test_custom_code_can_be_saved_explicitly(client, stage_admin, editing):
    stage = PipelineStage.objects.create(name="Настраиваемый этап", code="old_custom") if editing else None
    url = reverse("core:pipeline_update", args=[stage.pk]) if editing else reverse("core:pipeline_create")

    response = client.post(url, {"name": "Ручная настройка", "code": "custom-stage_2026", "order": 2, "probability": 100})

    assert response.status_code == 302
    saved = PipelineStage.objects.get(name="Ручная настройка")
    assert saved.code == "custom-stage_2026"
    if editing:
        assert saved.pk == stage.pk


@pytest.mark.parametrize("code", ["код", "two words", "bad/code", "a" * 51, "new_lead"])
def test_invalid_or_duplicate_code_opens_additional_settings(client, stage_admin, code):
    count = PipelineStage.objects.count()

    response = client.post(reverse("core:pipeline_create"), {
        "name": "Этап с ошибкой кода", "code": code, "order": 12, "probability": 25,
    })

    assert response.status_code == 200
    assert "code" in response.context["form"].errors
    assert '<details class="lead-form-more" open>' in response.content.decode()
    assert PipelineStage.objects.count() == count


@pytest.mark.parametrize("probability", [-1, 101])
def test_invalid_probability_keeps_entered_values_on_edit(client, stage_admin, probability):
    stage = PipelineStage.objects.create(name="Исходный этап", code="keep_values", order=4, probability=40)

    response = client.post(reverse("core:pipeline_update", args=[stage.pk]), {
        "name": "Название из формы", "order": 9, "probability": probability, "is_lost": "on",
    })

    assert response.status_code == 200
    form = response.context["form"]
    assert "probability" in form.errors
    assert form["name"].value() == "Название из формы"
    assert form["order"].value() == "9"
    assert form["is_lost"].value()
    stage.refresh_from_db()
    assert (stage.name, stage.code, stage.order, stage.probability, stage.is_lost) == ("Исходный этап", "keep_values", 4, 40, False)


@pytest.mark.parametrize("invalid_data,error_field", [
    ({"name": ""}, "name"),
    ({"name": "Новый лид"}, "name"),
    ({"order": -1}, "order"),
])
def test_stage_form_validates_name_and_position(client, stage_admin, invalid_data, error_field):
    count = PipelineStage.objects.count()
    data = dict({"name": "Новый проверочный этап", "order": 9, "probability": 0}, **invalid_data)
    response = client.post(reverse("core:pipeline_create"), data)
    assert response.status_code == 200
    assert error_field in response.context["form"].errors
    assert PipelineStage.objects.count() == count


@pytest.mark.parametrize("editing", [False, True])
def test_post_cannot_bypass_system_permission(client, django_user_model, editing):
    user = create_user_with_profile(django_user_model, "stage_viewer", can_manage_leads=True, can_manage_system=False)
    client.force_login(user)
    stage = PipelineStage.objects.create(name="Защищённый этап", code="protected_stage", order=3)
    count = PipelineStage.objects.count()
    url = reverse("core:pipeline_update", args=[stage.pk]) if editing else reverse("core:pipeline_create")

    response = client.post(url, {"name": "Подмена", "order": 1, "probability": 99, "can_manage_system": "on"})

    assert response.status_code == 403
    stage.refresh_from_db()
    assert stage.name == "Защищённый этап"
    assert PipelineStage.objects.count() == count


@pytest.mark.parametrize("editing", [False, True])
def test_stage_forms_require_csrf_token(stage_admin, editing):
    client = CSRFClient(enforce_csrf_checks=True)
    client.force_login(stage_admin)
    stage = PipelineStage.objects.create(name="Этап CSRF", code="csrf_stage", order=3)
    count = PipelineStage.objects.count()
    url = reverse("core:pipeline_update", args=[stage.pk]) if editing else reverse("core:pipeline_create")
    response = client.post(url, {"name": "Подмена CSRF", "order": 1, "probability": 0})
    assert response.status_code == 403
    assert PipelineStage.objects.count() == count
    stage.refresh_from_db()
    assert stage.name == "Этап CSRF"
