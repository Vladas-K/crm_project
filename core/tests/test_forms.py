from core.forms import EventForm


def test_event_form_preserves_event_date_in_date_input(crm_objects):
    """Форма редактирования мероприятия показывает сохранённую дату."""
    event = crm_objects["event"]

    rendered_date = EventForm(instance=event)["date"].as_widget()

    assert f'value="{event.date:%Y-%m-%d}"' in rendered_date
    assert f'value="{event.date:%d.%m.%Y}"' not in rendered_date
