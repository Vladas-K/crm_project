import pytest
from datetime import timedelta

from django.utils import timezone
from django.urls import reverse

from core.models import CRMRole, Event, Lead, TeamMemberProfile


def create_user_with_profile(django_user_model, username, **profile_flags):
    user = django_user_model.objects.create_user(username=username, password="TestPass123!")
    defaults = {
        "role": CRMRole.PROJECT_MANAGER,
        "can_view_finance": False,
        "can_view_clients": True,
        "can_view_analytics": False,
        "can_manage_system": False,
    }
    defaults.update(profile_flags)
    TeamMemberProfile.objects.create(user=user, **defaults)
    return user


def get_sidebar_html(response):
    html = response.content.decode()
    start = html.index('<nav class="crm-nav">')
    end = html.index("</nav>", start)
    return html[start:end]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name",
    [
        "clients",
        "analytics",
        "team",
    ],
)
def test_permission_protected_sections_require_crm_profile(client, django_user_model, url_name):
    user = django_user_model.objects.create_user(username="without_profile", password="TestPass123!")
    client.force_login(user)

    response = client.get(reverse(f"core:{url_name}"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_clients_section_requires_client_access_flag(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "no_clients",
        can_view_clients=False,
    )
    client.force_login(user)
    urls = [
        reverse("core:clients"),
        reverse("core:client_create"),
        reverse("core:client_update", kwargs={"pk": crm_objects["client"].pk}),
        reverse("core:client_delete", kwargs={"pk": crm_objects["client"].pk}),
    ]

    for url in urls:
        response = client.get(url)

        assert response.status_code == 403


@pytest.mark.django_db
def test_clients_section_allows_user_with_client_access_flag(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "client_manager",
        can_view_clients=True,
    )
    client.force_login(user)
    urls = [
        reverse("core:clients"),
        reverse("core:client_create"),
        reverse("core:client_update", kwargs={"pk": crm_objects["client"].pk}),
        reverse("core:client_delete", kwargs={"pk": crm_objects["client"].pk}),
    ]

    for url in urls:
        response = client.get(url)

        assert response.status_code == 200


@pytest.mark.django_db
def test_analytics_requires_analytics_access_flag(client, django_user_model):
    user = create_user_with_profile(
        django_user_model,
        "no_analytics",
        can_view_analytics=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_analytics_allows_user_with_analytics_access_flag(client, django_user_model):
    user = create_user_with_profile(
        django_user_model,
        "analyst",
        can_view_analytics=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_analytics_contains_pipeline_chart_data(client, django_user_model, crm_objects):
    """Аналитика передаёт в график этапы воронки и количество лидов."""
    user = create_user_with_profile(
        django_user_model,
        "pipeline_analyst",
        can_view_analytics=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'id="pipeline-chart"' in html
    matching_stage = next(
        item for item in response.context["pipeline_chart"] if item["label"] == "Новый"
    )
    assert matching_stage == {
        "label": "Новый",
        "total": 1,
        "color": "rgba(100, 116, 139, 0.78)",
        "url": f"{reverse('core:pipeline')}?stage={crm_objects['stage'].pk}",
    }


@pytest.mark.django_db
def test_pipeline_accepts_stage_filter_from_analytics(client, django_user_model, crm_objects):
    """Воронка открывает выбранный этап по ссылке из аналитики."""
    user = create_user_with_profile(
        django_user_model,
        "pipeline_viewer",
    )
    client.force_login(user)

    response = client.get(reverse("core:pipeline"), {"stage": crm_objects["stage"].pk})

    assert response.status_code == 200
    assert list(response.context["stages"]) == [crm_objects["stage"]]


@pytest.mark.django_db
def test_analytics_contains_source_chart_data(client, django_user_model):
    """Аналитика передаёт в график источников количество лидов и ссылки на фильтр."""
    user = create_user_with_profile(
        django_user_model,
        "source_analyst",
        can_view_analytics=True,
    )
    client.force_login(user)
    Lead.objects.create(name="Лид с сайта", source="Сайт")
    Lead.objects.create(name="Лид из рекламы", source="Реклама")

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200
    source_chart = response.context["source_chart"]
    assert {item["label"] for item in source_chart} == {"Сайт", "Реклама"}
    assert {item["url"] for item in source_chart} == {
        f"{reverse('core:leads')}?source=%D0%A1%D0%B0%D0%B9%D1%82",
        f"{reverse('core:leads')}?source=%D0%A0%D0%B5%D0%BA%D0%BB%D0%B0%D0%BC%D0%B0",
    }


@pytest.mark.django_db
def test_analytics_contains_monthly_event_chart_data(client, django_user_model, crm_objects):
    """Аналитика передаёт месячную динамику мероприятий со ссылками на фильтр."""
    user = create_user_with_profile(
        django_user_model,
        "monthly_analyst",
        can_view_analytics=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200
    matching_month = next(item for item in response.context["monthly_chart"] if item["label"].endswith("2026"))
    assert matching_month["total"] == 1
    assert matching_month["url"].endswith("?month=2026-08")


@pytest.mark.django_db
def test_analytics_contains_team_chart_data(client, django_user_model, crm_objects):
    """Аналитика передаёт загрузку менеджеров со ссылками на фильтр мероприятий."""
    user = create_user_with_profile(
        django_user_model,
        "team_analyst",
        can_view_analytics=True,
    )
    manager = django_user_model.objects.create_user(username="project_manager")
    crm_objects["event"].manager = manager
    crm_objects["event"].save(update_fields=["manager"])
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200
    assert response.context["team_chart"] == [
        {
            "label": "project_manager",
            "total": 1,
            "url": f"{reverse('core:events')}?manager={manager.pk}",
        }
    ]


@pytest.mark.django_db
def test_analytics_contains_finance_chart_for_finance_user(client, django_user_model, crm_objects):
    """Пользователь с финансовым правом видит бюджет и расходы по месяцам."""
    user = create_user_with_profile(
        django_user_model,
        "finance_analyst",
        can_view_analytics=True,
        can_view_finance=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200
    matching_month = next(item for item in response.context["finance_monthly_chart"] if item["label"].endswith("2026"))
    assert matching_month["budget"] == 100000.0
    assert matching_month["expenses"] == 50000.0


@pytest.mark.django_db
def test_analytics_hides_finance_chart_without_finance_access(client, django_user_model, crm_objects):
    """Пользователь без финансового права не получает финансовые данные графика."""
    user = create_user_with_profile(
        django_user_model,
        "non_finance_analyst",
        can_view_analytics=True,
        can_view_finance=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))

    assert response.status_code == 200
    assert response.context["finance_monthly_chart"] == []
    assert "Бюджет и расходы" not in response.content.decode()


@pytest.mark.django_db
def test_analytics_period_filters_leads_events_and_finance(client, django_user_model, crm_objects):
    """Выбранный период одновременно ограничивает лиды, мероприятия и финансы."""
    user = create_user_with_profile(
        django_user_model,
        "period_analyst",
        can_view_analytics=True,
        can_view_finance=True,
    )
    old_date = timezone.localdate() - timedelta(days=220)
    old_lead = Lead.objects.create(name="Старый лид", source="Старый источник")
    Lead.objects.filter(pk=old_lead.pk).update(
        created_at=timezone.make_aware(timezone.datetime.combine(old_date, timezone.datetime.min.time()))
    )
    old_event = Event.objects.create(
        client=crm_objects["client"],
        lead=old_lead,
        event_format=crm_objects["event_format"],
        title="Старое мероприятие",
        date=old_date,
        city="Москва",
        planned_budget=250000,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"), {"period": "6m"})

    assert response.status_code == 200
    assert response.context["analytics_period"] == "6m"
    assert {item["label"] for item in response.context["source_chart"]} == {"Не указан"}
    assert all(item["label"] != old_date.strftime("%Y-%m") for item in response.context["monthly_chart"])
    assert all(item["label"] != old_date.strftime("%Y-%m") for item in response.context["finance_monthly_chart"])
    assert old_event.planned_budget not in [item["budget"] for item in response.context["finance_monthly_chart"]]
    assert 'name="period"' in response.content.decode()


@pytest.mark.django_db
def test_analytics_invalid_period_falls_back_to_all(client, django_user_model):
    """Неизвестное значение периода не ломает аналитику и означает весь период."""
    user = create_user_with_profile(
        django_user_model,
        "period_fallback_analyst",
        can_view_analytics=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"), {"period": "unknown"})

    assert response.status_code == 200
    assert response.context["analytics_period"] == "all"


@pytest.mark.django_db
def test_team_section_requires_system_access_flag(client, django_user_model):
    user = create_user_with_profile(
        django_user_model,
        "no_system_access",
        can_manage_system=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:team"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_team_section_allows_user_with_system_access_flag(client, django_user_model):
    user = create_user_with_profile(
        django_user_model,
        "system_admin",
        can_manage_system=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:team"))

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name, object_key",
    [
        ("pipeline_create", None),
        ("pipeline_update", "stage"),
        ("pipeline_delete", "stage"),
        ("format_create", None),
        ("format_update", "event_format"),
        ("format_delete", "event_format"),
        ("vendor_create", None),
        ("vendor_update", "vendor"),
        ("vendor_delete", "vendor"),
        ("package_create", None),
        ("package_update", "service_package"),
        ("package_delete", "service_package"),
    ],
)
def test_reference_data_mutations_require_system_access(client, django_user_model, crm_objects, url_name, object_key):
    """Изменение справочников доступно только пользователю с системным правом."""
    user = create_user_with_profile(
        django_user_model,
        "reference_viewer",
        can_manage_system=False,
    )
    client.force_login(user)
    kwargs = {"pk": crm_objects[object_key].pk} if object_key else {}

    response = client.get(reverse(f"core:{url_name}", kwargs=kwargs))

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name, object_key",
    [
        ("pipeline_create", None),
        ("pipeline_update", "stage"),
        ("pipeline_delete", "stage"),
        ("format_create", None),
        ("format_update", "event_format"),
        ("format_delete", "event_format"),
        ("vendor_create", None),
        ("vendor_update", "vendor"),
        ("vendor_delete", "vendor"),
        ("package_create", None),
        ("package_update", "service_package"),
        ("package_delete", "service_package"),
    ],
)
def test_reference_data_mutations_allow_system_access(client, django_user_model, crm_objects, url_name, object_key):
    """Пользователь с системным правом может управлять справочниками."""
    user = create_user_with_profile(
        django_user_model,
        "reference_manager",
        can_manage_system=True,
    )
    client.force_login(user)
    kwargs = {"pk": crm_objects[object_key].pk} if object_key else {}

    response = client.get(reverse(f"core:{url_name}", kwargs=kwargs))

    assert response.status_code == 200


@pytest.mark.django_db
def test_expense_actions_require_finance_access_flag(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "no_finance",
        can_view_finance=False,
    )
    client.force_login(user)
    urls = [
        reverse("core:event_expense_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_expense_update", kwargs={"pk": crm_objects["expense"].pk}),
    ]

    for url in urls:
        response = client.get(url)

        assert response.status_code == 403


@pytest.mark.django_db
def test_expense_actions_allow_user_with_finance_access_flag(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "finance_manager",
        can_view_finance=True,
    )
    client.force_login(user)
    urls = [
        reverse("core:event_expense_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_expense_update", kwargs={"pk": crm_objects["expense"].pk}),
    ]

    for url in urls:
        response = client.get(url)

        assert response.status_code == 200


@pytest.mark.django_db
def test_sidebar_hides_permission_restricted_links(client, django_user_model):
    """Sidebar hides navigation items unavailable to the current CRM user."""
    user = create_user_with_profile(
        django_user_model,
        "restricted_sidebar",
        can_view_clients=False,
        can_view_analytics=False,
        can_manage_system=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:dashboard"))
    sidebar = get_sidebar_html(response)

    assert reverse("core:clients") not in sidebar
    assert reverse("core:analytics") not in sidebar
    assert reverse("core:team") not in sidebar
    assert "/admin/" not in sidebar


@pytest.mark.django_db
def test_sidebar_shows_links_allowed_by_permissions(client, django_user_model):
    """Sidebar shows protected navigation items when profile flags allow them."""
    user = create_user_with_profile(
        django_user_model,
        "full_sidebar",
        can_view_clients=True,
        can_view_analytics=True,
        can_manage_system=True,
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    client.force_login(user)

    response = client.get(reverse("core:dashboard"))
    sidebar = get_sidebar_html(response)

    assert reverse("core:clients") in sidebar
    assert reverse("core:analytics") in sidebar
    assert reverse("core:team") in sidebar
    assert "/admin/" in sidebar


@pytest.mark.django_db
def test_event_detail_hides_financial_ui_without_finance_access(client, django_user_model, crm_objects):
    """Event card hides expense tabs, actions and financial indicators without finance access."""
    user = create_user_with_profile(
        django_user_model,
        "event_no_finance",
        can_view_finance=False,
    )
    client.force_login(user)

    response = client.get(f"{reverse('core:event_detail', kwargs={'pk': crm_objects['event'].pk})}?tab=expenses")
    html = response.content.decode()

    assert response.status_code == 200
    assert "Плановый бюджет" not in html
    assert "Расходы" not in html
    assert "Прибыль" not in html
    assert "Маржа" not in html
    assert "Предоплата" not in html
    assert reverse("core:event_expense_create", kwargs={"event_pk": crm_objects["event"].pk}) not in html
    assert reverse("core:event_expense_update", kwargs={"pk": crm_objects["expense"].pk}) not in html


@pytest.mark.django_db
def test_event_detail_shows_financial_ui_with_finance_access(client, django_user_model, crm_objects):
    """Event card shows expense tab, actions and financial indicators with finance access."""
    user = create_user_with_profile(
        django_user_model,
        "event_finance",
        can_view_finance=True,
    )
    client.force_login(user)

    response = client.get(f"{reverse('core:event_detail', kwargs={'pk': crm_objects['event'].pk})}?tab=expenses")
    html = response.content.decode()

    assert response.status_code == 200
    assert "Плановый бюджет" in html
    assert "Расходы" in html
    assert "Прибыль" in html
    assert "Маржа" in html
    assert "Предоплата" in html
    assert reverse("core:event_expense_create", kwargs={"event_pk": crm_objects["event"].pk}) in html
    assert reverse("core:event_expense_update", kwargs={"pk": crm_objects["expense"].pk}) in html


@pytest.mark.django_db
def test_events_list_hides_financial_indicators_without_finance_access(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "events_no_finance",
        can_view_finance=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:events"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Бюджет" not in html
    assert "Маржинальность" not in html


@pytest.mark.django_db
def test_analytics_hides_financial_indicators_without_finance_access(client, django_user_model, crm_objects):
    user = create_user_with_profile(
        django_user_model,
        "analytics_no_finance",
        can_view_analytics=True,
        can_view_finance=False,
    )
    client.force_login(user)

    response = client.get(reverse("core:analytics"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Средний чек" not in html
    assert "Прибыль" not in html
    assert "Источник → деньги" not in html
    assert "Источники лидов" in html
