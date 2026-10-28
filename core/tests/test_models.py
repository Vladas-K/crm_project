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
    EventOutcome,
    EventTask,
    EventTimelineItem,
    EventVendor,
    ExpenseCategory,
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
def test_selecting_event_format_does_not_create_operational_records():
    """Формат задаёт тип мероприятия без создания рабочего наполнения."""

    event_format = EventFormat.objects.create(name="Свадьба", description="Частное торжество")
    client = Client.objects.create(name="Анна и Иван")
    event = Event.objects.create(
        client=client,
        event_format=event_format,
        title="Свадьба Анны и Ивана",
        date=timezone.localdate(),
        city="Москва",
        planned_budget=Decimal("500000.00"),
    )

    event.refresh_from_db()

    assert event.event_format == event_format
    assert event.planned_budget == Decimal("500000.00")
    assert event.tasks.count() == 0
    assert event.timeline_items.count() == 0
    assert event.expenses.count() == 0
    assert event.event_vendors.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["change", "clear", "delete", "rename"])
def test_event_format_changes_preserve_existing_operational_records(crm_objects, action):
    """Справочник форматов не управляет содержимым и бюджетом мероприятия."""

    event = crm_objects["event"]
    event_format = crm_objects["event_format"]
    EventTimelineItem.objects.create(event=event, time="18:00", block="Встреча гостей")
    relations = ("tasks", "timeline_items", "expenses", "event_vendors")
    before = {relation: list(getattr(event, relation).order_by("pk").values()) for relation in relations}
    planned_budget = event.planned_budget

    if action == "change":
        event.event_format = EventFormat.objects.create(name="Конференция")
        event.save(update_fields=["event_format"])
    elif action == "clear":
        event.event_format = None
        event.save(update_fields=["event_format"])
    elif action == "delete":
        # Удаление формата разрешено после освобождения связанных пакетов.
        event_format.packages.all().delete()
        event_format.delete()
    else:
        event_format.name = "Корпоративный выезд"
        event_format.description = "Обновлённое описание типа мероприятия"
        event_format.save()
    event.refresh_from_db()

    assert event.planned_budget == planned_budget
    for relation in relations:
        assert list(getattr(event, relation).order_by("pk").values()) == before[relation]
    if action in {"clear", "delete"}:
        assert event.event_format_id is None
    elif action == "change":
        assert event.event_format.name == "Конференция"
    else:
        assert event.event_format.name == "Корпоративный выезд"


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
        category=ExpenseCategory.objects.create(name="Площадка"),
        amount=Decimal("30000.00"),
        paid_amount=Decimal("10000.00"),
    )
    EventExpense.objects.create(
        event=event,
        category=ExpenseCategory.objects.create(name="Техника"),
        amount=Decimal("20000.00"),
        paid_amount=Decimal("5000.00"),
    )

    assert event.total_expenses == Decimal("50000.00")
    assert event.paid_amount_total == Decimal("15000.00")
    assert event.balance == Decimal("85000.00")
    assert event.profit == Decimal("50000.00")
    assert event.margin == Decimal("50.0")


def test_event_outcome_rating_cannot_exceed_five(crm_objects):
    """Оценка итогов мероприятия не может быть выше максимального значения 5."""

    outcome = EventOutcome(event=crm_objects["event"], project_rating=6)

    with pytest.raises(ValidationError):
        outcome.full_clean()


def test_event_outcome_distinguishes_empty_profit_from_zero(crm_objects):
    """Итоги различают неуказанную прибыль и фактический нулевой результат."""

    empty_outcome = EventOutcome(event=crm_objects["event"], final_profit=None)
    zero_outcome = EventOutcome(event=crm_objects["event"], final_profit=Decimal("0.00"))

    empty_outcome.full_clean()
    zero_outcome.full_clean()

    assert empty_outcome.final_profit is None
    assert zero_outcome.final_profit == Decimal("0.00")


def test_expense_can_reference_event_vendor(crm_objects):
    """Расход может быть связан с подрядчиком, назначенным на это мероприятие."""

    expense = EventExpense(
        event=crm_objects["event"],
        category=ExpenseCategory.objects.create(name="Техника"),
        amount=Decimal("50000.00"),
        vendor_assignment=crm_objects["event_vendor"],
    )

    expense.full_clean()


def test_expense_calculates_remaining_amount(crm_objects):
    """Расход рассчитывает остаток после частичной оплаты."""

    expense = EventExpense(
        event=crm_objects["event"],
        category=ExpenseCategory.objects.create(name="Техника"),
        amount=Decimal("150000.00"),
        paid_amount=Decimal("50000.00"),
    )

    assert expense.remaining_amount == Decimal("100000.00")


def test_expense_rejects_payment_above_total(crm_objects):
    """Расход не позволяет указать оплату выше общей суммы."""

    expense = EventExpense(
        event=crm_objects["event"],
        category=ExpenseCategory.objects.create(name="Техника"),
        amount=Decimal("150000.00"),
        paid_amount=Decimal("160000.00"),
    )

    with pytest.raises(ValidationError):
        expense.full_clean()


def test_expense_cannot_reference_vendor_from_another_event(crm_objects):
    """Расход не может ссылаться на подрядчика другого мероприятия."""

    other_event = Event.objects.create(
        client=crm_objects["client"],
        title="Другое мероприятие",
        date=timezone.localdate(),
        city="Москва",
    )
    expense = EventExpense(
        event=other_event,
        category=ExpenseCategory.objects.create(name="Техника"),
        amount=Decimal("50000.00"),
        vendor_assignment=crm_objects["event_vendor"],
    )

    with pytest.raises(ValidationError):
        expense.full_clean()


@pytest.mark.django_db
def test_vendor_saves_russian_phone_with_country_code():
    """Подрядчик сохраняет номер с +7, если пользователь ввёл начальную восьмёрку."""

    vendor = Vendor.objects.create(name="Phone Team", phone="8 999 123-45-67")

    assert vendor.phone == "+7 999 123-45-67"


@pytest.mark.django_db
def test_vendor_saves_website_with_https_scheme():
    """Подрядчик сохраняет адрес сайта с https://, если схема не введена."""

    vendor = Vendor.objects.create(name="Web Team", website="example.com/portfolio")

    assert vendor.website == "https://example.com/portfolio"
