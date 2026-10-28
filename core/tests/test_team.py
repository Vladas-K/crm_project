import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from core.models import TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def team_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="operator")
    TeamMemberProfile.objects.create(user=user, role="admin", can_manage_system=True)
    client.force_login(user)
    return user


def test_team_shows_unprofiled_and_inactive_accounts_with_all_rights(client, team_operator, django_user_model):
    user = django_user_model.objects.create_user(username="employee", first_name="Анна", last_name="Петрова", email="anna@example.test", is_active=False)
    TeamMemberProfile.objects.create(user=user, role="finance", can_view_finance=True, can_manage_events=False)
    missing = django_user_model.objects.create_user(username="without_profile")
    response = client.get(reverse("core:team"))
    rows = {row["user"].pk: row for row in response.context["team_rows"]}
    assert rows[user.pk]["role_label"] == "Финансист"
    assert len(rows[user.pk]["rights"]) == 7
    assert rows[missing.pk]["profile"] is None
    html = response.content.decode()
    for text in ("Анна Петрова", "anna@example.test", "Отключён", "Управление мероприятиями", "Без CRM-профиля"):
        assert text in html
    assert 'aria-current="page">Пользователи и роли</a>' in html
    assert not response.context["add_user_url"]
    assert not rows[user.pk]["edit_user_url"]


def test_team_search_and_filters(client, team_operator, django_user_model):
    user = django_user_model.objects.create_user(username="anna", first_name="Анна", last_name="Петрова", is_active=False)
    TeamMemberProfile.objects.create(user=user, role="finance")
    params = {"q": "Петрова Анна", "role": "finance", "activity": "inactive"}
    response = client.get(reverse("core:team"), params)
    assert list(response.context["team_users"]) == [user]
    assert "activity=inactive" in response.context["pagination_query"]
    assert not client.get(reverse("core:team"), {**params, "activity": "active"}).context["team_users"]
    assert "Пользователи не найдены" in client.get(reverse("core:team"), {"q": "doesnotexist"}).content.decode()
    plain = django_user_model.objects.create_user(username="plain")
    assert list(client.get(reverse("core:team"), {"role": "without_profile"}).context["team_users"]) == [plain]
    normalized = client.get(reverse("core:team"), {"role": "invalid", "activity": "invalid"})
    assert normalized.context["team_role"] == normalized.context["team_activity"] == ""


def test_team_admin_links_require_staff_and_relevant_permissions(client, team_operator, django_user_model):
    user = django_user_model.objects.create_user(username="target")
    profile = TeamMemberProfile.objects.create(user=user, role="finance")
    permissions = Permission.objects.filter(codename__in=["change_user", "add_user", "change_teammemberprofile", "add_teammemberprofile"])
    team_operator.user_permissions.set(permissions)
    assert not client.get(reverse("core:team")).context["add_user_url"]
    team_operator.is_staff = True
    team_operator.save()
    response = client.get(reverse("core:team"))
    row = next(row for row in response.context["team_rows"] if row["user"].pk == user.pk)
    assert response.context["add_user_url"] == reverse("admin:auth_user_add")
    assert row["edit_user_url"] == reverse("admin:auth_user_change", args=[user.pk])
    assert row["edit_profile_url"] == reverse("admin:core_teammemberprofile_change", args=[profile.pk])
    bare = django_user_model.objects.create_user(username="bare")
    rows = client.get(reverse("core:team")).context["team_rows"]
    assert next(row for row in rows if row["user"].pk == bare.pk)["add_profile_url"].endswith(f"?user={bare.pk}")


def test_team_pagination_is_stable_and_keeps_filters(client, team_operator, django_user_model):
    for i in range(21):
        django_user_model.objects.create_user(username=f"search_{i:02}")
    response = client.get(reverse("core:team"), {"q": "search_", "page": 2})
    assert len(response.context["team_rows"]) == 1
    assert response.context["page_obj"].paginator.count == 21
    assert response.context["pagination_query"] == "q=search_"
