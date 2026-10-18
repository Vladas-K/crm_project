import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from core.models import CRMRole, Event, EventCommunication, EventDocument, TeamMemberProfile

pytestmark = pytest.mark.django_db

RECORDS = [
    ('event_communication_delete', 'communication', 'communications'),
    ('event_document_delete', 'document', 'documents'),
]


@pytest.fixture
def operator(client, django_user_model):
    user = django_user_model.objects.create_user(username='event_record_operator')
    TeamMemberProfile.objects.create(
        user=user, role=CRMRole.PROJECT_MANAGER, can_manage_events=True,
        can_manage_system=False, can_view_finance=False,
    )
    client.force_login(user)
    return user


def event_tab(event, tab):
    return f"{reverse('core:event_detail', args=[event.pk])}?tab={tab}#event-tabs"


@pytest.mark.parametrize('route,key,tab', RECORDS)
@pytest.mark.parametrize('access', ['anonymous', 'no_profile', 'readonly', 'system_only', 'finance_only'])
def test_event_record_deletion_requires_event_management(client, django_user_model, crm_objects, route, key, tab, access):
    record = crm_objects[key]
    if access != 'anonymous':
        user = django_user_model.objects.create_user(username=access)
        if access != 'no_profile':
            TeamMemberProfile.objects.create(
                user=user, role=CRMRole.PROJECT_MANAGER, can_manage_events=False,
                can_manage_system=access == 'system_only', can_view_finance=access == 'finance_only',
            )
        client.force_login(user)
    url = reverse(f'core:{route}', args=[record.pk])
    for method in ('get', 'post'):
        response = getattr(client, method)(url)
        assert response.status_code == (302 if access == 'anonymous' else 403)
        if access == 'anonymous':
            assert response.url.startswith(reverse('login'))
        assert type(record).objects.filter(pk=record.pk).exists()


@pytest.mark.parametrize('route,key,tab', RECORDS)
def test_confirmation_is_read_only_and_cancel_returns_to_original_event_tab(client, operator, crm_objects, route, key, tab):
    record = crm_objects[key]
    url = reverse(f'core:{route}', args=[record.pk])
    response = client.get(url, {'return_tab': 'https://example.com', 'event': '999999'})
    assert response.status_code == 200
    assert type(record).objects.filter(pk=record.pk).exists()
    assert response.context['cancel_url'] == event_tab(record.event, tab)
    html = response.content.decode()
    assert record.event.title in html
    assert f'href="{event_tab(record.event, tab)}"' in html
    assert f'name="return_tab" value="{tab}"' in html
    assert 'csrfmiddlewaretoken' in html
    cancel = client.get(response.context['cancel_url'])
    assert cancel.status_code == 200
    assert cancel.context['active_tab'] == tab
    assert type(record).objects.filter(pk=record.pk).exists()


@pytest.mark.parametrize('route,key,tab', RECORDS)
@pytest.mark.parametrize('return_value', ['', 'https://example.com/?tab=tasks'])
def test_delete_removes_only_target_record_and_ignores_forged_parent_and_return_tab(client, operator, crm_objects, route, key, tab, return_value):
    record = crm_objects[key]
    original_pk = record.pk
    parent = record.event
    other_event = Event.objects.create(client=parent.client, title='Другое мероприятие', date=timezone.localdate())
    if key == 'document':
        other = EventDocument.objects.create(event=other_event, document_type=EventDocument.Type.CONTRACT)
    else:
        other = EventCommunication.objects.create(event=other_event, communication_type=EventCommunication.Type.CALL, date=timezone.now())
    url = reverse(f'core:{route}', args=[record.pk])
    response = client.post(url, {'return_tab': return_value, 'event': other_event.pk})
    assert response.status_code == 302
    assert response.url == event_tab(parent, tab)
    assert not type(record).objects.filter(pk=original_pk).exists()
    assert type(record).objects.filter(pk=other.pk).exists()
    assert Event.objects.filter(pk=parent.pk).exists()
    assert Event.objects.filter(pk=other_event.pk).exists()
    assert client.get(url).status_code == 404
    assert client.post(url).status_code == 404
    returned = client.get(response.url)
    assert returned.context['active_tab'] == tab
    assert any('удален' in str(message).replace('ё', 'е') for message in returned.context['messages'])


