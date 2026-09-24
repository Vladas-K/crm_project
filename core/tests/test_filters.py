import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.models import (
    CRMRole,
    Client,
    Event,
    EventFormat,
    EventRisk,
    Lead,
    PipelineStage,
    TeamMemberProfile,
    Vendor,
    VendorRole,
)

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
def test_leads_filter_by_source(client, django_user_model):
    """Фильтр источника оставляет только лиды выбранного канала."""
    user = django_user_model.objects.create_user(username="source_filter_user", password="TestPass123!")
    client.force_login(user)
    matching_lead = Lead.objects.create(name="Лид из формы", source="Сайт")
    Lead.objects.create(name="Лид из соцсетей", source="Соцсети")

    response = client.get(reverse("core:leads"), {"source": "Сайт"})

    assert response.status_code == 200
    assert list(response.context["leads"]) == [matching_lead]
    assert response.context["source_filter"] == "Сайт"


@pytest.mark.django_db
def test_leads_sort_by_probability_and_show_operational_metrics(client, django_user_model):
    """Список сортирует лиды и передаёт показатели для сводки страницы."""

    user = django_user_model.objects.create_user(username="lead_sort_user", password="TestPass123!")
    client.force_login(user)
    low_probability = Lead.objects.create(name="Низкая вероятность", probability=15)
    high_probability = Lead.objects.create(name="Высокая вероятность", probability=80)
    Lead.objects.filter(pk=low_probability.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=25)
    )

    response = client.get(reverse("core:leads"), {"sort": "probability"})

    assert response.status_code == 200
    assert list(response.context["leads"]) == [high_probability, low_probability]
    assert response.context["lead_sort"] == "probability"
    assert response.context["lead_metrics"] == {
        "total": 2,
        "recent": 2,
        "needs_response": 1,
        "average_probability": 48,
    }


@pytest.mark.django_db
def test_lead_list_shows_only_phone_and_prefers_manager_full_name(client, django_user_model):
    """Каталог скрывает email и не дублирует username вместо имени менеджера."""

    viewer = django_user_model.objects.create_user(username="lead_catalog_viewer")
    manager = django_user_model.objects.create_user(
        username="sales_named", first_name="Анна", last_name="Соколова"
    )
    Lead.objects.create(
        name="Лид с контактами",
        phone="+7 999 000-00-00",
        email="lead@example.com",
        manager=manager,
    )
    client.force_login(viewer)

    response = client.get(reverse("core:leads"))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'href="tel:+7 999 000-00-00"' in html
    assert 'href="mailto:lead@example.com"' not in html
    assert "Анна Соколова" in html
    assert "@sales_named" in html
    assert ">Реакция<" in html


@pytest.mark.django_db
def test_leads_attention_sort_places_overdue_first(client, django_user_model):
    """Сортировка по вниманию поднимает просроченные обращения наверх."""

    user = django_user_model.objects.create_user(username="lead_attention_sort", password="TestPass123!")
    client.force_login(user)
    recent_lead = Lead.objects.create(name="Свежий лид")
    overdue_lead = Lead.objects.create(name="Просроченный лид")
    Lead.objects.filter(pk=overdue_lead.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=25)
    )

    response = client.get(reverse("core:leads"), {"sort": "attention"})

    assert list(response.context["leads"]) == [overdue_lead, recent_lead]


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


@pytest.mark.django_db
def test_events_filter_by_date_range(client, django_user_model):
    """Фильтр мероприятий по диапазону дат исключает события за пределами периода."""
    user = django_user_model.objects.create_user(username="event_date_filter_user", password="TestPass123!")
    client.force_login(user)
    event_client = Client.objects.create(name="ООО Вектор")
    matching_event = Event.objects.create(
        client=event_client,
        title="Мероприятие в периоде",
        city="Москва",
        date="2026-09-15",
    )
    Event.objects.create(
        client=event_client,
        title="Раннее мероприятие",
        city="Москва",
        date="2026-09-01",
    )
    Event.objects.create(
        client=event_client,
        title="Позднее мероприятие",
        city="Москва",
        date="2026-10-01",
    )

    response = client.get(
        reverse("core:events"),
        {"date_from": "2026-09-10", "date_to": "2026-09-20"},
    )

    assert response.status_code == 200
    assert list(response.context["events"]) == [matching_event]
    assert response.context["event_date_from"] == "2026-09-10"
    assert response.context["event_date_to"] == "2026-09-20"


