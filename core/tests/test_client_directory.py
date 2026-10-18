from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import CRMRole, Client, Event, Lead, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(client, django_user_model):
    user = django_user_model.objects.create_user(username='client_viewer')
    TeamMemberProfile.objects.create(
        user=user, role=CRMRole.PROJECT_MANAGER, can_view_clients=True,
        can_manage_clients=False, can_manage_system=False, can_view_finance=False,
    )
    client.force_login(user)
    return user


@pytest.mark.parametrize('access', ['anonymous', 'no_profile', 'denied', 'allowed'])
def test_client_detail_requires_client_access(client, django_user_model, access):
    item = Client.objects.create(name='Проверка доступа')
    if access != 'anonymous':
        user = django_user_model.objects.create_user(username=access)
        if access != 'no_profile':
            TeamMemberProfile.objects.create(user=user, role=CRMRole.PROJECT_MANAGER, can_view_clients=access == 'allowed')
        client.force_login(user)
    response = client.get(reverse('core:client_detail', args=[item.pk]))
    assert response.status_code == {'anonymous': 302, 'no_profile': 403, 'denied': 403, 'allowed': 200}[access]
    if access == 'anonymous':
        assert response.url.startswith(reverse('login'))


@pytest.mark.parametrize('finance', [False, True])
def test_client_profile_contains_contacts_context_and_events_without_edit_access(client, viewer, finance):
    viewer.crm_profile.can_view_finance = finance
    viewer.crm_profile.save()
    lead = Lead.objects.create(name='Исходное обращение', manager=viewer)
    item = Client.objects.create(
        name='Компания', lead=lead, phone='+79991234567', email='client@example.com',
        telegram='@person', whatsapp='8 (999) 123-45-67', max_messenger='Имя в MAX',
        instagram='person', facebook='person', vk='person', contacts='Звонить утром',
        messenger='Прежний мессенджер', event_history='Прежняя история', preferences='Без громкой музыки',
        ltv=Decimal('987654.32'),
    )
    event = Event.objects.create(client=item, title='Связанное мероприятие', date=timezone.localdate(), planned_budget=Decimal('7654321.12'))
    html = client.get(reverse('core:client_detail', args=[item.pk])).content.decode()
    for value in ('Звонить утром', 'Прежний мессенджер', 'Прежняя история', 'Без громкой музыки', 'Имя в MAX'):
        assert value in html
    for target in ('tel:+79991234567', 'mailto:client@example.com', 'https://t.me/person', 'https://wa.me/79991234567',
                   'https://instagram.com/person', 'https://facebook.com/person', 'https://vk.com/person',
                   reverse('core:lead_detail', args=[lead.pk]), reverse('core:event_detail', args=[event.pk])):
        assert f'href="{target}"' in html
    assert 'href="Имя в MAX"' not in html
    assert reverse('core:client_update', args=[item.pk]) not in html
    assert reverse('core:client_delete', args=[item.pk]) not in html
    assert ('987\xa0654,32' in html) is finance
    assert ('LTV' in html) is finance
    assert '7654321' not in html
    assert '7\xa0654\xa0321' not in html


def test_client_list_keeps_structured_contacts_visible_over_notes(client, viewer):
    item = Client.objects.create(name='Контакты', phone='+79991112233', email='main@example.com', contacts='Длинная заметка вместо контактов', telegram='@person')
    html = client.get(reverse('core:clients')).content.decode()
    assert 'href="tel:+79991112233"' in html
    assert 'href="mailto:main@example.com"' in html
    assert 'href="https://t.me/person"' in html
    assert item.contacts not in html
    assert reverse('core:client_detail', args=[item.pk]) in html
    assert reverse('core:client_update', args=[item.pk]) not in html
    assert reverse('core:client_delete', args=[item.pk]) not in html


def test_client_filters_combine_and_metrics_cover_whole_database(client, viewer):
    lead = Lead.objects.create(name='Заявка', manager=viewer)
    target = Client.objects.create(name='Целевой', lead=lead, manager=viewer, client_type='b2b', segment='vip')
    Client.objects.create(name='Целевой частный', client_type='b2c', segment='vip')
    Client.objects.create(name='Другой', client_type='b2b', segment='standard')
    response = client.get(reverse('core:clients'), {'q': 'целевой', 'client_type': 'b2b', 'segment': 'vip', 'manager': viewer.pk})
    assert list(response.context['clients']) == [target]
    assert response.context['paginator'].count == 1
    assert response.context['client_metrics'] == {'total': 3, 'companies': 2, 'individuals': 1, 'vip': 2}
    assert 'Ответственный' in response.content.decode()


