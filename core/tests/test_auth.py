import pytest
from django.urls import reverse


def assert_login_required(client, url, method="get"):
    response = getattr(client, method)(url)

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('login')}?next={url}"


def test_public_login_page_is_available(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    "url_name",
    [
        "dashboard",
        "leads",
        "pipeline",
        "clients",
        "events",
        "tasks",
        "formats",
        "vendors",
        "packages",
        "calendar",
        "analytics",
        "team",
    ],
)
def test_list_and_dashboard_views_require_login(client, url_name):
    assert_login_required(client, reverse(f"core:{url_name}"))


def test_detail_and_form_views_require_login(client, crm_objects):
    urls = [
        reverse("core:lead_create"),
        reverse("core:lead_update", kwargs={"pk": crm_objects["lead"].pk}),
        reverse("core:lead_delete", kwargs={"pk": crm_objects["lead"].pk}),
        reverse("core:pipeline_create"),
        reverse("core:pipeline_update", kwargs={"pk": crm_objects["stage"].pk}),
        reverse("core:pipeline_delete", kwargs={"pk": crm_objects["stage"].pk}),
        reverse("core:client_create"),
        reverse("core:client_update", kwargs={"pk": crm_objects["client"].pk}),
        reverse("core:client_delete", kwargs={"pk": crm_objects["client"].pk}),
        reverse("core:event_create"),
        reverse("core:event_detail", kwargs={"pk": crm_objects["event"].pk}),
        reverse("core:event_update", kwargs={"pk": crm_objects["event"].pk}),
        reverse("core:event_delete", kwargs={"pk": crm_objects["event"].pk}),
        reverse("core:event_task_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_expense_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_vendor_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_communication_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:event_document_create", kwargs={"event_pk": crm_objects["event"].pk}),
        reverse("core:task_create"),
        reverse("core:task_detail", kwargs={"pk": crm_objects["task"].pk}),
        reverse("core:task_update", kwargs={"pk": crm_objects["task"].pk}),
        reverse("core:task_delete", kwargs={"pk": crm_objects["task"].pk}),
        reverse("core:event_expense_update", kwargs={"pk": crm_objects["expense"].pk}),
        reverse("core:event_vendor_update", kwargs={"pk": crm_objects["event_vendor"].pk}),
        reverse("core:event_communication_update", kwargs={"pk": crm_objects["communication"].pk}),
        reverse("core:event_document_update", kwargs={"pk": crm_objects["document"].pk}),
        reverse("core:format_create"),
        reverse("core:format_update", kwargs={"pk": crm_objects["event_format"].pk}),
        reverse("core:format_delete", kwargs={"pk": crm_objects["event_format"].pk}),
        reverse("core:vendor_create"),
        reverse("core:vendor_update", kwargs={"pk": crm_objects["vendor"].pk}),
        reverse("core:vendor_delete", kwargs={"pk": crm_objects["vendor"].pk}),
        reverse("core:package_create"),
        reverse("core:package_update", kwargs={"pk": crm_objects["service_package"].pk}),
        reverse("core:package_delete", kwargs={"pk": crm_objects["service_package"].pk}),
    ]

    for url in urls:
        assert_login_required(client, url)


@pytest.mark.parametrize(
    ("route_name", "object_key"),
    [
        ("task_status_update", "task"),
        ("event_vendor_status_update", "event_vendor"),
    ],
)
def test_status_action_views_require_login(client, crm_objects, route_name, object_key):
    url = reverse(f"core:{route_name}", kwargs={"pk": crm_objects[object_key].pk})

    assert_login_required(client, url, method="post")
