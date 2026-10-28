from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

from core.models import CRMRole, TeamMemberProfile

pytestmark = pytest.mark.django_db

ACCESS_FIELDS = (
    "role",
    "can_view_finance",
    "can_view_clients",
    "can_view_analytics",
    "can_manage_leads",
    "can_manage_clients",
    "can_manage_events",
    "can_manage_system",
)


@pytest.fixture
def access_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="access_operator")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.ADMIN, can_manage_system=True)
    client.force_login(user)
    return user


@pytest.fixture
def access_target(django_user_model):
    user = django_user_model.objects.create_user(
        username="access_target", first_name="Анна", last_name="Соколова", email="anna@example.test"
    )
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_finance=False,
        can_view_clients=True,
        can_view_analytics=False,
        can_manage_leads=False,
        can_manage_clients=True,
        can_manage_events=True,
        can_manage_system=False,
    )
    return user


def access_data(profile, **changes):
    data = {field: getattr(profile, field) for field in ACCESS_FIELDS}
    data.update(changes)
    return data


def test_access_form_works_for_crm_administrator_without_django_staff(client, access_operator, access_target):
    assert not access_operator.is_staff
    response = client.get(reverse("core:team_access_update", args=[access_target.pk]))

    assert response.status_code == 200
    assert "core/team_access_form.html" in [template.name for template in response.templates]
    assert set(response.context["form"].fields) == set(ACCESS_FIELDS)
    assert response.context["cancel_url"] == reverse("core:team")
    assert "Анна Соколова" in response.content.decode()


def test_access_save_changes_role_and_explicit_rights_without_role_presets(client, access_operator, access_target):
    profile = access_target.crm_profile
    expected = access_data(profile, role=CRMRole.FINANCE)
    response = client.post(reverse("core:team_access_update", args=[access_target.pk]), expected)

    assert response.status_code == 302
    assert response.url == reverse("core:team")
    profile.refresh_from_db()
    for field in ACCESS_FIELDS:
        assert getattr(profile, field) == expected[field]
    assert profile.can_view_finance is False
    assert profile.can_manage_events is True


