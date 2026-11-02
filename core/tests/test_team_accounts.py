from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory
from django.urls import reverse

from core.forms import TEAM_PERMISSION_LABELS, TeamMemberAccountForm
from core.models import CRMRole, Lead, TeamMemberProfile
from core.views import TeamMemberAccountUpdateView, TeamMemberCreateView

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="accounts_operator")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.ADMIN, can_manage_system=True)
    client.force_login(user)
    return user


@pytest.fixture
def target(django_user_model):
    user = django_user_model.objects.create_user(username="employee", password="Old!pass49word", first_name="Анна")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.SALES_MANAGER)
    return user


def create_data(**changes):
    return {
        "username": "new_employee", "first_name": "Анна", "last_name": "Соколова",
        "email": "anna@example.test", "is_active": True,
        "password1": "Qz!newPassword463", "password2": "Qz!newPassword463",
        "access-role": CRMRole.SALES_MANAGER, "access-can_manage_leads": True, **changes,
    }


def account_data(account, **changes):
    return {name: getattr(account, name) for name in TeamMemberAccountForm.Meta.fields} | changes


def test_create_with_explicit_rights_and_hashed_password_without_staff(client, operator, django_user_model):
    url = reverse("core:team_create")
    before = django_user_model.objects.count()
    page = client.get(url)
    assert page.status_code == 200
    assert django_user_model.objects.count() == before
    assert all(page.context["access_form"].initial[name] is False for name, _ in TEAM_PERMISSION_LABELS)
    response = client.post(url, create_data())
    assert response.status_code == 302
    user = django_user_model.objects.get(username="new_employee")
    assert user.get_full_name() == "Анна Соколова"
    assert user.email == "anna@example.test"
    assert user.check_password("Qz!newPassword463")
    assert not user.is_staff and not user.is_superuser
    assert user.is_active
    profile = user.crm_profile
    assert profile.role == CRMRole.SALES_MANAGER
    for name, _ in TEAM_PERMISSION_LABELS:
        assert getattr(profile, name) is (name == "can_manage_leads")
    assert Client().login(username="new_employee", password="Qz!newPassword463")


@pytest.mark.parametrize("changes,field", [
    ({"password2": "different"}, "password2"),
    ({"password1": "123", "password2": "123"}, "password2"),
    ({"password1": "new_employee", "password2": "new_employee"}, "password2"),
    ({"username": ""}, "username"),
    ({"username": "bad login"}, "username"),
    ({"email": "bad email"}, "email"),
    ({"access-role": "unknown"}, "role"),
])
def test_invalid_creation_saves_neither_account_nor_profile(client, operator, django_user_model, changes, field):
    users_before = django_user_model.objects.count()
    profiles_before = TeamMemberProfile.objects.count()
    response = client.post(reverse("core:team_create"), create_data(**changes))
    assert response.status_code == 200
    form = response.context["access_form"] if field == "role" else response.context["form"]
    assert field in form.errors
    assert django_user_model.objects.count() == users_before
    assert TeamMemberProfile.objects.count() == profiles_before
    assert 'role="alert"' in response.content.decode()


def test_creation_checks_both_forms_and_does_not_echo_passwords(client, operator):
    response = client.post(reverse("core:team_create"), create_data(username="", **{"access-role": ""}))
    assert "username" in response.context["form"].errors
    assert "role" in response.context["access_form"].errors
    assert "Qz!newPassword463" not in response.content.decode()


def test_duplicate_username_ignores_case(client, operator, target, django_user_model):
    response = client.post(reverse("core:team_create"), create_data(username="EMPLOYEE"))
    assert response.status_code == 200
    assert "username" in response.context["form"].errors
    assert not django_user_model.objects.filter(username="EMPLOYEE").exists()


def test_creation_ignores_forged_django_permissions_and_target(client, operator, target, django_user_model):
    permission = Permission.objects.first()
    response = client.post(reverse("core:team_create"), create_data(
        id=target.pk, user=operator.pk, is_staff=True, is_superuser=True,
        password="unhashed", user_permissions=[permission.pk], groups=[1],
    ))
    assert response.status_code == 302
    user = django_user_model.objects.get(username="new_employee")
    assert user.pk != target.pk
    assert user.check_password("Qz!newPassword463")
    assert not user.is_staff and not user.is_superuser
    assert not user.user_permissions.exists() and not user.groups.exists()
    target.refresh_from_db()
    assert target.username == "employee"


