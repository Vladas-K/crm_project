from core.forms import EventExpenseForm, EventForm


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
