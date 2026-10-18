import pytest
from django.urls import reverse

from core.forms import ClientForm
from core.models import CRMRole, Client, Lead, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, django_user_model):
    users = []
    for username, full_name in [('operator', 'Оператор'), ('first_manager', 'Первый менеджер'), ('second_manager', 'Второй менеджер')]:
        user = django_user_model.objects.create_user(username=username, first_name=full_name)
        TeamMemberProfile.objects.create(user=user, role=CRMRole.PROJECT_MANAGER, can_view_clients=True, can_manage_clients=True)
        users.append(user)
    client.force_login(users[0])
    return users


@pytest.fixture
def payload():
    return {'creation_mode': 'manual', 'name': 'Новый клиент', 'client_type': 'b2c', 'segment': 'standard'}


@pytest.mark.parametrize('manager_value', [None, ''])
def test_client_created_from_lead_copies_manager_without_javascript(client, staff, payload, manager_value):
    _, first, second = staff
    lead = Lead.objects.create(name='Исходный лид', manager=first)
    prefilled = client.get(reverse('core:client_create'), {'lead': lead.pk}).context['form']
    assert prefilled['manager'].value() == first.pk
    data = dict(payload, creation_mode='lead', lead=lead.pk)
    if manager_value is not None:
        data['manager'] = manager_value
    response = client.post(reverse('core:client_create'), data)
    assert response.status_code == 302
    saved = Client.objects.get(lead=lead)
    assert saved.manager == first
    lead.manager = second
    lead.save()
    saved.refresh_from_db()
    assert saved.manager == first


@pytest.mark.parametrize('clear', [False, True])
def test_explicit_choice_overrides_inherited_manager(client, staff, payload, clear):
    _, first, second = staff
    lead = Lead.objects.create(name='Лид', manager=first)
    response = client.post(reverse('core:client_create'), dict(
        payload, creation_mode='lead', lead=lead.pk,
        manager='' if clear else second.pk, manager_selection_changed='true',
    ))
    assert response.status_code == 302
    assert Client.objects.get(lead=lead).manager_id == (None if clear else second.pk)
    lead.refresh_from_db()
    assert lead.manager == first


@pytest.mark.parametrize('assigned', [False, True])
def test_manual_creation_can_assign_or_leave_empty_without_using_stale_lead(client, staff, payload, assigned):
    _, first, second = staff
    lead = Lead.objects.create(name='Не выбран', manager=first)
    response = client.post(reverse('core:client_create'), dict(payload, lead=lead.pk, manager=second.pk if assigned else ''))
    assert response.status_code == 302
    saved = Client.objects.get()
    assert saved.lead is None
    assert saved.manager_id == (second.pk if assigned else None)


@pytest.mark.parametrize('manager_choice', ['keep', 'change', 'clear'])
def test_editing_lead_and_other_data_does_not_override_client_manager(client, staff, payload, manager_choice):
    _, first, second = staff
    lead = Lead.objects.create(name='Новый исходный лид', manager=first)
    item = Client.objects.create(name='Клиент', manager=second)
    chosen_id = {'keep': second.pk, 'change': first.pk, 'clear': ''}[manager_choice]
    response = client.post(reverse('core:client_update', args=[item.pk]), dict(payload, lead=lead.pk, manager=chosen_id))
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.lead == lead
    assert item.manager_id == (chosen_id or None)
    lead.refresh_from_db()
    assert lead.manager == first


@pytest.mark.parametrize('clear', [False, True])
def test_failed_validation_preserves_explicit_manager_choice(client, staff, payload, clear):
    _, first, second = staff
    lead = Lead.objects.create(name='Лид', manager=first)
    data = dict(payload, creation_mode='lead', lead=lead.pk, manager='' if clear else second.pk,
                manager_selection_changed='true', email='invalid')
    response = client.post(reverse('core:client_create'), data)
    assert response.status_code == 200
    form = response.context['form']
    assert form['manager'].value() == ('' if clear else str(second.pk))
    assert form['manager_selection_changed'].value() == 'true'
    assert not Client.objects.exists()
    response = client.post(reverse('core:client_create'), dict(data, email='valid@example.com'))
    assert response.status_code == 302
    assert Client.objects.get().manager_id == (None if clear else second.pk)


