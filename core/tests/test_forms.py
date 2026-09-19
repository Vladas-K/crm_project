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
        "social_links",
        "service_area",
        "preferred_contact_method",
    }.issubset(form.fields)


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