@pytest.mark.parametrize('route,key,tab', RECORDS)
@pytest.mark.parametrize('can_manage', [False, True])
def test_delete_links_follow_event_permission(client, operator, crm_objects, route, key, tab, can_manage):
    operator.crm_profile.can_manage_events = can_manage
    operator.crm_profile.save()
    record = crm_objects[key]
    response = client.get(event_tab(record.event, tab))
    html = response.content.decode()
    url = reverse(f'core:{route}', args=[record.pk])
    assert (f'href="{url}?return_tab={tab}"' in html) is can_manage


@pytest.mark.parametrize('route,key,tab', RECORDS)
def test_direct_http_delete_is_not_supported(client, operator, crm_objects, route, key, tab):
    record = crm_objects[key]
    response = client.delete(reverse(f'core:{route}', args=[record.pk]))
    assert response.status_code == 405
    assert type(record).objects.filter(pk=record.pk).exists()


@pytest.mark.parametrize('route,key,tab', RECORDS)
def test_deletion_requires_csrf_token(operator, crm_objects, route, key, tab):
    secure_client = DjangoClient(enforce_csrf_checks=True)
    secure_client.force_login(operator)
    record = crm_objects[key]
    url = reverse(f'core:{route}', args=[record.pk])
    assert secure_client.post(url).status_code == 403
    assert type(record).objects.filter(pk=record.pk).exists()
    confirmation = secure_client.get(url)
    token = confirmation.cookies['csrftoken'].value
    response = secure_client.post(url, {'csrfmiddlewaretoken': token})
    assert response.status_code == 302
    assert not type(record).objects.filter(pk=record.pk).exists()


@pytest.mark.parametrize('status', EventDocument.Status.values)
def test_document_deletion_supports_all_document_statuses(client, operator, crm_objects, status):
    document = crm_objects['document']
    document.status = status
    document.save()
    url = reverse('core:event_document_delete', args=[document.pk])
    confirmation = client.get(url)
    assert document.get_status_display() in confirmation.content.decode()
    assert client.post(url).status_code == 302
    assert not EventDocument.objects.filter(pk=document.pk).exists()


def test_document_file_is_removed_only_after_commit(client, operator, crm_objects, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = tmp_path
    document = crm_objects['document']
    document.file = SimpleUploadedFile('contract.txt', b'contract')
    document.save()
    storage, filename = document.file.storage, document.file.name
    url = reverse('core:event_document_delete', args=[document.pk])
    confirmation = client.get(url)
    assert storage.exists(filename)
    assert 'contract.txt' in confirmation.content.decode()
    assert 'также будет удалён' in confirmation.content.decode()
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(url)
        assert response.status_code == 302
        assert not EventDocument.objects.filter(pk=document.pk).exists()
        assert storage.exists(filename)
    assert len(callbacks) == 1
    assert not storage.exists(filename)


def test_rollback_preserves_document_and_file(client, operator, crm_objects, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = tmp_path
    document = crm_objects['document']
    document.file = SimpleUploadedFile('keep.txt', b'keep')
    document.save()
    filename, storage = document.file.name, document.file.storage
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                assert client.post(reverse('core:event_document_delete', args=[document.pk])).status_code == 302
                raise RuntimeError('Rollback')
    assert callbacks == []
    assert EventDocument.objects.filter(pk=document.pk).exists()
    assert storage.exists(filename)


def test_shared_file_is_kept_for_remaining_document(client, operator, crm_objects, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = tmp_path
    document = crm_objects['document']
    document.file = SimpleUploadedFile('shared.txt', b'shared')
    document.save()
    other = EventDocument.objects.create(event=document.event, document_type=EventDocument.Type.ACT, file=document.file.name)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(reverse('core:event_document_delete', args=[document.pk])).status_code == 302
    assert EventDocument.objects.filter(pk=other.pk).exists()
    assert other.file.storage.exists(other.file.name)


def test_communication_confirmation_escapes_comment(client, operator, crm_objects):
    communication = crm_objects['communication']
    communication.comment = '<script>alert(1)</script>'
    communication.save()
    html = client.get(reverse('core:event_communication_delete', args=[communication.pk])).content.decode()
    assert communication.comment not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'Дата и время:' in html
