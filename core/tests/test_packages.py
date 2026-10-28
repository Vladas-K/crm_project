from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from core.forms import ServicePackageForm
from core.models import EventFormat, ServicePackage, TeamMemberProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def package_operator(client, django_user_model):
    user = django_user_model.objects.create_user(username='package_operator')
    TeamMemberProfile.objects.create(user=user, can_manage_system=True)
    client.force_login(user)
    return user


@pytest.mark.parametrize('price,valid', [('-0.01', False), ('0', True), ('980000.50', True)])
def test_package_price_form_validation(crm_objects, price, valid):
    form = ServicePackageForm({'name': 'Пакет', 'event_format': crm_objects['event_format'].pk, 'services': 'Свет\nЗвук', 'price': price})
    assert form.is_valid() is valid
    if not valid:
        assert 'price' in form.errors


def test_negative_package_price_is_rejected_by_model_and_database(crm_objects):
    package = ServicePackage(name='Недопустимая цена', event_format=crm_objects['event_format'], services='Свет', price=Decimal('-1'))
    with pytest.raises(ValidationError):
        package.full_clean()
    with transaction.atomic(), pytest.raises(IntegrityError):
        package.save()


def test_format_deletion_is_protected_and_explained(client, package_operator, crm_objects):
    event_format = crm_objects['event_format']
    package = ServicePackage.objects.create(name='Связанный пакет', event_format=event_format, services='Свет', price=0)
    with pytest.raises(ProtectedError):
        event_format.delete()
    url = reverse('core:format_delete', args=[event_format.pk])
    for response in (client.get(url), client.post(url)):
        assert response.status_code == 200
        html = response.content.decode()
        assert 'используется в пакетах' in html
        assert reverse('core:package_update', args=[package.pk]) in html
        assert 'class="btn btn-danger"' not in html
    assert EventFormat.objects.filter(pk=event_format.pk).exists()
    assert ServicePackage.objects.filter(pk=package.pk).exists()


def test_unused_format_can_still_be_deleted(client, package_operator):
    event_format = EventFormat.objects.create(name='Неиспользуемый формат')
    response = client.post(reverse('core:format_delete', args=[event_format.pk]))
    assert response.status_code == 302
    assert response.url == reverse('core:formats')
    assert not EventFormat.objects.filter(pk=event_format.pk).exists()


@pytest.mark.parametrize('editing', [False, True])
def test_package_form_save_and_invalid_price(client, package_operator, crm_objects, editing):
    package = ServicePackage.objects.create(name='Прежний пакет', event_format=crm_objects['event_format'], services='Свет', price=10)
    url = reverse('core:package_update', args=[package.pk]) if editing else reverse('core:package_create')
    response = client.get(url)
    assert 'core/package_form.html' in [template.name for template in response.templates]
    assert response.context['cancel_url'] == reverse('core:packages')
    data = {'name': 'Обновлённый пакет', 'event_format': package.event_format_id, 'services': 'Свет\nЗвук', 'price': '-1'}
    invalid = client.post(url, data)
    assert invalid.status_code == 200
    assert 'price' in invalid.context['form'].errors
    assert not ServicePackage.objects.filter(name=data['name']).exists()
    data['price'] = '125000.50'
    saved = client.post(url, data)
    assert saved.status_code == 302
    assert saved.url == reverse('core:packages')
    assert ServicePackage.objects.get(name=data['name']).price == Decimal('125000.50')


def test_package_catalog_services_and_money(client, package_operator, crm_objects):
    first = ServicePackage.objects.create(name='Список строками', event_format=crm_objects['event_format'], services='Свет\n\nЗвук, микрофоны', price=980000)
    second = ServicePackage.objects.create(name='Прежний список', event_format=crm_objects['event_format'], services='Бриф, площадка, техника', price=Decimal('1234.50'))
    assert first.service_items == ['Свет', 'Звук, микрофоны']
    assert second.service_items == ['Бриф', 'площадка', 'техника']
    html = client.get(reverse('core:packages')).content.decode().replace('\xa0', ' ')
    assert '980 000 ₽' in html and '1 234,50 ₽' in html
    assert '<li>Звук, микрофоны</li>' in html
    assert 'aria-current="page">Пакеты</a>' in html
