from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import (
    CRMRole,
    Client,
    Event,
    EventExpense,
    EventFormat,
    EventFormatBudgetTemplate,
    EventFormatTaskTemplate,
    EventFormatTimelineTemplate,
    EventFormatVendorTemplate,
    EventTask,
    EventTimelineItem,
    EventVendor,
    Lead,
    PipelineStage,
    TeamMemberProfile,
    Vendor,
)

User = get_user_model()


@pytest.mark.django_db
def test_lead_assigns_sales_manager_with_lowest_load():
    """Новый лид назначается sales manager с меньшей текущей нагрузкой."""

    stage = PipelineStage.objects.create(name="Новый", code="new", probability=20)
    busy_manager = User.objects.create_user(username="busy_sales")
    free_manager = User.objects.create_user(username="free_sales")
    TeamMemberProfile.objects.create(user=busy_manager, role=CRMRole.SALES_MANAGER)
    TeamMemberProfile.objects.create(user=free_manager, role=CRMRole.SALES_MANAGER)
    Lead.objects.create(name="Уже назначенный лид", stage=stage, manager=busy_manager)

    lead = Lead.objects.create(name="Новый входящий лид", stage=stage)

    assert lead.manager == free_manager


@pytest.mark.django_db
def test_lost_lead_requires_loss_reason():
    """Потерянный лид нельзя сохранить без причины отказа."""

    lost_stage = PipelineStage.objects.create(
        name="Проигран",
        code="lost_test",
        probability=0,
        is_lost=True,
    )

    with pytest.raises(ValidationError) as error:
        Lead.objects.create(name="Потерянный лид", stage=lost_stage)

    assert "loss_reason" in error.value.message_dict


@pytest.mark.django_db
def test_lead_copies_probability_from_stage_when_probability_is_empty():
    """Если вероятность лида не задана, она наследуется из выбранного этапа."""

    stage = PipelineStage.objects.create(name="Переговоры тест", code="negotiation_test", probability=65)

    lead = Lead.objects.create(name="Лид с этапом", stage=stage)

    assert lead.probability == 65


@pytest.mark.django_db
def test_lead_needs_response_after_24_hours_without_contact():
    """Лид требует реакции, если первый контакт не зафиксирован за 24 часа."""

    lead = Lead.objects.create(name="Лид без контакта")
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timezone.timedelta(hours=25))
    lead.refresh_from_db()

    assert lead.needs_response is True


@pytest.mark.django_db
def test_lead_does_not_need_response_after_contact():
    """Зафиксированный контакт снимает follow-up тревогу даже у старого лида."""

    lead = Lead.objects.create(name="Лид с контактом", last_contact_at=timezone.now())
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timezone.timedelta(hours=25))
    lead.refresh_from_db()

    assert lead.needs_response is False


@pytest.mark.django_db
def test_event_creates_related_records_from_format():
    """Мероприятие из формата получает задачи, тайминг, бюджет и подрядчиков."""

    event_format = EventFormat.objects.create(name="Свадьба", default_budget=Decimal("500000.00"))
    vendor = Vendor.objects.create(name="Visual Stories", roles="Фото")
    EventFormatTaskTemplate.objects.create(
        event_format=event_format,
        title="Согласовать концепцию",
        description="Moodboard и референсы",
        deadline_offset_days=-10,
    )
    EventFormatTimelineTemplate.objects.create(
        event_format=event_format,
        time="15:00",
        block="Сбор гостей",
        description="Welcome drink",
        responsible_label="Координатор",
    )
    EventFormatBudgetTemplate.objects.create(
        event_format=event_format,
        category="Фото",
        vendor_name="Visual Stories",
        amount=Decimal("120000.00"),
    )
    EventFormatVendorTemplate.objects.create(
        event_format=event_format,
        vendor=vendor,
        role="Фотограф",
        cost=Decimal("120000.00"),
    )
    client = Client.objects.create(name="Анна и Иван")
    event_date = timezone.localdate() + timezone.timedelta(days=30)

    event = Event.objects.create(
        client=client,
        event_format=event_format,
        title="Свадьба Анны и Ивана",
        date=event_date,
        city="Москва",
        planned_budget=Decimal("500000.00"),
    )

    task = event.tasks.get(title="Согласовать концепцию")
    timeline_item = event.timeline_items.get(block="Сбор гостей")
    expense = event.expenses.get(category="Фото")
    event_vendor = event.event_vendors.get(vendor=vendor)
    assert task.description == "Moodboard и референсы"
    assert task.deadline_offset_days == -10
    assert task.deadline == event_date - timezone.timedelta(days=10)
    assert timeline_item.responsible == "Координатор"
    assert expense.vendor_name == "Visual Stories"
    assert expense.amount == Decimal("120000.00")
    assert expense.payment_status == EventExpense.PaymentStatus.PLANNED
    assert event_vendor.role == "Фотограф"
    assert event_vendor.cost == Decimal("120000.00")
    assert event_vendor.status == EventVendor.Status.PROPOSED