def test_creation_is_atomic_if_profile_cannot_be_saved(client, operator, django_user_model, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("profile save failed")
    monkeypatch.setattr(TeamMemberProfile, "save", fail)
    with pytest.raises(RuntimeError, match="profile save failed"):
        client.post(reverse("core:team_create"), create_data())
    assert not django_user_model.objects.filter(username="new_employee").exists()


def test_account_edit_changes_only_basic_fields(client, operator, target):
    profile_pk = target.crm_profile.pk
    password = target.password
    target.is_staff = target.is_superuser = True
    target.save()
    permission = Permission.objects.first()
    target.user_permissions.add(permission)
    response = client.post(reverse("core:team_account_update", args=[target.pk]), account_data(
        target, username="updated", first_name="Ирина", last_name="Орлова", email="irina@example.test",
        is_staff=False, is_superuser=False, password="changed", password1="changed",
        role=CRMRole.FINANCE, can_manage_system=True, user=operator.pk, user_permissions=[],
    ))
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.username == "updated"
    assert target.get_full_name() == "Ирина Орлова"
    assert target.email == "irina@example.test"
    assert target.password == password
    assert target.is_staff and target.is_superuser
    assert target.user_permissions.filter(pk=permission.pk).exists()
    assert target.crm_profile.pk == profile_pk
    assert target.crm_profile.role == CRMRole.SALES_MANAGER
    assert not target.crm_profile.can_manage_system


def test_disable_blocks_existing_session_and_new_leads_but_keeps_old_assignments(client, operator, target):
    old = Lead.objects.create(name="Прежний лид", manager=target)
    employee_client = Client()
    employee_client.force_login(target)
    url = reverse("core:team_account_update", args=[target.pk])
    response = client.post(url, account_data(target, is_active=False))
    assert response.status_code == 302
    target.refresh_from_db()
    assert not target.is_active
    assert employee_client.get(reverse("core:team")).status_code == 302
    assert not Client().login(username="employee", password="Old!pass49word")
    old.refresh_from_db()
    assert old.manager_id == target.pk
    assert Lead.objects.create(name="Новый лид").manager_id is None
    assert client.post(url, account_data(target, is_active=True)).status_code == 302
    assert Client().login(username="employee", password="Old!pass49word")


def test_self_disabling_is_forbidden_even_with_another_admin(client, operator, target):
    TeamMemberProfile.objects.filter(user=target).update(can_manage_system=True)
    response = client.post(reverse("core:team_account_update", args=[operator.pk]), account_data(operator, is_active=False))
    assert response.status_code == 200
    assert "is_active" in response.context["form"].errors
    operator.refresh_from_db()
    assert operator.is_active


def test_form_independently_protects_last_active_admin(operator, target):
    form = TeamMemberAccountForm(account_data(operator, is_active=False), instance=operator, actor=target)
    assert not form.is_valid()
    assert "is_active" in form.errors


def test_can_disable_other_system_admin_when_actor_remains_active(client, operator, target):
    TeamMemberProfile.objects.filter(user=target).update(can_manage_system=True)
    response = client.post(reverse("core:team_account_update", args=[target.pk]), account_data(target, is_active=False))
    assert response.status_code == 302
    target.refresh_from_db()
    assert not target.is_active
    assert target.crm_profile.can_manage_system


def test_editing_bare_account_does_not_create_profile(client, operator, django_user_model):
    user = django_user_model.objects.create_user(username="bare")
    url = reverse("core:team_account_update", args=[user.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, account_data(user, first_name="Новое имя")).status_code == 302
    assert not TeamMemberProfile.objects.filter(user=user).exists()


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("route", ["team_create", "team_account_update"])
def test_account_actions_require_crm_system_right(client, target, route, method):
    url = reverse(f"core:{route}", args=[target.pk] if route == "team_account_update" else [])
    assert getattr(client, method)(url).status_code == 302
    target.is_staff = target.is_superuser = True
    target.save()
    client.force_login(target)
    assert getattr(client, method)(url).status_code == 403


@pytest.mark.parametrize("view_class", [TeamMemberCreateView, TeamMemberAccountUpdateView])
@pytest.mark.parametrize("revoked", ["active", "system"])
def test_post_rechecks_current_actor_access_despite_cached_profile(operator, target, view_class, revoked):
    # Кэш запроса успел прочитать прежнее право до конкурентного изменения.
    assert operator.crm_profile.can_manage_system
    if revoked == "active":
        type(operator).objects.filter(pk=operator.pk).update(is_active=False)
    else:
        TeamMemberProfile.objects.filter(user=operator).update(can_manage_system=False)
    request = RequestFactory().post("/team/", create_data())
    request.user = operator
    kwargs = {"pk": target.pk} if view_class is TeamMemberAccountUpdateView else {}
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        view_class.as_view()(request, **kwargs)


@pytest.mark.parametrize("route", ["team_create", "team_account_update"])
def test_account_forms_preserve_safe_return_context(client, operator, target, route):
    url = reverse(f"core:{route}", args=[target.pk] if route == "team_account_update" else [])
    return_to = "/team/?q=Анна&role=finance&activity=active&page=2"
    response = client.get(url, {"return_to": return_to})
    assert parse_qs(urlsplit(response.context["cancel_url"]).query) == parse_qs(urlsplit(return_to).query)
    data = create_data() if route == "team_create" else account_data(target)
    saved = client.post(url, {**data, "return_to": return_to})
    assert saved.status_code == 302
    assert parse_qs(urlsplit(saved.url).query) == parse_qs(urlsplit(return_to).query)


@pytest.mark.parametrize("return_to", ["https://evil.test/team/", "//evil.test/team/", "/clients/"])
def test_account_forms_reject_external_return(client, operator, target, return_to):
    for url in [reverse("core:team_create"), reverse("core:team_account_update", args=[target.pk])]:
        assert client.get(url, {"return_to": return_to}).context["cancel_url"] == reverse("core:team")


def test_account_edit_validation_does_not_partially_save(client, operator, target):
    response = client.post(reverse("core:team_account_update", args=[target.pk]), account_data(
        target, username=operator.username, first_name="Подмена", is_active=False,
    ))
    assert response.status_code == 200
    assert "username" in response.context["form"].errors
    target.refresh_from_db()
    assert target.first_name == "Анна" and target.is_active


def test_account_edit_unknown_user(client, operator):
    url = reverse("core:team_account_update", args=[999999])
    assert client.get(url).status_code == 404
    assert client.post(url, {}).status_code == 404
