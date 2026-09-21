import pytest
from django.urls import reverse

from core.models import CRMRole, Event, EventVendor, TeamMemberProfile


def create_vendor_viewer(django_user_model, username, **profile_flags):
    """Создаёт пользователя с минимальным CRM-профилем для просмотра подрядчиков."""

    user = django_user_model.objects.create_user(username=username, password="TestPass123!")
    defaults = {
        "role": CRMRole.PROJECT_MANAGER,
        "can_view_finance": False,
        "can_view_clients": True,
        "can_view_analytics": False,
        "can_manage_leads": False,
        "can_manage_clients": False,
        "can_manage_events": False,
        "can_manage_system": False,
    }
    defaults.update(profile_flags)
    TeamMemberProfile.objects.create(user=user, **defaults)
    return user


@pytest.mark.django_db
def test_vendor_detail_shows_profile_and_event_history(client, django_user_model, crm_objects):
    """Карточка показывает профиль подрядчика и связанные мероприятия."""

    user = create_vendor_viewer(django_user_model, "vendor_viewer")
    vendor = crm_objects["vendor"]
    vendor.contact_person = "Сергей Орлов"
    vendor.contact_position = "Менеджер проектов"
    vendor.phone = "+7 999 100-20-30"
    vendor.email = "manager@stage-pro.test"
    vendor.website = "https://example.com/stage-pro"
    vendor.telegram = "@stage_pro"
    vendor.whatsapp = "8 (999) 100-20-30"
    vendor.max_messenger = "https://max.ru/stage-pro"
    vendor.instagram = "@stage_pro"
    vendor.vk = "vk.com/stage_pro"
    vendor.social_links = "https://vk.com/stage_pro"
    vendor.service_area = "Москва и область"
    vendor.preferred_contact_method = vendor.PreferredContactMethod.TELEGRAM
    vendor.availability_notes = "Свободен по выходным"
    vendor.rating = 4.75
    vendor.reliability = 96
    vendor.event_formats.add(crm_objects["event_format"])
    vendor.save()
    crm_objects["event_vendor"].status = EventVendor.Status.APPROVED
    crm_objects["event_vendor"].save(update_fields=["status"])
    crm_objects["event"].status = Event.Status.COMPLETED
    crm_objects["event"].save(update_fields=["status"])
    client.force_login(user)

    response = client.get(reverse("core:vendor_detail", kwargs={"pk": vendor.pk}))
    html = response.content.decode()

    assert response.status_code == 200
    assert vendor.name in html
    assert "Сергей Орлов" in html
    assert "Менеджер проектов" in html
    assert 'href="tel:+7 999 100-20-30"' in html
    assert 'href="mailto:manager@stage-pro.test"' in html
    assert 'href="https://t.me/stage_pro"' in html
    assert 'href="https://wa.me/79991002030"' in html
    assert 'href="https://max.ru/stage-pro"' in html
    assert 'href="https://instagram.com/stage_pro"' in html
    assert 'href="https://vk.com/stage_pro"' in html
    assert 'href="https://example.com/stage-pro"' in html
    assert 'href="https://vk.com/stage_pro"' in html
    for icon_name in ("phone", "email", "telegram", "whatsapp", "max", "instagram", "vk", "website"):
        assert f"vendor-contact-icon--{icon_name}" in html
    assert "Москва и область" in html
    assert "Предпочтительный способ связи" in html
    assert "manager@stage-pro.test" in html
    assert "Свободен по выходным" in html
    assert crm_objects["event"].title in html
    assert response.context["vendor_summary"] == {
        "events": 1,
        "approved": 1,
        "completed": 1,
    }
    assert reverse("core:event_detail", kwargs={"pk": crm_objects["event"].pk}) in html


