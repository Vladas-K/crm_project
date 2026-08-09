import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Lead, PipelineStage

User = get_user_model()


@pytest.mark.django_db
def test_leads_search_filters_by_name_phone_and_email(client, django_user_model):
    """Поиск лидов находит совпадения по имени, телефону и email."""
    user = django_user_model.objects.create_user(username="filter_user", password="TestPass123!")
    client.force_login(user)
    stage = PipelineStage.objects.create(name="Новый", code="new_filter", order=1)
    Lead.objects.create(name="Анна Смирнова", phone="+79990001122", stage=stage)
    Lead.objects.create(name="Пётр Иванов", email="petr@example.com", stage=stage)
    Lead.objects.create(name="Мария Петрова", phone="+79990003344", stage=stage)

    response = client.get(reverse("core:leads"), {"q": "example.com"})

    assert response.status_code == 200
    assert list(response.context["leads"]) == [Lead.objects.get(name="Пётр Иванов")]


@pytest.mark.django_db
def test_leads_filters_combine_stage_and_manager(client, django_user_model):
    """Фильтры этапа и ответственного работают одновременно и сохраняются в контексте."""
    user = django_user_model.objects.create_user(username="filter_user", password="TestPass123!")
    manager = User.objects.create_user(username="lead_manager")
    client.force_login(user)
    first_stage = PipelineStage.objects.create(name="Переговоры для фильтра", code="talks_filter", order=1)
    second_stage = PipelineStage.objects.create(name="Договор для фильтра", code="contract_filter", order=2)
    matching_lead = Lead.objects.create(name="Подходящий лид", stage=first_stage, manager=manager)
    Lead.objects.create(name="Другой этап", stage=second_stage, manager=manager)
    Lead.objects.create(name="Другой менеджер", stage=first_stage)

    response = client.get(
        reverse("core:leads"),
        {"q": "Подход", "stage": first_stage.pk, "manager": manager.pk},
    )

    assert response.status_code == 200
    assert list(response.context["leads"]) == [matching_lead]
    assert response.context["search_query"] == "Подход"
    assert response.context["stage_filter"] == str(first_stage.pk)
    assert response.context["manager_filter"] == str(manager.pk)
