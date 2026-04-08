from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

User = get_user_model()


class ContactMixin(models.Model):
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    messenger = models.CharField("Мессенджер", max_length=100, blank=True)

    class Meta:
        abstract = True


class CRMRole(models.TextChoices):
    SALES_MANAGER = "sales_manager", "Sales Manager"
    PROJECT_MANAGER = "project_manager", "Project Manager"
    ADMIN = "admin", "Admin"
    FINANCE = "finance", "Finance"


class TeamMemberProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="crm_profile",
        verbose_name="Пользователь",
    )
    role = models.CharField("Роль", max_length=30, choices=CRMRole.choices)
    can_view_finance = models.BooleanField("Доступ к финансам", default=False)
    can_view_clients = models.BooleanField("Доступ к клиентам", default=True)
    can_view_analytics = models.BooleanField("Доступ к аналитике", default=False)
    can_manage_system = models.BooleanField("Управление системой", default=False)

    class Meta:
        verbose_name = "Профиль сотрудника"
        verbose_name_plural = "Профили сотрудников"

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.get_role_display()})"


class PipelineStage(models.Model):
    name = models.CharField("Этап", max_length=100, unique=True)
    code = models.SlugField("Код", max_length=50, unique=True)
    order = models.PositiveIntegerField("Порядок", default=0)
    probability = models.PositiveSmallIntegerField("Вероятность (%)", default=0)
    is_lost = models.BooleanField("Потерянный этап", default=False)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Этап воронки"
        verbose_name_plural = "Этапы воронки"

    def __str__(self) -> str:
        return self.name


