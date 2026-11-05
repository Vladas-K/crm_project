import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.forms import EventTimelineItemForm
from core.models import Event, EventTimelineItem, EventVendor, Vendor
from core.tests.test_event_workflow import login_user

pytestmark = pytest.mark.django_db


def test_assigned_vendor_supplies_contact_without_javascript(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects['event']
    assignment = crm_objects['event_vendor']
    assignment.vendor.contact_person = 'Ирина Координатор'
    assignment.vendor.phone = '8 (911) 123-45-67'
    assignment.vendor.save()
    response = client.get(reverse('core:event_timeline_create', args=[event.pk]))
    form = response.context['form']
    assert list(form.fields['responsible_vendor'].queryset) == [assignment]
    assert form.responsible_contacts[str(assignment.pk)]['name'] == 'Ирина Координатор'
    response = client.post(reverse('core:event_timeline_create', args=[event.pk]), {
        'time': '10:00', 'block': 'Встреча гостей', 'responsible_vendor': assignment.pk,
        'responsible': 'Подменённое имя', 'responsible_phone': '+0',
    })
    assert response.status_code == 302
    item = event.timeline_items.get()
    assert item.responsible_vendor == assignment
    assert item.responsible == 'Ирина Координатор'
    assert item.responsible_phone == '+7 (911) 123-45-67'


def test_manual_contact_without_vendors_does_not_create_catalog_record(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects['event']
    event.event_vendors.all().delete()
    vendor_count = Vendor.objects.count()
    url = reverse('core:event_timeline_create', args=[event.pk])
    response = client.get(url)
    assert not response.context['form'].has_responsible_vendors
    assert 'Укажите имя и телефон вручную' in response.content.decode()
    response = client.post(url, {'time': '11:00', 'block': 'Запуск', 'responsible': 'Александр',
                                 'responsible_phone': '89111234567'})
    assert response.status_code == 302
    item = event.timeline_items.get()
    assert item.responsible_vendor is None
    assert item.responsible == 'Александр' and item.responsible_phone == '+79111234567'
    assert Vendor.objects.count() == vendor_count


def test_vendor_from_other_event_cannot_be_posted_or_selected(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects['event']
    other = Event.objects.create(client=event.client, date=event.date, city=event.city)
    outsider = EventVendor.objects.create(event=other, vendor=crm_objects['vendor'], role='Ведущий')
    url = reverse('core:event_timeline_create', args=[event.pk])
    response = client.post(url, {'event': other.pk, 'time': '12:00', 'block': 'Проверка',
                                 'responsible_vendor': outsider.pk})
    assert response.status_code == 200
    assert 'responsible_vendor' in response.context['form'].errors
    assert not event.timeline_items.exists()
    with pytest.raises(ValidationError, match='Выберите подрядчика этого мероприятия'):
        EventTimelineItem(event=event, time='12:00', block='Проверка', responsible_vendor=outsider).full_clean()


def test_contact_falls_back_to_vendor_name_and_survives_assignment_deletion(crm_objects):
    event = crm_objects['event']
    assignment = crm_objects['event_vendor']
    assignment.vendor.contact_person = ''
    assignment.vendor.phone = '+79111234567'
    assignment.vendor.save()
    form = EventTimelineItemForm(initial={'event': event}, data={
        'event': event.pk, 'time': '12:00', 'block': 'Программа', 'responsible_vendor': assignment.pk,
    })
    assert form.is_valid(), form.errors
    item = form.save()
    assert item.responsible == assignment.vendor.name
    assignment.delete()
    item.refresh_from_db()
    assert item.responsible_vendor is None
    assert item.responsible == assignment.vendor.name and item.responsible_phone == '+79111234567'


def test_switching_to_manual_keeps_edits_and_original_event(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_manage_events=True)
    event = crm_objects['event']
    item = EventTimelineItem.objects.create(event=event, time='10:00', block='Открытие',
        responsible_vendor=crm_objects['event_vendor'], responsible='Прежнее имя', responsible_phone='+79110000000')
    response = client.post(reverse('core:event_timeline_update', args=[item.pk]), {
        'time': '10:15', 'block': 'Открытие', 'responsible_vendor': '',
        'responsible': 'Другой координатор', 'responsible_phone': '+79990000000',
    })
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.event_id == event.pk and item.responsible_vendor_id is None
    assert item.responsible == 'Другой координатор' and item.responsible_phone == '+79990000000'


def test_previous_manual_name_is_preserved(crm_objects):
    event = crm_objects['event']
    item = EventTimelineItem.objects.create(event=event, time='10:00', block='Старый блок', responsible='Продюсер')
    form = EventTimelineItemForm(instance=item, data={'time': '10:30', 'block': 'Старый блок', 'responsible': 'Продюсер'})
    assert form.is_valid(), form.errors
    form.save()
    item.refresh_from_db()
    assert item.responsible == 'Продюсер' and not item.responsible_phone