@pytest.mark.django_db
def test_event_structure_creates_all_templates_from_format():
    """Мероприятие создаёт все строки из нескольких шаблонов выбранного формата."""

    event_format = EventFormat.objects.create(name="Конференция", default_budget=Decimal("800000.00"))
    first_vendor = Vendor.objects.create(name="Light Crew", roles="Свет")
    second_vendor = Vendor.objects.create(name="Sound Crew", roles="Звук")
    EventFormatTaskTemplate.objects.create(event_format=event_format, title="Собрать программу")
    EventFormatTaskTemplate.objects.create(event_format=event_format, title="Подтвердить спикеров")
    EventFormatTimelineTemplate.objects.create(event_format=event_format, time="10:00", block="Регистрация")
    EventFormatTimelineTemplate.objects.create(event_format=event_format, time="11:00", block="Открытие")
    EventFormatBudgetTemplate.objects.create(
        event_format=event_format,
        category="Свет",
        vendor_name="Light Crew",
        amount=Decimal("70000.00"),
    )
    EventFormatBudgetTemplate.objects.create(
        event_format=event_format,
        category="Звук",
        vendor_name="Sound Crew",
        amount=Decimal("90000.00"),
    )
    EventFormatVendorTemplate.objects.create(
        event_format=event_format,
        vendor=first_vendor,
        role="Свет",
        cost=Decimal("70000.00"),
    )
    EventFormatVendorTemplate.objects.create(
        event_format=event_format,
        vendor=second_vendor,
        role="Звук",
        cost=Decimal("90000.00"),
    )
    client = Client.objects.create(name="TechConf")

    event = Event.objects.create(
        client=client,
        event_format=event_format,
        title="TechConf 2026",
        date=timezone.localdate(),
        city="Москва",
        planned_budget=Decimal("800000.00"),
    )

    assert set(event.tasks.values_list("title", flat=True)) == {"Собрать программу", "Подтвердить спикеров"}
    assert set(event.timeline_items.values_list("block", flat=True)) == {"Регистрация", "Открытие"}
    assert set(event.expenses.values_list("category", flat=True)) == {"Свет", "Звук"}
    assert set(event.event_vendors.values_list("role", flat=True)) == {"Свет", "Звук"}


@pytest.mark.django_db
def test_event_structure_does_not_duplicate_records_on_resave():
    """Повторное сохранение мероприятия не дублирует структуру из формата."""

    event_format = EventFormat.objects.create(name="Презентация", default_budget=Decimal("300000.00"))
    vendor = Vendor.objects.create(name="Presentation Team", roles="Техника")
    EventFormatTaskTemplate.objects.create(event_format=event_format, title="Подготовить зал")
    EventFormatTimelineTemplate.objects.create(event_format=event_format, time="18:00", block="Сбор гостей")
    EventFormatBudgetTemplate.objects.create(
        event_format=event_format,
        category="Техника",
        vendor_name="Presentation Team",
        amount=Decimal("50000.00"),
    )
    EventFormatVendorTemplate.objects.create(
        event_format=event_format,
        vendor=vendor,
        role="Техника",
        cost=Decimal("50000.00"),
    )
    client = Client.objects.create(name="ООО Презентация")
    event = Event.objects.create(
        client=client,
        event_format=event_format,
        title="Запуск продукта",
        date=timezone.localdate(),
        city="Москва",
    )

    event.title = "Запуск продукта обновлён"
    event.save()

    assert event.tasks.count() == 1
    assert event.timeline_items.count() == 1
    assert event.expenses.count() == 1
    assert event.event_vendors.count() == 1


@pytest.mark.django_db
def test_event_without_format_does_not_create_related_records():
    """Мероприятие без формата не создаёт задачи, тайминг, бюджет и подрядчиков."""

    client = Client.objects.create(name="ООО Без Формата")

    event = Event.objects.create(
        client=client,
        title="Индивидуальное мероприятие",
        date=timezone.localdate(),
        city="Москва",
    )

    assert event.tasks.count() == 0
    assert EventTimelineItem.objects.filter(event=event).count() == 0
    assert event.expenses.count() == 0
    assert event.event_vendors.count() == 0


@pytest.mark.django_db
def test_event_task_deadline_is_calculated_from_event_date():
    """Дедлайн задачи рассчитывается от даты мероприятия по offset в днях."""

    client = Client.objects.create(name="ООО Вектор")
    event_date = timezone.localdate() + timezone.timedelta(days=14)
    event = Event.objects.create(
        client=client,
        title="Корпоратив Вектор",
        date=event_date,
        city="Москва",
    )

    task = EventTask.objects.create(
        event=event,
        title="Подтвердить площадку",
        deadline_offset_days=-7,
    )

    assert task.deadline == event_date - timezone.timedelta(days=7)


@pytest.mark.django_db
def test_event_financial_properties_are_calculated_from_expenses():
    """Финансовые показатели мероприятия считаются из бюджета и расходов."""

    client = Client.objects.create(name="ООО Финанс")
    event = Event.objects.create(
        client=client,
        title="Финансовый тест",
        date=timezone.localdate(),
        city="Москва",
        planned_budget=Decimal("100000.00"),
    )
    EventExpense.objects.create(
        event=event,
        category="Площадка",
        amount=Decimal("30000.00"),
        prepayment=Decimal("10000.00"),
    )
    EventExpense.objects.create(
        event=event,
        category="Техника",
        amount=Decimal("20000.00"),
        prepayment=Decimal("5000.00"),
    )

    assert event.total_expenses == Decimal("50000.00")
    assert event.prepayment_total == Decimal("15000.00")
    assert event.balance == Decimal("85000.00")
    assert event.profit == Decimal("50000.00")
    assert event.margin == Decimal("50.0")