class EventFormat(models.Model):
    name = models.CharField("Формат мероприятия", max_length=120, unique=True)
    description = models.TextField("Описание", blank=True)
    default_budget = models.DecimalField("Бюджет по умолчанию", max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ("name",)
        verbose_name = "Формат мероприятия"
        verbose_name_plural = "Форматы мероприятий"

    def __str__(self) -> str:
        return self.name


class Lead(ContactMixin):
    name = models.CharField("Имя", max_length=255)
    source = models.CharField("Источник", max_length=120, blank=True)
    preliminary_event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Предварительный формат мероприятия",
    )
    comment = models.TextField("Комментарий", blank=True)
    stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Статус",
    )
    probability = models.PositiveSmallIntegerField("Вероятность сделки (%)", default=0)
    loss_reason = models.TextField("Причина отказа", blank=True)
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
        verbose_name="Ответственный менеджер",
    )
    last_contact_at = models.DateTimeField("Последний контакт", null=True, blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Лид"
        verbose_name_plural = "Лиды"

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.stage and self.stage.is_lost and not self.loss_reason:
            raise ValidationError({"loss_reason": "Укажите причину отказа для потерянного лида."})

    @property
    def follow_up_deadline(self):
        return self.created_at + timezone.timedelta(hours=24) if self.created_at else None

    @property
    def needs_response(self) -> bool:
        deadline = self.follow_up_deadline
        return bool(deadline and timezone.now() > deadline and not self.last_contact_at)

    def save(self, *args, **kwargs):
        if not self.manager:
            self.manager = (
                User.objects.filter(crm_profile__role=CRMRole.SALES_MANAGER)
                .annotate(models.Count("assigned_leads"))
                .order_by("assigned_leads__count", "id")
                .first()
            )
        if self.stage and not self.probability:
            self.probability = self.stage.probability
        self.full_clean()
        super().save(*args, **kwargs)


class Client(ContactMixin):
    class ClientType(models.TextChoices):
        B2B = "b2b", "B2B"
        B2C = "b2c", "B2C"

    class Segment(models.TextChoices):
        VIP = "vip", "VIP"
        STANDARD = "standard", "Стандарт"

    lead = models.OneToOneField(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client",
        verbose_name="Исходный лид",
    )
    client_type = models.CharField("Тип", max_length=10, choices=ClientType.choices, default=ClientType.B2C)
    name = models.CharField("Имя / компания", max_length=255)
    contacts = models.TextField("Контакты", blank=True)
    segment = models.CharField("Сегмент", max_length=20, choices=Segment.choices, default=Segment.STANDARD)
    ltv = models.DecimalField("LTV", max_digits=12, decimal_places=2, default=0)
    preferences = models.TextField("Предпочтения", blank=True)
    event_history = models.TextField("История мероприятий", blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"

    def __str__(self) -> str:
        return self.name


class Vendor(models.Model):
    name = models.CharField("Имя / компания", max_length=255)
    roles = models.CharField("Роли", max_length=255, help_text="Например: ведущий, фотограф")
    event_formats = models.ManyToManyField(
        EventFormat,
        blank=True,
        related_name="vendors",
        verbose_name="Форматы мероприятий",
    )
    min_cost = models.DecimalField("Минимальная стоимость", max_digits=12, decimal_places=2, default=0)
    avg_cost = models.DecimalField("Средняя стоимость", max_digits=12, decimal_places=2, default=0)
    rating = models.DecimalField("Рейтинг", max_digits=3, decimal_places=2, default=0)
    reliability = models.PositiveSmallIntegerField("Надёжность (%)", default=0)
    contacts = models.TextField("Контакты", blank=True)
    availability_notes = models.TextField("Календарь занятости", blank=True)
    blacklisted = models.BooleanField("Чёрный список", default=False)

    class Meta:
        ordering = ("name",)
        verbose_name = "Подрядчик"
        verbose_name_plural = "Подрядчики"

    def __str__(self) -> str:
        return self.name


class ServicePackage(models.Model):
    name = models.CharField("Название пакета", max_length=255)
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.CASCADE,
        related_name="packages",
        verbose_name="Формат мероприятия",
    )
    services = models.TextField("Список услуг")
    price = models.DecimalField("Цена", max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("name",)
        verbose_name = "Пакет услуг"
        verbose_name_plural = "Пакеты услуг"

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    class Status(models.TextChoices):
        PLANNING = "planning", "Планирование"
        IN_PROGRESS = "in_progress", "В реализации"
        COMPLETED = "completed", "Завершено"
        CANCELLED = "cancelled", "Отменено"

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="Клиент",
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Лид",
    )
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Формат",
    )
    title = models.CharField("Название мероприятия", max_length=255, blank=True)
    date = models.DateField("Дата")
    city = models.CharField("Город", max_length=120)
    guests_count = models.PositiveIntegerField("Количество гостей", default=0)
    planned_budget = models.DecimalField("Бюджет плановый", max_digits=12, decimal_places=2, default=0)
    goal = models.TextField("Цель мероприятия", blank=True)
    preferences = models.TextField("Предпочтения", blank=True)
    stop_factors = models.TextField("Стоп-факторы", blank=True)
    status = models.CharField("Статус реализации", max_length=20, choices=Status.choices, default=Status.PLANNING)
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_events",
        verbose_name="Project Manager",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ("date", "-created_at")
        verbose_name = "Мероприятие"
        verbose_name_plural = "Мероприятия"

    def __str__(self) -> str:
        return self.title or f"{self.client} - {self.event_format or 'Мероприятие'}"

    @property
    def total_expenses(self) -> Decimal:
        return sum((expense.amount for expense in self.expenses.all()), Decimal("0"))

    @property
    def prepayment_total(self) -> Decimal:
        return sum((expense.prepayment for expense in self.expenses.all()), Decimal("0"))

    @property
    def balance(self) -> Decimal:
        return Decimal(self.planned_budget) - self.prepayment_total

    @property
    def profit(self) -> Decimal:
        return Decimal(self.planned_budget) - self.total_expenses

    @property
    def margin(self) -> Decimal:
        if not self.planned_budget:
            return Decimal("0")
        return (self.profit / Decimal(self.planned_budget)) * Decimal("100")

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating and self.event_format:
            self.bootstrap_from_format()

    def bootstrap_from_format(self) -> None:
        for template in self.event_format.task_templates.all():
            EventTask.objects.get_or_create(
                event=self,
                title=template.title,
                defaults={
                    "description": template.description,
                    "deadline_offset_days": template.deadline_offset_days,
                    "responsible": self.manager,
                    "status": EventTask.Status.TODO,
                },
            )
        for template in self.event_format.timeline_templates.all():
            EventTimelineItem.objects.get_or_create(
                event=self,
                time=template.time,
                block=template.block,
                defaults={
                    "description": template.description,
                    "responsible": template.responsible_label,
                },
            )
        for template in self.event_format.budget_templates.all():
            EventExpense.objects.get_or_create(
                event=self,
                category=template.category,
                vendor_name=template.vendor_name,
                defaults={
                    "amount": template.amount,
                    "payment_status": EventExpense.PaymentStatus.PLANNED,
                },
            )
        for template in self.event_format.vendor_templates.select_related("vendor"):
            EventVendor.objects.get_or_create(
                event=self,
                vendor=template.vendor,
                role=template.role,
                defaults={
                    "cost": template.cost,
                    "status": EventVendor.Status.PROPOSED,
                },
            )


