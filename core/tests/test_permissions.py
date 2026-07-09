import pytest
from django.urls import reverse

from core.models import CRMRole, TeamMemberProfile


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