@pytest.mark.django_db
def test_vendor_detail_hides_finance_without_access(client, django_user_model, crm_objects):
    """Пользователь без финансового права не видит суммы подрядчика."""

    user = create_vendor_viewer(django_user_model, "vendor_no_finance")
    client.force_login(user)

    response = client.get(reverse("core:vendor_detail", kwargs={"pk": crm_objects["vendor"].pk}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Финансовая сводка" not in html
    assert "Согласовано" not in html
    assert "Стоимость 50000" not in html
    assert "vendor_finance_summary" not in response.context


@pytest.mark.django_db
def test_vendor_detail_shows_finance_with_access(client, django_user_model, crm_objects):
    """Финансовое право открывает суммы назначений, расходов и оплат."""

    user = create_vendor_viewer(django_user_model, "vendor_finance", can_view_finance=True)
    expense = crm_objects["expense"]
    expense.vendor_assignment = crm_objects["event_vendor"]
    expense.paid_amount = 20000
    expense.save(update_fields=["vendor_assignment", "paid_amount"])
    client.force_login(user)

    response = client.get(reverse("core:vendor_detail", kwargs={"pk": crm_objects["vendor"].pk}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Финансовая сводка" in html
    assert response.context["vendor_finance_summary"] == {
        "total_cost": 50000,
        "expenses": 50000,
        "paid": 20000,
        "remaining": 30000,
    }
    assert "Стоимость 50000" in html
    assert "оплачено 20000" in html


@pytest.mark.django_db
def test_vendor_detail_respects_system_action_permission(client, django_user_model, crm_objects):
    """Редактирование карточки отображается только системному пользователю."""

    detail_url = reverse("core:vendor_detail", kwargs={"pk": crm_objects["vendor"].pk})
    edit_url = reverse("core:vendor_update", kwargs={"pk": crm_objects["vendor"].pk})
    viewer = create_vendor_viewer(django_user_model, "vendor_read_only")
    client.force_login(viewer)

    viewer_response = client.get(detail_url)

    assert edit_url not in viewer_response.content.decode()

    system_user = create_vendor_viewer(
        django_user_model,
        "vendor_system_user",
        can_manage_system=True,
    )
    client.force_login(system_user)

    system_response = client.get(detail_url)

    assert edit_url in system_response.content.decode()


@pytest.mark.django_db
def test_vendor_update_uses_sectioned_contact_form(client, django_user_model, crm_objects):
    """Редактирование подрядчика использует отдельную форму с понятными разделами."""

    user = create_vendor_viewer(
        django_user_model,
        "vendor_form_editor",
        can_manage_system=True,
    )
    client.force_login(user)

    response = client.get(reverse("core:vendor_update", kwargs={"pk": crm_objects["vendor"].pk}))
    html = response.content.decode()

    assert response.status_code == 200
    assert any(template.name == "core/vendor_form.html" for template in response.templates)
    assert "Основная информация" in html
    assert "Контактное лицо" in html
    assert "Онлайн-контакты" in html
    assert "Условия работы" in html
    assert "Использовать основной телефон" in html
    assert "Редактирование данных без перехода в Django admin." not in html


@pytest.mark.django_db
def test_vendor_links_open_detail_page(client, django_user_model, crm_objects):
    """Список и карточка мероприятия ведут в профиль подрядчика."""

    user = create_vendor_viewer(django_user_model, "vendor_link_viewer")
    client.force_login(user)
    detail_url = reverse("core:vendor_detail", kwargs={"pk": crm_objects["vendor"].pk})

    vendors_response = client.get(reverse("core:vendors"))
    event_response = client.get(
        f"{reverse('core:event_detail', kwargs={'pk': crm_objects['event'].pk})}?tab=vendors"
    )

    assert detail_url in vendors_response.content.decode()
    assert detail_url in event_response.content.decode()


@pytest.mark.django_db
def test_vendor_list_renders_catalog_cards_and_compact_actions(client, django_user_model, crm_objects):
    """Список подрядчиков показывает рабочий контекст и прячет мутации в компактное меню."""

    user = create_vendor_viewer(
        django_user_model,
        "vendor_catalog_manager",
        can_view_finance=True,
        can_manage_system=True,
    )
    vendor = crm_objects["vendor"]
    vendor.contact_person = "Анна Белова"
    vendor.service_area = "Москва и область"
    vendor.save(update_fields=["contact_person", "service_area"])
    client.force_login(user)

    response = client.get(reverse("core:vendors"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "vendor-card" in html
    assert "Анна Белова" in html
    assert "Москва и область" in html
    assert "Открыть профиль" in html
    assert "Специализация" in html
    assert "Сортировка" in html