class EventExpense(models.Model):
    class PaymentStatus(models.TextChoices):
        PLANNED = "planned", "Запланировано"
        PARTIAL = "partial", "Частично оплачено"
        PAID = "paid", "Оплачено"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="expenses",
        verbose_name="Мероприятие",
    )
    category = models.CharField("Категория", max_length=120)
    vendor_name = models.CharField("Подрядчик", max_length=255, blank=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2, default=0)
    prepayment = models.DecimalField("Предоплата", max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(
        "Статус оплаты",
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PLANNED,
    )

    class Meta:
        ordering = ("category", "id")
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"

    def __str__(self) -> str:
        return f"{self.category} - {self.amount}"


class EventVendor(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложен"
        APPROVED = "approved", "Утверждён"
        REPLACED = "replaced", "Заменён"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="event_vendors",
        verbose_name="Мероприятие",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="event_assignments",
        verbose_name="Подрядчик",
    )
    role = models.CharField("Роль", max_length=120)
    cost = models.DecimalField("Стоимость", max_digits=12, decimal_places=2, default=0)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.PROPOSED)

    class Meta:
        verbose_name = "Подрядчик мероприятия"
        verbose_name_plural = "Подрядчики мероприятия"
        unique_together = ("event", "vendor", "role")

    def __str__(self) -> str:
        return f"{self.vendor} / {self.role}"


class EventTask(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "К выполнению"
        IN_PROGRESS = "in_progress", "В работе"
        DONE = "done", "Готово"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Мероприятие",
    )
    title = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    deadline = models.DateField("Дедлайн", null=True, blank=True)
    deadline_offset_days = models.IntegerField("Смещение дедлайна", default=0)
    responsible = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_tasks",
        verbose_name="Ответственный",
    )
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.TODO)

    class Meta:
        ordering = ("deadline", "id")
        verbose_name = "Задача мероприятия"
        verbose_name_plural = "Задачи мероприятия"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.event_id and not self.deadline:
            self.deadline = self.event.date + timezone.timedelta(days=self.deadline_offset_days)
        super().save(*args, **kwargs)


class EventTimelineItem(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="timeline_items",
        verbose_name="Мероприятие",
    )
    time = models.TimeField("Время")
    block = models.CharField("Блок", max_length=120)
    description = models.TextField("Описание", blank=True)
    responsible = models.CharField("Ответственный", max_length=120, blank=True)

    class Meta:
        ordering = ("time", "id")
        verbose_name = "Тайминг"
        verbose_name_plural = "Тайминг"

    def __str__(self) -> str:
        return f"{self.time} - {self.block}"


class EventRisk(models.Model):
    class Probability(models.TextChoices):
        LOW = "low", "Низкая"
        MEDIUM = "medium", "Средняя"
        HIGH = "high", "Высокая"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="risks",
        verbose_name="Мероприятие",
    )
    description = models.TextField("Описание риска")
    probability = models.CharField("Вероятность", max_length=10, choices=Probability.choices, default=Probability.MEDIUM)
    plan_b = models.TextField("План B", blank=True)

    class Meta:
        verbose_name = "Риск"
        verbose_name_plural = "Риски"

    def __str__(self) -> str:
        return self.description[:60]


