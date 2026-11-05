from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.forms import EventExpenseForm
from core.models import Event, EventExpense
from core.tests.test_event_workflow import login_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('amount,paid,status', [('100','0','planned'),('100','30','partial'),('100','100','paid'),('0','0','planned')])
def test_status_is_derived_and_manual_status_is_ignored(crm_objects, amount, paid, status):
    expense = crm_objects['expense']
    expense.amount = Decimal(amount)
    expense.paid_amount = Decimal(paid)
    expense.payment_status = 'paid' if status != 'paid' else 'planned'
    expense.save(update_fields=['amount', 'paid_amount'])
    expense.refresh_from_db()
    assert expense.payment_status == status


@pytest.mark.parametrize('amount,paid,field', [('-1','0','amount'),('100','-1','paid_amount'),('100','101','paid_amount')])
def test_invalid_amounts_have_field_errors_and_database_protection(crm_objects, amount, paid, field):
    expense = crm_objects['expense']
    form = EventExpenseForm(data={'event':expense.event_id,'category':expense.category_id,'amount':amount,'paid_amount':paid}, instance=expense)
    assert not form.is_valid()
    assert field in form.errors
    with pytest.raises(IntegrityError), transaction.atomic():
        EventExpense.objects.filter(pk=expense.pk).update(amount=amount, paid_amount=paid)


def test_existing_inactive_category_can_be_kept_but_not_newly_selected(crm_objects):
    expense = crm_objects['expense']
    category = expense.category
    category.is_active = False
    category.save()
    data = {'event':expense.event_id,'category':category.pk,'amount':'100','paid_amount':'0'}
    assert EventExpenseForm(data=data,instance=expense).is_valid()
    assert not EventExpenseForm(data=data).is_valid()


def test_event_is_fixed_and_return_filters_survive(client, django_user_model, crm_objects):
    login_user(client, django_user_model, can_view_finance=True)
    expense = crm_objects['expense']
    other = Event.objects.create(client=crm_objects['client'], date=expense.event.date, city='Москва')
    url = reverse('core:event_expense_update', args=[expense.pk])
    response = client.post(url, {'event':other.pk,'category':expense.category_id,'amount':'200','paid_amount':'50',
                                'payment_status':'paid','event_filters':'expense_filter=partial','return_tab':'expenses'})
    assert response.status_code == 302
    expense.refresh_from_db()
    assert expense.event_id == crm_objects['event'].pk
    assert expense.payment_status == 'partial'
    assert parse_qs(urlsplit(response.url).query)['expense_filter'] == ['partial']
    get = client.get(url)
    assert b'payment_status' not in get.content
    assert 'Сохранить изменения' in get.content.decode()