def test_unassigned_filter_uses_client_assignment_independently_of_lead(client, viewer):
    manual = Client.objects.create(name='Вручную')
    free_lead = Lead.objects.create(name='Без менеджера')
    Lead.objects.filter(pk=free_lead.pk).update(manager=None)
    unassigned = Client.objects.create(name='Из свободного лида', lead=free_lead)
    assigned_lead = Lead.objects.create(name='Назначен', manager=viewer)
    Client.objects.create(name='Назначенный клиент', lead=assigned_lead, manager=viewer)
    response = client.get(reverse('core:clients'), {'manager': 'unassigned'})
    assert set(response.context['clients']) == {manual, unassigned}


def test_client_sort_by_real_event_count(client, viewer):
    first = Client.objects.create(name='Альфа')
    second = Client.objects.create(name='Бета')
    Event.objects.create(client=second, title='Мероприятие', date=timezone.localdate())
    response = client.get(reverse('core:clients'), {'sort': 'events'})
    assert list(response.context['clients']) == [second, first]
    assert response.context['clients'][0].events_count == 1


def test_client_pagination_keeps_filters_and_stable_order(client, viewer):
    Client.objects.bulk_create([Client(name='Одинаковое имя', client_type='b2b', segment='vip') for _ in range(21)])
    params = {'q': 'одинаковое', 'client_type': 'b2b', 'segment': 'vip', 'manager': 'unassigned', 'sort': 'name'}
    first = client.get(reverse('core:clients'), params)
    second = client.get(reverse('core:clients'), dict(params, page=2))
    assert first.context['paginator'].count == 21
    assert len(first.context['clients']) == 20
    assert len(second.context['clients']) == 1
    assert set(first.context['clients']).isdisjoint(second.context['clients'])
    query = second.context['pagination_query']
    for value in ('client_type=b2b', 'segment=vip', 'manager=unassigned', 'sort=name'):
        assert value in query
    assert 'page=' not in query
    assert query.replace('&', '&amp;') in second.content.decode()


@pytest.mark.parametrize('query', ['+79991234567', '8 (999) 123-45-67', '9991234567', 'ИВАН', '@online'])
def test_client_search_handles_phone_format_cyrillic_and_channels(client, viewer, query):
    target = Client.objects.create(name='Иван', phone='+7 (999) 123-45-67', telegram='@online')
    Client.objects.create(name='Другой', phone='+78881234567')
    assert list(client.get(reverse('core:clients'), {'q': query}).context['clients']) == [target]
    results = client.get(reverse('core:client_autocomplete'), {'q': query}).json()['results']
    assert [item['id'] for item in results] == [target.pk]
    assert results[0]['url'] == reverse('core:client_detail', args=[target.pk])


def test_client_autocomplete_is_limited_and_not_cached(client, viewer):
    Client.objects.bulk_create([Client(name=f'Подсказка {index:02}') for index in range(10)])
    response = client.get(reverse('core:client_autocomplete'), {'q': 'подсказка'})
    assert len(response.json()['results']) == 8
    assert response['Cache-Control'] == 'no-store'
    assert client.get(reverse('core:client_autocomplete'), {'q': 'п'}).json() == {'results': []}


def test_client_names_and_contact_notes_are_escaped_in_html(client, viewer):
    value = '<img src=x onerror=alert(1)>'
    item = Client.objects.create(name=value, contacts=value)
    for url in (reverse('core:clients'), reverse('core:client_detail', args=[item.pk])):
        html = client.get(url).content.decode()
        assert value not in html
        assert '&lt;img' in html
    assert client.get(reverse('core:client_autocomplete'), {'q': '<img'}).json()['results'][0]['name'] == value


def test_empty_database_and_empty_filtered_result_have_different_guidance(client, viewer):
    assert 'Клиентов пока нет' in client.get(reverse('core:clients')).content.decode()
    Client.objects.create(name='Существующий')
    html = client.get(reverse('core:clients'), {'q': 'не найден'}).content.decode()
    assert 'Клиенты не найдены' in html
    assert 'Сбросить фильтры' in html


def test_create_edit_and_cancel_return_to_client_profile(client, viewer):
    viewer.crm_profile.can_manage_clients = True
    viewer.crm_profile.save()
    payload = {'creation_mode': 'manual', 'name': 'Новый', 'client_type': 'b2c', 'segment': 'standard'}
    response = client.post(reverse('core:client_create'), payload)
    item = Client.objects.get(name='Новый')
    detail_url = reverse('core:client_detail', args=[item.pk])
    assert response.url == detail_url
    edit_url = reverse('core:client_update', args=[item.pk])
    assert client.get(edit_url).context['cancel_url'] == detail_url
    response = client.post(edit_url, dict(payload, name='Изменённый'))
    assert response.url == detail_url
    item.refresh_from_db()
    assert item.name == 'Изменённый'


def test_unknown_sort_and_filters_use_safe_defaults(client, viewer):
    item = Client.objects.create(name='Тест')
    response = client.get(reverse('core:clients'), {'sort': '-ltv', 'segment': 'bad', 'client_type': 'bad', 'manager': 'bad'})
    assert response.status_code == 200
    assert list(response.context['clients']) == [item]
    assert response.context['client_sort'] == 'name'
    assert not response.context['has_filters']