def test_access_get_does_not_create_profile_and_post_creates_it_for_fixed_target(
    client, access_operator, django_user_model
):
    user = django_user_model.objects.create_user(username="no_crm_profile")
    url = reverse("core:team_access_update", args=[user.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert not TeamMemberProfile.objects.filter(user=user).exists()
    assert all(response.context["form"].initial[field] is False for field in ACCESS_FIELDS[1:])

    response = client.post(url, {"role": CRMRole.SALES_MANAGER, "can_manage_leads": True})

    assert response.status_code == 302
    profile = TeamMemberProfile.objects.get(user=user)
    assert profile.role == CRMRole.SALES_MANAGER
    assert profile.can_manage_leads is True
    assert profile.can_view_clients is False
    assert profile.can_manage_clients is False
    assert profile.can_manage_events is False
    assert profile.can_manage_system is False


def test_access_post_cannot_change_account_or_attach_profile_to_another_user(
    client, access_operator, access_target, django_user_model
):
    other = django_user_model.objects.create_user(username="another_account")
    original_password = access_target.password
    original_name = access_target.username
    data = access_data(access_target.crm_profile, role=CRMRole.FINANCE)
    data.update(
        user=other.pk,
        username="hijacked",
        email="changed@example.test",
        first_name="Подмена",
        is_active=False,
        is_staff=True,
        is_superuser=True,
        password="replacement-password",
    )
    response = client.post(reverse("core:team_access_update", args=[access_target.pk]), data)

    assert response.status_code == 302
    access_target.refresh_from_db()
    assert access_target.username == original_name
    assert access_target.email == "anna@example.test"
    assert access_target.first_name == "Анна"
    assert access_target.password == original_password
    assert access_target.is_active is True
    assert access_target.is_staff is False
    assert access_target.is_superuser is False
    assert TeamMemberProfile.objects.get(user=access_target).role == CRMRole.FINANCE
    assert not TeamMemberProfile.objects.filter(user=other).exists()


def test_access_can_configure_inactive_account_without_reactivating_it(client, access_operator, access_target):
    access_target.is_active = False
    access_target.save(update_fields=["is_active"])
    response = client.post(
        reverse("core:team_access_update", args=[access_target.pk]),
        access_data(access_target.crm_profile, role=CRMRole.SALES_MANAGER, can_manage_leads=True),
    )

    assert response.status_code == 302
    access_target.refresh_from_db()
    assert access_target.is_active is False
    assert access_target.crm_profile.role == CRMRole.SALES_MANAGER
    assert access_target.crm_profile.can_manage_leads is True


def test_access_cannot_remove_own_system_access_even_with_another_administrator(
    client, access_operator, django_user_model
):
    other = django_user_model.objects.create_user(username="second_administrator")
    TeamMemberProfile.objects.create(user=other, role=CRMRole.ADMIN, can_manage_system=True)
    response = client.post(
        reverse("core:team_access_update", args=[access_operator.pk]),
        access_data(access_operator.crm_profile, can_manage_system=False),
    )

    assert response.status_code == 200
    assert "can_manage_system" in response.context["form"].errors
    access_operator.crm_profile.refresh_from_db()
    assert access_operator.crm_profile.can_manage_system is True
    assert client.get(reverse("core:team")).status_code == 200


def test_access_cannot_remove_last_active_administrator_with_only_inactive_replacement(
    client, access_operator, django_user_model
):
    inactive = django_user_model.objects.create_user(username="inactive_administrator", is_active=False)
    TeamMemberProfile.objects.create(user=inactive, role=CRMRole.ADMIN, can_manage_system=True)
    response = client.post(
        reverse("core:team_access_update", args=[access_operator.pk]),
        access_data(access_operator.crm_profile, role=CRMRole.FINANCE, can_manage_system=False),
    )

    assert response.status_code == 200
    assert "can_manage_system" in response.context["form"].errors
    access_operator.crm_profile.refresh_from_db()
    assert access_operator.crm_profile.can_manage_system is True
    assert access_operator.crm_profile.role == CRMRole.ADMIN


def test_access_can_revoke_another_administrators_system_flag(client, access_operator, access_target):
    profile = access_target.crm_profile
    profile.can_manage_system = True
    profile.save(update_fields=["can_manage_system"])
    response = client.post(
        reverse("core:team_access_update", args=[access_target.pk]),
        access_data(profile, can_manage_system=False),
    )

    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.can_manage_system is False
    assert client.get(reverse("core:team")).status_code == 200


@pytest.mark.parametrize("role", ["", "unsupported_role"])
def test_access_invalid_role_does_not_partially_save_rights(client, access_operator, access_target, role):
    profile = access_target.crm_profile
    response = client.post(
        reverse("core:team_access_update", args=[access_target.pk]),
        access_data(profile, role=role, can_manage_system=True),
    )

    assert response.status_code == 200
    assert "role" in response.context["form"].errors
    profile.refresh_from_db()
    assert profile.role == CRMRole.PROJECT_MANAGER
    assert profile.can_manage_system is False


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("with_profile", [False, True])
def test_access_requires_crm_system_permission(client, access_target, django_user_model, method, with_profile):
    user = django_user_model.objects.create_user(username="forbidden_operator", is_staff=True, is_superuser=True)
    if with_profile:
        TeamMemberProfile.objects.create(user=user, role=CRMRole.ADMIN, can_manage_system=False)
    client.force_login(user)
    response = getattr(client, method)(
        reverse("core:team_access_update", args=[access_target.pk]),
        access_data(access_target.crm_profile, can_manage_system=True),
    )

    assert response.status_code == 403
    access_target.crm_profile.refresh_from_db()
    assert access_target.crm_profile.can_manage_system is False


@pytest.mark.parametrize("method", ["get", "post"])
def test_access_requires_login(client, access_target, method):
    response = getattr(client, method)(reverse("core:team_access_update", args=[access_target.pk]))
    assert response.status_code == 302
    assert urlsplit(response.url).path == reverse("login")


def test_access_return_preserves_only_team_list_context(client, access_operator, access_target):
    return_to = "/team/?q=Анна&role=finance&activity=active&page=2"
    url = reverse("core:team_access_update", args=[access_target.pk])
    response = client.get(url, {"return_to": return_to})
    assert urlsplit(response.context["cancel_url"]).path == reverse("core:team")
    assert parse_qs(urlsplit(response.context["cancel_url"]).query) == parse_qs(urlsplit(return_to).query)

    invalid = client.post(url, {**access_data(access_target.crm_profile, role=""), "return_to": return_to})
    assert invalid.status_code == 200
    assert parse_qs(urlsplit(invalid.context["cancel_url"]).query) == parse_qs(urlsplit(return_to).query)

    response = client.post(url, {**access_data(access_target.crm_profile), "return_to": return_to})
    assert response.status_code == 302
    assert urlsplit(response.url).path == reverse("core:team")
    assert parse_qs(urlsplit(response.url).query) == parse_qs(urlsplit(return_to).query)


@pytest.mark.parametrize("return_to", ["https://example.test/team/", "//example.test/team/", "/clients/", "/team/1/access/"])
def test_access_rejects_unsafe_or_unrelated_return_addresses(client, access_operator, access_target, return_to):
    url = reverse("core:team_access_update", args=[access_target.pk])
    response = client.get(url, {"return_to": return_to})
    assert response.context["cancel_url"] == reverse("core:team")
    saved = client.post(url, {**access_data(access_target.crm_profile), "return_to": return_to})
    assert saved.status_code == 302
    assert saved.url == reverse("core:team")


def test_access_unknown_account_returns_not_found(client, access_operator):
    assert client.get(reverse("core:team_access_update", args=[99999999])).status_code == 404


def test_access_return_drops_unknown_query_parameters(client, access_operator, access_target):
    return_to = "/team/?q=Анна&role=finance&activity=active&page=2&next=https://example.test&can_manage_system=1"
    response = client.get(reverse("core:team_access_update", args=[access_target.pk]), {"return_to": return_to})
    assert parse_qs(urlsplit(response.context["cancel_url"]).query) == {
        "q": ["Анна"], "role": ["finance"], "activity": ["active"], "page": ["2"],
    }


def test_access_form_protects_last_active_administrator_independently_of_self_check(access_operator, access_target):
    from core.forms import TeamMemberAccessForm

    form = TeamMemberAccessForm(
        data=access_data(access_operator.crm_profile, can_manage_system=False),
        actor=access_target,
        target_user=access_operator,
        instance=access_operator.crm_profile,
    )
    assert not form.is_valid()
    assert "can_manage_system" in form.errors
    access_operator.crm_profile.refresh_from_db()
    assert access_operator.crm_profile.can_manage_system is True