class EventCommunication(models.Model):
    class Type(models.TextChoices):
        CALL = "call", "Звонок"
        MESSAGE = "message", "Сообщение"
        MEETING = "meeting", "Встреча"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="communications",
        verbose_name="Мероприятие",
    )
    communication_type = models.CharField("Тип", max_length=20, choices=Type.choices)
    date = models.DateTimeField("Дата")
    comment = models.TextField("Комментарий", blank=True)
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_communications",
        verbose_name="Менеджер",
    )

    class Meta:
        ordering = ("-date",)
        verbose_name = "Коммуникация"
        verbose_name_plural = "Коммуникации"

    def __str__(self) -> str:
        return f"{self.get_communication_type_display()} - {self.date:%d.%m.%Y}"


class EventDocument(models.Model):
    class Type(models.TextChoices):
        CONTRACT = "contract", "Договор"
        INVOICE = "invoice", "Счёт"
        PROPOSAL = "proposal", "КП"
        ACT = "act", "Акт"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SENT = "sent", "Отправлен"
        SIGNED = "signed", "Подписан"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Мероприятие",
    )
    document_type = models.CharField("Тип", max_length=20, choices=Type.choices)
    file = models.FileField("Файл", upload_to="event_documents/", blank=True)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        verbose_name = "Документ"
        verbose_name_plural = "Документы"

    def __str__(self) -> str:
        return self.get_document_type_display()


class EventOutcome(models.Model):
    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="outcome",
        verbose_name="Мероприятие",
    )
    client_feedback = models.TextField("Отзыв клиента", blank=True)
    final_profit = models.DecimalField("Финальная прибыль", max_digits=12, decimal_places=2, default=0)
    lessons_learned = models.TextField("Проблемы / выводы", blank=True)
    media_links = models.TextField("Фото / видео материалы", blank=True)
    project_rating = models.PositiveSmallIntegerField("Оценка проекта", default=0)

    class Meta:
        verbose_name = "Итоги мероприятия"
        verbose_name_plural = "Итоги мероприятий"

    def __str__(self) -> str:
        return f"Итоги: {self.event}"


class EventFormatTaskTemplate(models.Model):
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.CASCADE,
        related_name="task_templates",
        verbose_name="Формат мероприятия",
    )
    title = models.CharField("Задача", max_length=255)
    description = models.TextField("Описание", blank=True)
    deadline_offset_days = models.IntegerField("Смещение дедлайна", default=0)

    class Meta:
        verbose_name = "Шаблон задачи"
        verbose_name_plural = "Шаблоны задач"

    def __str__(self) -> str:
        return self.title


class EventFormatTimelineTemplate(models.Model):
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.CASCADE,
        related_name="timeline_templates",
        verbose_name="Формат мероприятия",
    )
    time = models.TimeField("Время")
    block = models.CharField("Блок", max_length=120)
    description = models.TextField("Описание", blank=True)
    responsible_label = models.CharField("Ответственный", max_length=120, blank=True)

    class Meta:
        ordering = ("time", "id")
        verbose_name = "Шаблон тайминга"
        verbose_name_plural = "Шаблоны тайминга"

    def __str__(self) -> str:
        return f"{self.event_format} - {self.block}"


class EventFormatBudgetTemplate(models.Model):
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.CASCADE,
        related_name="budget_templates",
        verbose_name="Формат мероприятия",
    )
    category = models.CharField("Категория", max_length=120)
    vendor_name = models.CharField("Подрядчик", max_length=255, blank=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Шаблон бюджета"
        verbose_name_plural = "Шаблоны бюджета"

    def __str__(self) -> str:
        return f"{self.event_format} - {self.category}"


class EventFormatVendorTemplate(models.Model):
    event_format = models.ForeignKey(
        EventFormat,
        on_delete=models.CASCADE,
        related_name="vendor_templates",
        verbose_name="Формат мероприятия",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="format_templates",
        verbose_name="Подрядчик",
    )
    role = models.CharField("Роль", max_length=120)
    cost = models.DecimalField("Стоимость", max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Шаблон подрядчика"
        verbose_name_plural = "Шаблоны подрядчиков"

    def __str__(self) -> str:
        return f"{self.event_format} - {self.vendor}"
