from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

from core.models import TeamMemberProfile, Vendor
from core.views import safe_vendor_return_url, vendor_profile_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def vendor_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username="vendor_navigation")
    TeamMemberProfile.objects.create(user=user, can_manage_system=True, can_view_finance=True)
    client.force_login(user)
    return user


def vendor_data(**changes):
    data = {"name": "Исполнитель", "min_cost": "0", "avg_cost": "0", "rating": "4", "reliability": "90"}
    data.update(changes)
    return data


@pytest.mark.parametrize("value", ["https://evil.example/vendors/", "//evil.example/vendors/", "/tasks/", "/vendors/../tasks/", r"/vendors/\evil", "http://["])
def test_vendor_return_rejects_unrelated_targets(value):
    assert safe_vendor_return_url(value) is None


def test_vendor_return_normalizes_supported_parameters():
    value = "/vendors/?q=  Свет &role=002&event_format=3&blacklisted=no&sort=rating&next=https://evil.example"
    url = safe_vendor_return_url(value)
    assert urlsplit(url).path == "/vendors/"
    assert parse_qs(urlsplit(url).query) == {"q": ["Свет"], "role": ["2"], "event_format": ["3"], "blacklisted": ["no"], "sort": ["rating"]}


def test_catalog_and_profile_preserve_filters(client, vendor_operator, crm_objects):
    vendor = crm_objects["vendor"]
    response = client.get(reverse("core:vendors"), {"q": vendor.name, "sort": "rating", "blacklisted": "no"})
    origin = response.context["vendor_return_url"]
    assert parse_qs(urlsplit(origin).query)["q"] == [vendor.name]
    assert response.context["vendor_extra_filters_active"]
    assert vendor_profile_url(vendor.pk, origin) in unescape(response.content.decode())
    profile = client.get(vendor_profile_url(vendor.pk, origin))
    assert profile.context["vendor_return_url"] == origin
    assert 'aria-current="page">Подрядчики</a>' in profile.content.decode()
    form = client.get(reverse("core:vendor_update", args=[vendor.pk]), {"return_to": origin})
    assert form.context["cancel_url"] == vendor_profile_url(vendor.pk, origin)
    assert 'name="return_to"' in form.content.decode()
    assert 'aria-current="page">Подрядчики</a>' in form.content.decode()


@pytest.mark.parametrize("editing", [False, True])
def test_vendor_save_opens_profile_and_errors_keep_context(client, vendor_operator, crm_objects, editing):
    vendor = crm_objects["vendor"]
    origin = "/vendors/?blacklisted=no&sort=reliability"
    url = reverse("core:vendor_update", args=[vendor.pk]) if editing else reverse("core:vendor_create")
    invalid = client.post(url, vendor_data(name="", return_to=origin))
    assert invalid.status_code == 200
    assert invalid.context["return_to"] == origin
    assert invalid.context["cancel_url"] == (vendor_profile_url(vendor.pk, origin) if editing else origin)
    saved = client.post(url, vendor_data(return_to=origin))
    assert saved.status_code == 302, getattr(saved, "context", None) and saved.context["form"].errors
    saved_vendor = Vendor.objects.get(name="Исполнитель")
    assert saved.url == vendor_profile_url(saved_vendor.pk, origin)
    assert client.get(saved.url).context["vendor_return_url"] == origin


def test_vendor_delete_preserves_list_context(client, vendor_operator, crm_objects):
    vendor = crm_objects["vendor"]
    origin = "/vendors/?q=Свет&sort=rating"
    url = reverse("core:vendor_delete", args=[vendor.pk])
    confirmation = client.get(url, {"return_to": origin})
    normalized = safe_vendor_return_url(origin)
    assert confirmation.context["cancel_url"] == vendor_profile_url(vendor.pk, normalized)
    assert 'name="return_to"' in confirmation.content.decode()
    response = client.post(url, {"return_to": origin})
    assert response.url == normalized
    assert not Vendor.objects.filter(pk=vendor.pk).exists()


def test_vendor_invalid_origin_falls_back_to_catalog(client, vendor_operator, crm_objects):
    vendor = crm_objects["vendor"]
    response = client.post(reverse("core:vendor_update", args=[vendor.pk]), vendor_data(return_to="https://evil.example/"))
    assert response.url == vendor_profile_url(vendor.pk, "/vendors/")


def test_vendor_navigation_does_not_grant_mutation_permission(client, vendor_operator, crm_objects):
    vendor_operator.crm_profile.can_manage_system = False
    vendor_operator.crm_profile.save()
    response = client.post(reverse("core:vendor_update", args=[crm_objects["vendor"].pk]), vendor_data(return_to="/vendors/"))
    assert response.status_code == 403


def test_financial_sort_is_not_kept_without_financial_access(client, vendor_operator):
    vendor_operator.crm_profile.can_view_finance = False
    vendor_operator.crm_profile.save()
    response = client.get(reverse("core:vendors"), {"sort": "cost", "role": "9" * 100})
    assert response.status_code == 200
    assert response.context["vendor_sort"] == "name"
    assert response.context["vendor_return_url"] == "/vendors/"
    assert not response.context["vendor_extra_filters_active"]
