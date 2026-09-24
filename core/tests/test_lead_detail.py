import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import CRMRole, TeamMemberProfile


def create_lead_viewer(django_user_model, username, *, can_manage_leads=False, can_manage_system=False):
    """Создаёт пользователя с заданными правами на работу с лидами."""

    user = django_user_model.objects.create_user(username=username, password="TestPass123!")
    TeamMemberProfile.objects.create(
        user=user,
        role=CRMRole.PROJECT_MANAGER,
        can_view_clients=True,
        can_manage_leads=can_manage_leads,
        can_manage_system=can_manage_system,
    )
    return user


@pytest.mark.django_db
def test_lead_detail_shows_contact_pipeline_and_sla(client, django_user_model, crm_objects):
    """Карточка лида показывает контакты, контекст заявки и состояние SLA."""

    lead = crm_objects["lead"]
    lead.phone = "+7 999 100-20-30"
    lead.email = "lead@example.com"
    lead.telegram = "@lead_contact"
    lead.whatsapp = "8 (999) 100-20-30"
    lead.max_messenger = "https://max.ru/lead-contact"
    lead.instagram = "@lead_contact"
    lead.facebook = "lead.contact"
    lead.vk = "lead_contact"
    lead.source = "Instagram"
    lead.comment = "Нужна площадка на 80 гостей"
    lead.last_contact_at = timezone.now()
    lead.save()
    user = create_lead_viewer(django_user_model, "lead_viewer")
    client.force_login(user)

    response = client.get(reverse("core:lead_detail", kwargs={"pk": lead.pk}))
    html = response.content.decode()

    assert response.status_code == 200
    assert lead.name in html
    assert 'href="tel:+7 999 100-20-30"' in html
    assert 'href="mailto:lead@example.com"' in html
    assert "@lead_contact" in html
    assert 'href="https://t.me/lead_contact"' in html
    assert 'href="https://wa.me/79991002030"' in html
    assert 'href="https://max.ru/lead-contact"' in html
    assert 'href="https://instagram.com/lead_contact"' in html
    assert 'href="https://facebook.com/lead.contact"' in html
    assert 'href="https://vk.com/lead_contact"' in html
    assert "Instagram" in html
    assert "Нужна площадка на 80 гостей" in html
    assert "Ответ получен" in html
    assert "contact-icon--compact" not in html
    for icon_name in ("phone", "email", "telegram", "whatsapp", "max", "instagram", "facebook", "vk"):
        assert f"contact-icon--{icon_name}" in html
    assert reverse("core:lead_update", kwargs={"pk": lead.pk}) not in html


@pytest.mark.django_db
def test_lead_detail_actions_follow_permissions(client, django_user_model, crm_objects):
    """Изменение доступно менеджеру лидов, удаление не выводится в карточке."""

    lead = crm_objects["lead"]
    user = create_lead_viewer(django_user_model, "lead_manager", can_manage_leads=True)
    client.force_login(user)

    response = client.get(reverse("core:lead_detail", kwargs={"pk": lead.pk}))
    html = response.content.decode()

    assert reverse("core:lead_update", kwargs={"pk": lead.pk}) in html
    assert reverse("core:lead_delete", kwargs={"pk": lead.pk}) not in html


@pytest.mark.django_db
def test_lead_list_links_to_detail_page(client, django_user_model, crm_objects):
    """Имя лида и компактное меню в каталоге ведут в карточку лида."""

    user = create_lead_viewer(django_user_model, "lead_list_viewer", can_manage_system=True)
    client.force_login(user)
    detail_url = reverse("core:lead_detail", kwargs={"pk": crm_objects["lead"].pk})

    response = client.get(reverse("core:leads"))

    assert response.status_code == 200
    assert response.content.decode().count(f'href="{detail_url}"') >= 2
    assert "contact-icon--compact" in response.content.decode()


@pytest.mark.django_db
def test_lead_update_returns_to_detail_page(client, django_user_model, crm_objects):
    """После редактирования пользователь возвращается в карточку лида."""

    lead = crm_objects["lead"]
    user = create_lead_viewer(django_user_model, "lead_editor", can_manage_leads=True)
    client.force_login(user)

    response = client.get(reverse("core:lead_update", kwargs={"pk": lead.pk}))

    assert response.status_code == 200
    assert response.context["cancel_url"] == reverse("core:lead_detail", kwargs={"pk": lead.pk})