@pytest.mark.parametrize('invalid_manager', ['inactive', 'no_profile', 'missing'])
def test_new_assignments_reject_invalid_employees(client, staff, payload, django_user_model, invalid_manager):
    if invalid_manager == 'missing':
        manager_id = 999999
    else:
        user = django_user_model.objects.create_user(username=invalid_manager, is_active=invalid_manager != 'inactive')
        manager_id = user.pk
        if invalid_manager == 'inactive':
            TeamMemberProfile.objects.create(user=user, role=CRMRole.PROJECT_MANAGER)
    response = client.post(reverse('core:client_create'), dict(payload, manager=manager_id))
    assert response.status_code == 200
    assert 'manager' in response.context['form'].errors
    assert not Client.objects.exists()


def test_existing_inactive_manager_can_be_preserved_or_replaced(client, staff, payload):
    _, first, second = staff
    first.is_active = False
    first.save()
    item = Client.objects.create(name='Клиент', manager=first)
    assert first not in ClientForm().fields['manager'].queryset
    assert first in ClientForm(instance=item).fields['manager'].queryset
    url = reverse('core:client_update', args=[item.pk])
    assert client.post(url, dict(payload, manager=first.pk)).status_code == 302
    item.refresh_from_db()
    assert item.manager == first
    assert client.post(url, dict(payload, manager=second.pk)).status_code == 302
    item.refresh_from_db()
    assert item.manager == second


@pytest.mark.parametrize('flag', ['can_view_clients', 'can_manage_clients'])
def test_manager_assignment_requires_client_management_permissions(client, staff, payload, flag):
    operator, first, second = staff
    setattr(operator.crm_profile, flag, False)
    operator.crm_profile.save()
    item = Client.objects.create(name='Существующий', manager=first)
    assert client.post(reverse('core:client_update', args=[item.pk]), dict(payload, manager=second.pk)).status_code == 403
    assert client.post(reverse('core:client_create'), dict(payload, manager=second.pk)).status_code == 403
    item.refresh_from_db()
    assert item.manager == first
    assert Client.objects.count() == 1


def test_filters_and_profiles_show_client_manager_instead_of_lead_manager(client, staff):
    _, first, second = staff
    lead = Lead.objects.create(name='Исходный лид', manager=first)
    different = Client.objects.create(name='Другой ответственный', lead=lead, manager=second)
    manual = Client.objects.create(name='Без исходного лида', manager=second)
    free = Client.objects.create(name='Без ответственного')
    url = reverse('core:clients')
    response = client.get(url, {'manager': second.pk})
    assert set(response.context['clients']) == {different, manual}
    assert list(response.context['client_managers']) == [second]
    assert first.get_full_name() not in response.content.decode()
    assert second.get_full_name() in response.content.decode()
    assert list(client.get(url, {'manager': first.pk}).context['clients']) == []
    assert list(client.get(url, {'manager': 'unassigned'}).context['clients']) == [free]
    html = client.get(reverse('core:client_detail', args=[different.pk])).content.decode()
    assert second.get_full_name() in html
    assert first.get_full_name() not in html
    assert 'Ответственный менеджер' in html


@pytest.mark.parametrize('eligible', [False, True])
def test_lead_endpoint_exposes_only_eligible_default_manager(client, staff, payload, eligible):
    _, first, _ = staff
    first.is_active = eligible
    first.save()
    lead = Lead.objects.create(name='Лид', manager=first)
    response = client.get(reverse('core:client_lead_data'), {'lead_id': lead.pk})
    assert response.json()['manager_id'] == (first.pk if eligible else None)
    response = client.post(reverse('core:client_create'), dict(payload, creation_mode='lead', lead=lead.pk))
    assert response.status_code == 302
    assert Client.objects.get(lead=lead).manager_id == (first.pk if eligible else None)


def test_deleting_manager_leaves_client_without_assignment(staff):
    _, first, _ = staff
    item = Client.objects.create(name='Клиент', manager=first)
    first.delete()
    item.refresh_from_db()
    assert item.manager is None
