from datetime import time
from io import BytesIO

from pypdf import PdfReader

import pytest
from django.urls import reverse

from core.models import Event, EventTimelineItem
from core.tests.test_event_workflow import login_user

pytestmark = pytest.mark.django_db


def test_download_requires_login(client, crm_objects):
    url = reverse("core:event_timeline_download", args=[crm_objects["event"].pk])
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/?next=")


def test_download_contains_only_selected_event_and_agreed_fields(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=False, can_view_finance=False)
    event = crm_objects["event"]
    event.title = "Название для печати"
    event.save()
    # Создаём не по времени: печатная программа должна быть хронологической.
    EventTimelineItem.objects.create(event=event, time="19:00", block="Вечерний блок",
                                     description="Первая строка\n<script>опасный текст</script>",
                                     responsible="Координатор мероприятия", responsible_phone="+7 911 123-45-67")
    EventTimelineItem.objects.create(event=event, time="09:00", block="Первый утренний блок")
    EventTimelineItem.objects.create(event=event, time="09:00", block="Второй утренний блок")
    other = Event.objects.create(client=event.client, date=event.date, city=event.city)
    EventTimelineItem.objects.create(event=other, time="08:00", block="Чужое мероприятие")
    response = client.get(reverse("core:event_timeline_download", args=[event.pk]))
    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'
    assert response['Content-Disposition'].startswith('attachment;')
    assert f'Dievent-timeline-{event.date:%Y-%m-%d}-{event.pk}.pdf' in response['Content-Disposition']
    data = b''.join(response.streaming_content)
    assert data.startswith(b'%PDF-')
    pdf = PdfReader(BytesIO(data))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    text = ' '.join(text.split())
    assert 'Dievent' in text and event.title in text
    assert event.date.strftime('%d.%m.%Y') in text
    assert text.index('Первый утренний блок') < text.index('Второй утренний блок') < text.index('Вечерний блок')
    assert '09:00' in text and '19:00' in text
    assert '<script>опасный текст</script>' in text
    assert 'Ответственный' in text and 'Координатор мероприятия' in text and '+7 911 123-45-67' in text
    for value in ('Чужое мероприятие', 'Плановый бюджет', 'Выйти', 'Изменить', 'Удалить'):
        assert value not in text
    assert float(pdf.pages[0].mediabox.width) == pytest.approx(595.28, abs=.1)
    assert float(pdf.pages[0].mediabox.height) == pytest.approx(841.89, abs=.1)


def test_download_empty_and_missing_event(client, django_user_model, crm_objects):
    login_user(client, django_user_model)
    event = crm_objects['event']
    response = client.get(reverse('core:event_timeline_download', args=[event.pk]))
    pdf = PdfReader(BytesIO(b''.join(response.streaming_content)))
    assert 'Блоки тайминга ещё не добавлены' in pdf.pages[0].extract_text()
    assert client.get(reverse('core:event_timeline_download', args=[999999])).status_code == 404


def test_pdf_splits_oversized_rows_and_repeats_headers(client, django_user_model, crm_objects):
    login_user(client, django_user_model)
    event = crm_objects['event']
    EventTimelineItem.objects.create(event=event, time='10:00', block='Очень длинный блок',
        description='\n'.join(f'Строка {i}: Подготовка площадки и проверка оборудования.' for i in range(150)))
    EventTimelineItem.objects.create(event=event, time='23:00', block='Последний блок', description='Конец программы')
    response = client.get(reverse('core:event_timeline_download', args=[event.pk]))
    pdf = PdfReader(BytesIO(b''.join(response.streaming_content)))
    assert len(pdf.pages) > 2
    for page in pdf.pages:
        assert 'Блок программы' in page.extract_text()
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'Строка 149:' in text and 'Последний блок' in text and 'Конец программы' in text


def test_timeline_has_single_download_action(client, django_user_model, crm_objects):
    login_user(client, django_user_model)
    response = client.get(reverse('core:event_detail', args=[crm_objects['event'].pk]), {'tab': 'timeline'})
    html = response.content.decode()
    assert html.count('>Скачать PDF</a>') == 1
    assert 'Печать / PDF' not in html and 'window.print' not in html


def test_timeline_edit_locks_event_and_preserves_filters(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects["event"]
    other = Event.objects.create(client=event.client, date=event.date, city=event.city)
    item = EventTimelineItem.objects.create(event=event, time="09:00", block="Сбор")
    url = reverse("core:event_timeline_update", args=[item.pk])
    response = client.get(url, {"event_filters": "vendor_filter=approved"})
    assert "core/timeline_form.html" in [template.name for template in response.templates]
    assert response.context["form"].fields["event"].disabled
    assert 'vendor_filter=approved' in response.context["cancel_url"]
    response = client.post(url, {"event": other.pk, "time": "10:30", "block": "Открытие",
                                 "event_filters": "vendor_filter=approved"})
    assert response.status_code == 302
    assert "tab=timeline" in response.url and "vendor_filter=approved" in response.url
    item.refresh_from_db()
    assert item.event_id == event.pk and item.time == time(10, 30)


def test_timeline_create_rejects_invalid_time_and_keeps_parent(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects["event"]
    other = Event.objects.create(client=event.client, date=event.date, city=event.city)
    url = reverse("core:event_timeline_create", args=[event.pk])
    response = client.post(url, {"event": other.pk, "time": "25:71", "block": ""})
    form = response.context["form"]
    assert response.status_code == 200
    assert "time" in form.errors and "block" in form.errors
    html = response.content.decode()
    assert 'aria-invalid="true"' in html and 'id_time_error' in html
    assert "id_time_helptext id_time_error" in html
    assert not EventTimelineItem.objects.filter(event=event).exists()
    response = client.post(url, {"event": other.pk, "time": "00:00", "block": "Старт"})
    assert response.status_code == 302
    assert event.timeline_items.get().time == time(0, 0)


def test_timeline_form_denies_changes_without_event_permission(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=False)
    event = crm_objects["event"]
    url = reverse("core:event_timeline_create", args=[event.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {"time": "10:00", "block": "Недоступно"}).status_code == 403