@pytest.mark.django_db
def test_events_filter_by_month(client, django_user_model):
    """Фильтр месяца оставляет мероприятия только выбранного периода."""
    user = django_user_model.objects.create_user(username="event_month_filter_user", password="TestPass123!")
    client.force_login(user)
    event_client = Client.objects.create(name="ООО Вектор")
    matching_event = Event.objects.create(client=event_client, title="Сентябрь", city="Москва", date="2026-09-15")
    Event.objects.create(client=event_client, title="Октябрь", city="Москва", date="2026-10-15")

    response = client.get(reverse("core:events"), {"month": "2026-09"})

    assert response.status_code == 200
    assert list(response.context["events"]) == [matching_event]
    assert response.context["event_month_filter"] == "2026-09"


@pytest.mark.django_db
def test_events_filter_by_manager(client, django_user_model):
    """Фильтр мероприятий по ответственному оставляет его проекты."""
    user = django_user_model.objects.create_user(username="event_manager_filter_user", password="TestPass123!")
    manager = User.objects.create_user(username="event_manager")
    other_manager = User.objects.create_user(username="other_event_manager")
    client.force_login(user)
    event_client = Client.objects.create(name="ООО Вектор")
    matching_event = Event.objects.create(
        client=event_client, title="Проект менеджера", city="Москва", date="2026-09-15", manager=manager
    )
    Event.objects.create(
        client=event_client, title="Другой проект", city="Москва", date="2026-09-16", manager=other_manager
    )

    response = client.get(reverse("core:events"), {"manager": manager.pk})

    assert response.status_code == 200
    assert list(response.context["events"]) == [matching_event]
    assert response.context["event_manager_filter"] == str(manager.pk)


@pytest.mark.django_db
def test_vendors_search_filters_by_status_format_and_role(client, django_user_model):
    """Поиск подрядчиков и фильтры статуса, формата и специализации работают вместе."""
    user = django_user_model.objects.create_user(username="vendor_filter_user", password="TestPass123!")
    client.force_login(user)
    event_format = EventFormat.objects.create(name="Конференция подрядчиков")
    vendor_role = VendorRole.objects.create(name="Технический продакшн")
    matching_vendor = Vendor.objects.create(
        name="Stage Team",
        roles="Технический продакшн",
        contact_person="Сергей Орлов",
        phone="+7 999 100-20-30",
        email="stage@example.com",
        service_area="Москва и область",
    )
    matching_vendor.event_formats.add(event_format)
    matching_vendor.role_categories.add(vendor_role)
    Vendor.objects.create(name="Другой подрядчик", roles="Декор", blacklisted=True)

    response = client.get(
        reverse("core:vendors"),
        {
            "q": "stage",
            "blacklisted": "no",
            "event_format": event_format.pk,
            "role": vendor_role.pk,
        },
    )

    assert response.status_code == 200
    assert list(response.context["vendors"]) == [matching_vendor]
    assert response.context["vendor_blacklist_filter"] == "no"
    assert response.context["vendor_format_filter"] == str(event_format.pk)
    assert response.context["vendor_role_filter"] == str(vendor_role.pk)
    assert response.context["vendor_selected_role"] == vendor_role


@pytest.mark.django_db
def test_vendors_can_be_sorted_by_rating(client, django_user_model):
    """Каталог подрядчиков поддерживает сортировку по рейтингу."""

    user = django_user_model.objects.create_user(username="vendor_sort_user", password="TestPass123!")
    client.force_login(user)
    top_vendor = Vendor.objects.create(name="Top Team", rating="4.90")
    Vendor.objects.create(name="Base Team", rating="4.20")

    response = client.get(reverse("core:vendors"), {"sort": "rating"})

    assert response.status_code == 200
    assert list(response.context["vendors"])[0] == top_vendor
    assert response.context["vendor_sort"] == "rating"


