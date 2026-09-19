import pytest

from core.forms import EventExpenseForm, EventForm, EventVendorForm, VendorForm
from core.models import VendorRole


def test_event_form_preserves_event_date_in_date_input(crm_objects):
    """Форма редактирования мероприятия показывает сохранённую дату."""
    event = crm_objects["event"]

    rendered_date = EventForm(instance=event)["date"].as_widget()

    assert f'value="{event.date:%Y-%m-%d}"' in rendered_date
    assert f'value="{event.date:%d.%m.%Y}"' not in rendered_date


def test_expense_form_uses_linked_vendor_assignment(crm_objects):
    """Форма расхода использует назначенного подрядчика вместо свободного текста."""

    form = EventExpenseForm()

    assert "vendor_assignment" in form.fields
    assert "vendor_name" not in form.fields


@pytest.mark.django_db
def test_event_vendor_form_renders_role_as_select():
    """Форма назначения подрядчика показывает роль как выпадающий список."""

    VendorRole.objects.create(name="Техника")

    form = EventVendorForm()

    assert form.fields["role"].widget.__class__.__name__ == "Select"
    assert form.fields["role"].choices[0] == ("", "Сначала выберите подрядчика")


@pytest.mark.django_db
def test_vendor_role_is_normalized_with_uppercase_first_letter():
    """Новая роль подрядчика сохраняется с заглавной первой буквой."""

    role = VendorRole.objects.create(name="  видеограф  ")

    assert role.name == "Видеограф"


@pytest.mark.django_db
def test_vendor_form_contains_structured_contact_fields():
    """Форма подрядчика показывает отдельные поля для основных каналов связи."""

    form = VendorForm()

    assert {
        "contact_person",
        "contact_position",
        "phone",
        "email",
        "website",
        "telegram",
        "whatsapp",
        "max_messenger",
        "instagram",
        "vk",
        "social_links",
        "service_area",
        "preferred_contact_method",
    }.issubset(form.fields)
    assert form.fields["phone"].widget.attrs["data-russian-phone"] == "true"
    assert form.fields["website"].widget.attrs["data-website-url"] == "true"


@pytest.mark.django_db
def test_vendor_form_normalizes_phone_starting_with_eight():
    """Форма заменяет начальную восьмёрку российского номера на +7."""

    form = VendorForm(
        data={
            "name": "Phone Team",
            "phone": "8 (999) 123-45-67",
            "min_cost": 0,
            "avg_cost": 0,
            "rating": 0,
            "reliability": 0,
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone"] == "+7 (999) 123-45-67"


@pytest.mark.django_db
def test_vendor_form_adds_https_to_website_without_scheme():
    """Форма дополняет адрес сайта безопасной схемой, если она не указана."""

    form = VendorForm(
        data={
            "name": "Web Team",
            "website": "example.com/portfolio",
            "min_cost": 0,
            "avg_cost": 0,
            "rating": 0,
            "reliability": 0,
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["website"] == "https://example.com/portfolio"


@pytest.mark.django_db
def test_vendor_form_rejects_social_link_without_scheme():
    """Ссылки на соцсети должны быть полными и безопасными для отображения."""

    form = VendorForm(
        data={
            "name": "Media Team",
            "social_links": "instagram.com/media-team",
            "min_cost": 0,
            "avg_cost": 0,
            "rating": 0,
            "reliability": 0,
        }
    )

    assert not form.is_valid()
    assert "social_links" in form.errors
