import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import CRMRole, Client, Event, EventFormat, Lead, PipelineStage, TeamMemberProfile

User = get_user_model()


def create_client_viewer(django_user_model, username):
    user = django_user_model.objects.create_user(username=username, password="TestPass123!")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_clients=True,
    )
    return user


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

    cyrillic_response = client.get(reverse("core:leads"), {"q": "анна смирнова"})

    assert list(cyrillic_response.context["leads"]) == [Lead.objects.get(name="Анна Смирнова")]


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


@pytest.mark.django_db
def test_lead_autocomplete_returns_matching_contact_data(client, django_user_model):
    """Autocomplete возвращает лиды, совпадающие по email или телефону."""
    user = django_user_model.objects.create_user(username="autocomplete_user", password="TestPass123!")
    client.force_login(user)
    Lead.objects.create(name="Анна Смирнова", phone="+79990001122", email="anna@example.com")
    Lead.objects.create(name="Пётр Иванов", phone="+79990003344", email="petr@example.com")

    response = client.get(reverse("core:lead_autocomplete"), {"q": "79990001122"})

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "id": Lead.objects.get(name="Анна Смирнова").pk,
            "name": "Анна Смирнова",
            "phone": "+79990001122",
            "email": "anna@example.com",
        }
    ]

    cyrillic_response = client.get(reverse("core:lead_autocomplete"), {"q": "анна смирнова"})

    assert cyrillic_response.status_code == 200
    assert len(cyrillic_response.json()["results"]) == 1


@pytest.mark.django_db
def test_lead_autocomplete_requires_two_characters(client, django_user_model):
    """Autocomplete не выполняет поиск по одному символу."""
    user = django_user_model.objects.create_user(username="autocomplete_user", password="TestPass123!")
    client.force_login(user)

    response = client.get(reverse("core:lead_autocomplete"), {"q": "a"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.django_db
def test_clients_search_filters_by_contact_and_type(client, django_user_model):
    """Поиск клиентов и фильтр типа работают вместе."""
    user = create_client_viewer(django_user_model, "client_filter_user")
    client.force_login(user)
    Client.objects.create(name="ООО Вектор", client_type=Client.ClientType.B2B, email="office@vector.ru")
    Client.objects.create(name="Анна Смирнова", client_type=Client.ClientType.B2C, phone="+79990005566")

    response = client.get(
        reverse("core:clients"),
        {"q": "OFFICE", "client_type": Client.ClientType.B2B},
    )

    assert response.status_code == 200
    assert list(response.context["clients"]) == [Client.objects.get(name="ООО Вектор")]


@pytest.mark.django_db
def test_client_autocomplete_returns_matching_contact_data(client, django_user_model):
    """Autocomplete клиентов возвращает совпадения по контактам без учёта регистра."""
    user = create_client_viewer(django_user_model, "client_autocomplete_user")
    client.force_login(user)
    Client.objects.create(name="ООО Вектор", email="office@vector.ru")
    Client.objects.create(name="Анна Смирнова", phone="+79990005566")

    response = client.get(reverse("core:client_autocomplete"), {"q": "ооо вектор"})

    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "ООО Вектор"


@pytest.mark.django_db
def test_events_search_filters_by_client_city_status_and_format(client, django_user_model):
    """Поиск мероприятий и фильтры статуса и формата работают вместе."""
    user = django_user_model.objects.create_user(username="event_filter_user", password="TestPass123!")
    client.force_login(user)
    first_format = EventFormat.objects.create(name="Конференция для фильтра")
    second_format = EventFormat.objects.create(name="Свадьба для фильтра")
    first_client = Client.objects.create(name="ООО Вектор")
    second_client = Client.objects.create(name="Анна Смирнова")
    matching_event = Event.objects.create(
        client=first_client,
        event_format=first_format,
        title="Большая конференция",
        city="Москва",
        date="2026-09-01",
        status=Event.Status.IN_PROGRESS,
    )
    Event.objects.create(
        client=second_client,
        event_format=second_format,
        title="Частное мероприятие",
        city="Казань",
        date="2026-09-02",
        status=Event.Status.IN_PROGRESS,
    )

    response = client.get(
        reverse("core:events"),
        {
            "q": "москва",
            "status": Event.Status.IN_PROGRESS,
            "event_format": first_format.pk,
        },
    )

    assert response.status_code == 200
    assert list(response.context["events"]) == [matching_event]
    assert response.context["search_query"] == "москва"
    assert response.context["event_status_filter"] == Event.Status.IN_PROGRESS
    assert response.context["event_format_filter"] == str(first_format.pk)


@pytest.mark.django_db
def test_event_autocomplete_returns_matching_event_data(client, django_user_model):
    """Autocomplete мероприятий возвращает совпадения по городу и клиенту."""
    user = django_user_model.objects.create_user(username="event_autocomplete_user", password="TestPass123!")
    client.force_login(user)
    event_client = Client.objects.create(name="ООО Вектор")
    event = Event.objects.create(
        client=event_client,
        title="Большая конференция",
        city="Москва",
        date="2026-09-01",
    )

    response = client.get(reverse("core:event_autocomplete"), {"q": "МОСКВА"})

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "id": event.pk,
            "title": "Большая конференция",
            "client": "ООО Вектор",
            "city": "Москва",
        }
    ]