@pytest.mark.django_db
def test_vendor_cost_sort_requires_finance_access(client, django_user_model):
    """Сортировка по стоимости не раскрывает финансовый порядок без соответствующего права."""

    user = django_user_model.objects.create_user(username="vendor_sort_no_finance", password="TestPass123!")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_finance=False,
    )
    client.force_login(user)
    first_by_name = Vendor.objects.create(name="Alpha Team", avg_cost="90000.00")
    Vendor.objects.create(name="Zeta Team", avg_cost="10000.00")

    response = client.get(reverse("core:vendors"), {"sort": "cost"})

    assert response.status_code == 200
    assert list(response.context["vendors"])[0] == first_by_name
    assert response.context["vendor_sort"] == "name"


@pytest.mark.django_db
def test_vendor_autocomplete_returns_matching_vendor_data(client, django_user_model):
    """Autocomplete подрядчиков ищет по структурированным контактам."""
    user = django_user_model.objects.create_user(username="vendor_autocomplete_user", password="TestPass123!")
    client.force_login(user)
    Vendor.objects.create(
        name="Stage Team",
        roles="Технический продакшн",
        phone="+7 999 100-20-30",
        email="stage@example.com",
    )

    response = client.get(reverse("core:vendor_autocomplete"), {"q": "100-20-30"})

    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "Stage Team"
    assert response.json()["results"][0]["contacts"] == "stage@example.com"


@pytest.mark.django_db
def test_leads_attention_filter_returns_only_leads_without_response(client, django_user_model):
    """Фильтр внимания по лидам оставляет только обращения без ответа более 24 часов."""
    user = django_user_model.objects.create_user(username="attention_lead_filter", password="TestPass123!")
    old_lead = Lead.objects.create(name="Старый лид")
    recent_lead = Lead.objects.create(name="Свежий лид")
    Lead.objects.filter(pk=old_lead.pk).update(created_at=timezone.now() - timezone.timedelta(hours=25))
    client.force_login(user)

    response = client.get(reverse("core:leads"), {"attention": "needs_response"})

    assert list(response.context["leads"]) == [old_lead]
    assert response.context["attention_filter"] == "needs_response"
    assert "Показаны лиды без ответа более 24 часов." in response.content.decode()


@pytest.mark.django_db
def test_events_attention_filters_return_risks_or_missing_outcomes(client, django_user_model):
    """Фильтры внимания по мероприятиям разделяют риски и незаполненные итоги."""
    user = django_user_model.objects.create_user(username="attention_event_filter", password="TestPass123!")
    client_record = Client.objects.create(name="Клиент фильтра внимания")
    risky_event = Event.objects.create(client=client_record, date=timezone.localdate(), city="Москва", title="С риском")
    empty_event = Event.objects.create(client=client_record, date=timezone.localdate(), city="Москва", title="Без итогов")
    EventRisk.objects.create(event=risky_event, description="Задержка площадки")
    client.force_login(user)

    risks_response = client.get(reverse("core:events"), {"attention": "risks"})
    outcomes_response = client.get(reverse("core:events"), {"attention": "outcomes"})
    unassigned_response = client.get(reverse("core:events"), {"attention": "unassigned_manager"})

    assert list(risks_response.context["events"]) == [risky_event]
    assert {event.title for event in outcomes_response.context["events"]} == {"С риском", "Без итогов"}
    assert "Показаны мероприятия с рисками." in risks_response.content.decode()
    assert "Показаны мероприятия без заполненных итогов." in outcomes_response.content.decode()
    assert {event.title for event in unassigned_response.context["events"]} == {"С риском", "Без итогов"}
    assert "Показаны мероприятия без ответственного менеджера." in unassigned_response.content.decode()
