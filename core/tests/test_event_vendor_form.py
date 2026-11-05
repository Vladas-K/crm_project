import json
import pytest
from django.urls import reverse
from core.forms import EventVendorForm
from core.tests.test_event_workflow import login_user

pytestmark = pytest.mark.django_db


def payload(assignment, **changes):
    return {'event':assignment.event_id,'vendor':assignment.vendor_id,'role':assignment.role,'cost':'100','status':'proposed',**changes}


def test_role_is_checked_and_previous_role_preserved(crm_objects):
    item = crm_objects['event_vendor']
    item.vendor.roles = 'Допустимая'
    item.vendor.save()
    assert EventVendorForm(data=payload(item),instance=item).is_valid()
    form = EventVendorForm(instance=item)
    assert item.role in json.loads(form.fields['vendor'].widget.attrs['data-role-map'])[str(item.vendor_id)]
    invalid = EventVendorForm(data=payload(item,role='Посторонняя'),instance=item)
    assert not invalid.is_valid()
    assert 'role' in invalid.errors


def test_negative_cost_and_bad_vendor_rejected(crm_objects):
    item = crm_objects['event_vendor']
    form = EventVendorForm(data=payload(item,cost='-1'),instance=item,can_view_finance=True)
    assert not form.is_valid() and 'cost' in form.errors
    assert not EventVendorForm(data=payload(item,vendor='bad'),instance=item).is_valid()


def test_hidden_cost_cannot_be_changed(client,django_user_model,crm_objects):
    login_user(client,django_user_model,can_manage_events=True)
    item = crm_objects['event_vendor']; old_cost = item.cost
    url = reverse('core:event_vendor_update',args=[item.pk])
    response = client.get(url)
    assert 'cost' not in response.context['form'].fields
    assert response.context['form'].fields['event'].disabled
    response = client.post(url,payload(item,cost='999999'))
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.cost == old_cost
