from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.urls import reverse

from core.models import CRMRole, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def usability_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="usability_operator")
    TeamMemberProfile.objects.create(user=user, role=CRMRole.ADMIN, can_manage_system=True)
    client.force_login(user)
    return user


def make_accounts(user_model, prefix, count, role=None):
    users = user_model.objects.bulk_create([
        user_model(username=f"{prefix}_{index:02}", is_active=True) for index in range(count)
    ])
    if role:
        TeamMemberProfile.objects.bulk_create([
            TeamMemberProfile(user=user, role=role) for user in users
        ])
    return users


def team_url(**params):
    return reverse("core:team") + "?" + urlencode(params)


def assert_list_context(response, *, page, count, query, role, activity):
    assert response.status_code == 200
    assert response.context["page_obj"].number == page
    assert response.context["paginator"].count == count
    assert response.context["team_search"] == query
    assert response.context["team_role"] == role
    assert response.context["team_activity"] == activity


@pytest.mark.parametrize("query", [
    "анна", "АННА", "сОКоЛоВа анНА", "руководитель", "почта@example.TEST", "Соколова ПОЧТА",
])
def test_team_search_matches_unicode_words_without_case_dependency(
    client, usability_operator, django_user_model, query
):
    expected = django_user_model.objects.create_user(
        username="РУКОВОДИТЕЛЬ_42", first_name="Анна", last_name="Соколова", email="ПОЧТА@Example.test"
    )
    django_user_model.objects.create_user(username="another_person", first_name="Борис", last_name="Орлов")

    response = client.get(reverse("core:team"), {"q": query})

    assert response.status_code == 200
    assert list(response.context["team_users"]) == [expected]


def test_role_change_on_last_filtered_page_returns_to_existing_page(
    client, usability_operator, django_user_model
):
    users = make_accounts(django_user_model, "selection", 21, CRMRole.FINANCE)
    target = users[-1]
    filters = {"q": "selection", "role": CRMRole.FINANCE, "activity": "active", "page": 2}
    before = client.get(reverse("core:team"), filters)
    assert list(before.context["team_users"]) == [target]

    saved = client.post(reverse("core:team_access_update", args=[target.pk]), {
        "role": CRMRole.PROJECT_MANAGER, "return_to": team_url(**filters),
    })

    assert saved.status_code == 302
    assert urlsplit(saved.url).path == reverse("core:team")
    after = client.get(saved.url)
    assert_list_context(after, page=1, count=20, query="selection", role=CRMRole.FINANCE, activity="active")
    assert target not in after.context["team_users"]
    assert TeamMemberProfile.objects.get(user=target).role == CRMRole.PROJECT_MANAGER


def test_profile_creation_on_last_unconfigured_page_preserves_list_filters(
    client, usability_operator, django_user_model
):
    users = make_accounts(django_user_model, "unconfigured", 21)
    target = users[-1]
    filters = {"q": "unconfigured", "role": "without_profile", "activity": "active", "page": 2}
    before = client.get(reverse("core:team"), filters)
    assert list(before.context["team_users"]) == [target]

    saved = client.post(reverse("core:team_access_update", args=[target.pk]), {
        "role": CRMRole.SALES_MANAGER, "return_to": team_url(**filters),
    })

    assert saved.status_code == 302
    after = client.get(saved.url)
    assert_list_context(after, page=1, count=20, query="unconfigured", role="without_profile", activity="active")
    assert target not in after.context["team_users"]
    assert TeamMemberProfile.objects.get(user=target).role == CRMRole.SALES_MANAGER


def test_role_change_can_return_to_empty_filtered_list(client, usability_operator, django_user_model):
    target = make_accounts(django_user_model, "solo", 1, CRMRole.FINANCE)[0]
    filters = {"q": "solo", "role": CRMRole.FINANCE, "activity": "active"}

    saved = client.post(reverse("core:team_access_update", args=[target.pk]), {
        "role": CRMRole.PROJECT_MANAGER, "return_to": team_url(**filters),
    })

    assert saved.status_code == 302
    response = client.get(saved.url)
    assert_list_context(response, page=1, count=0, query="solo", role=CRMRole.FINANCE, activity="active")
    assert "Пользователи не найдены" in response.content.decode()


def test_cancel_keeps_existing_filtered_page_without_changing_profile(
    client, usability_operator, django_user_model
):
    users = make_accounts(django_user_model, "cancel", 21, CRMRole.FINANCE)
    target = users[-1]
    filters = {"q": "cancel", "role": CRMRole.FINANCE, "activity": "active", "page": 2}

    form = client.get(reverse("core:team_access_update", args=[target.pk]), {"return_to": team_url(**filters)})

    assert form.status_code == 200
    assert parse_qs(urlsplit(form.context["cancel_url"]).query) == {
        key: [str(value)] for key, value in filters.items()
    }
    response = client.get(form.context["cancel_url"])
    assert_list_context(response, page=2, count=21, query="cancel", role=CRMRole.FINANCE, activity="active")
    assert list(response.context["team_users"]) == [target]
    assert TeamMemberProfile.objects.get(user=target).role == CRMRole.FINANCE


def test_out_of_range_team_page_opens_last_available_page(client, usability_operator, django_user_model):
    make_accounts(django_user_model, "page", 21)

    response = client.get(reverse("core:team"), {"q": "page_", "page": 999})

    assert response.status_code == 200
    assert response.context["page_obj"].number == 2
    assert len(response.context["team_users"]) == 1


class DetailsInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "details":
            item = {"attributes": attributes, "labels": set()}
            self.details.append(item)
            self.stack.append(item)
        elif tag == "label" and self.stack:
            self.stack[-1]["labels"].add(attributes.get("for"))

    def handle_endtag(self, tag):
        if tag == "details" and self.stack:
            self.stack.pop()


@pytest.mark.parametrize("params,active", [
    ({}, False), ({"q": "operator"}, False), ({"role": CRMRole.ADMIN}, True), ({"activity": "active"}, True),
])
def test_team_additional_filters_expose_applied_state_and_work_without_javascript(
    client, usability_operator, params, active
):
    response = client.get(reverse("core:team"), params)
    assert response.status_code == 200
    inspector = DetailsInspector()
    inspector.feed(response.content.decode())
    filters = [item for item in inspector.details if {"team-role", "team-activity"} <= item["labels"]]
    assert len(filters) == 1
    assert "open" in filters[0]["attributes"]
    assert filters[0]["attributes"]["data-active"] == str(active).lower()


def test_team_distinguishes_viewing_rights_from_changing_access(client, usability_operator):
    response = client.get(reverse("core:team"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Посмотреть права" in html
    assert "Изменить доступ" in html
