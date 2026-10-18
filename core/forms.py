import json
from uuid import uuid4

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Max, Q

from .models import (
    Client,
    Event,
    EventCommunication,
    EventDocument,
    EventExpense,
    ExpenseCategory,
    EventFormat,
    EventOutcome,
    EventRisk,
    EventTask,
    EventTimelineItem,
    EventVendor,
    Lead,
    PipelineStage,
    ServicePackage,
    Vendor,
    VendorRole,
    normalize_russian_phone,
    normalize_website_url,
)

User = get_user_model()


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
                continue
            css_class = "form-select" if isinstance(widget, (forms.Select, forms.SelectMultiple)) else "form-control"
            if isinstance(widget, forms.DateTimeInput):
                widget.input_type = "datetime-local"
                widget.format = "%Y-%m-%dT%H:%M"
            elif isinstance(widget, forms.DateInput):
                widget.input_type = "date"
                widget.format = "%Y-%m-%d"
            widget.attrs["class"] = css_class
            if field.required:
                widget.attrs["required"] = "required"


class LeadForm(BootstrapModelForm):
    class Meta:
        model = Lead
        fields = [
            "name",
            "phone",
            "email",
            "telegram",
            "whatsapp",
            "max_messenger",
            "instagram",
            "facebook",
            "vk",
            "source",
            "preliminary_event_format",
            "comment",
            "stage",
            "probability",
            "loss_reason",
            "manager",
            "last_contact_at",
        ]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 4}),
            "loss_reason": forms.Textarea(attrs={"rows": 3}),
            "last_contact_at": forms.DateTimeInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.order_by("username")
        stages = list(PipelineStage.objects.order_by("order", "name"))
        self.fields["stage"].queryset = PipelineStage.objects.filter(pk__in=[stage.pk for stage in stages]).order_by(
            "order", "name"
        )
        self.fields["stage"].widget.attrs.update(
            {
                "data-lost-stage-ids": json.dumps([str(stage.pk) for stage in stages if stage.is_lost]),
                "data-stage-probabilities": json.dumps(
                    {str(stage.pk): stage.probability for stage in stages}
                ),
            }
        )
        self.fields["phone"].widget.attrs.update(
            {
                "autocomplete": "tel",
                "data-russian-phone": "true",
                "inputmode": "tel",
                "placeholder": "+7 999 000-00-00",
            }
        )
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "placeholder": "name@example.com"}
        )
        self.fields["whatsapp"].widget.attrs.update(
            {
                "autocomplete": "tel",
                "data-russian-phone": "true",
                "inputmode": "tel",
                "placeholder": "+7 999 000-00-00",
            }
        )
        self.fields["name"].widget.attrs.update(
            {"autocomplete": "name", "placeholder": "Имя или название компании"}
        )
        self.fields["source"].widget.attrs.update(
            {"list": "lead-source-suggestions", "placeholder": "Например, рекомендация или сайт"}
        )
        self.fields["probability"].widget.attrs.update(
            {"min": 0, "max": 100, "step": 1, "inputmode": "numeric"}
        )

    def clean_phone(self):
        """Нормализует основной российский номер лида."""

        return normalize_russian_phone(self.cleaned_data.get("phone", ""))

    def clean_whatsapp(self):
        """Нормализует номер WhatsApp, не изменяя готовую ссылку."""

        value = self.cleaned_data.get("whatsapp", "")
        if value.startswith(("http://", "https://")):
            return value
        return normalize_russian_phone(value)


class LeadStageForm(BootstrapModelForm):
    """Меняет только этап и причину отказа, не затрагивая остальные данные лида."""

    class Meta:
        model = Lead
        fields = ["stage", "loss_reason"]
        labels = {"stage": "Новый этап"}
        widgets = {"loss_reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_stage_id = self.instance.stage_id
        self.fields["stage"].empty_label = "Без этапа"
        stages = list(PipelineStage.objects.order_by("order", "pk"))
        self.fields["stage"].widget.attrs["data-lost-stage-ids"] = json.dumps(
            [str(stage.pk) for stage in stages if stage.is_lost]
        )
        self.fields["stage"].help_text = "При смене этапа вероятность сделки берётся из его настроек. Без этапа — 0%."
        self.fields["loss_reason"].help_text = "Обязательно при переводе в потерянный этап."

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.stage_id != self.original_stage_id:
            instance.probability = instance.stage.probability if instance.stage else 0
        if commit:
            instance.save(update_fields=["stage", "probability", "loss_reason"])
        return instance


class PipelineStageForm(BootstrapModelForm):
    """Настройки этапа с автоматическим кодом и позицией в конце воронки."""

    class Meta:
        model = PipelineStage
        fields = ["name", "code", "order", "probability", "is_lost"]
        labels = {
            "name": "Название этапа",
            "code": "Технический код",
            "order": "Позиция в воронке",
            "probability": "Вероятность сделки (%)",
            "is_lost": "Этап отказа",
        }
        help_texts = {
            "code": "Латинские буквы, цифры, дефис или подчёркивание. Если оставить поле пустым, CRM создаст код автоматически; при редактировании сохранит текущий.",
            "order": "Меньший номер располагается раньше. При создании предложена позиция в конце воронки.",
            "probability": "От 0 до 100%. Подставляется лиду при переходе на этот этап.",
            "is_lost": "При переводе лида потребуется причина отказа.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_code = self.instance.code
        self.fields["code"].required = False
        self.fields["code"].widget.attrs.pop("required", None)
        self.fields["code"].widget.attrs.update({"placeholder": "Заполнится автоматически", "autocomplete": "off", "spellcheck": "false"})
        self.fields["name"].widget.attrs.update({"placeholder": "Например, КП отправлено", "autocomplete": "off"})
        self.fields["order"].widget.attrs.update({"min": 0, "step": 1, "inputmode": "numeric"})
        self.fields["probability"].widget.attrs.update({"min": 0, "max": 100, "step": 1, "inputmode": "numeric"})
        if not self.instance.pk and "order" not in (kwargs.get("initial") or {}):
            last_order = PipelineStage.objects.aggregate(last_order=Max("order"))["last_order"]
            self.initial["order"] = (last_order if last_order is not None else 0) + 1

    def clean_code(self):
        # Код не зависит от переименования этапа; уникальность проверяет ModelForm.
        return self.cleaned_data.get("code") or self.original_code or f"stage-{uuid4().hex}"


class ClientForm(BootstrapModelForm):
    creation_mode = forms.ChoiceField(
        label="Как создать клиента", choices=[("manual", "С нуля"), ("lead", "Из лида")],
        widget=forms.RadioSelect, initial="manual", required=False,
    )
    manager_selection_changed = forms.BooleanField(required=False, widget=forms.HiddenInput)
    lead_contact_fields = ("name", "phone", "email", "telegram", "whatsapp", "max_messenger", "instagram", "facebook", "vk")

    class Meta:
        model = Client
        fields = [
            "lead",
            "client_type",
            "name",
            "manager",
            "phone",
            "email",
            "telegram",
            "whatsapp",
            "max_messenger",
            "instagram",
            "facebook",
            "vk",
            "contacts",
            "segment",
            "preferences",
        ]
        widgets = {
            "contacts": forms.Textarea(attrs={"rows": 3}),
            "preferences": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        eligible = Q(client__isnull=True)
        self.imported_lead_id = self.data.get("lead_contacts_loaded", "") if self.is_bound else ""
        if self.instance.pk:
            eligible |= Q(client__pk=self.instance.pk)
            self.fields.pop("creation_mode")
        self.fields["lead"].queryset = Lead.objects.filter(eligible).order_by("name", "pk")
        self.fields["lead"].empty_label = "Выберите исходный лид"
        manager_choices = Q(is_active=True, crm_profile__isnull=False)
        if self.instance.pk and self.instance.manager_id:
            manager_choices |= Q(pk=self.instance.manager_id)
        self.fields["manager"].queryset = User.objects.filter(manager_choices).order_by("username")
        self.fields["manager"].empty_label = "Без ответственного"
        self.fields["manager"].label_from_instance = lambda user: user.get_full_name() or user.get_username()
        self.fields["manager"].help_text = "Ответственный за работу с клиентом. Назначение не зависит от менеджера лида."
        if "creation_mode" in self.fields:
            self.fields["creation_mode"].widget.attrs.pop("class", None)
        self.fields["client_type"].label = "Тип клиента"
        self.fields["client_type"].choices = [("b2c", "Частное лицо"), ("b2b", "Компания")]
        self.fields["contacts"].label = "Дополнительные сведения о контактах"
        self.fields["contacts"].help_text = "Например, контактное лицо компании и удобное время для связи."
        self.fields["name"].label = "Имя клиента"
        self.fields["name"].widget.attrs["autocomplete"] = "name"
        self.fields["email"].widget.attrs.update(autocomplete="email", placeholder="name@example.com")
        for field in ("phone", "whatsapp"):
            self.fields[field].widget.attrs.update({"data-russian-phone": "true", "placeholder": "+7 999 000-00-00"})
        self.fields["phone"].widget.attrs.update(autocomplete="tel", inputmode="tel")
        self.fields["telegram"].widget.attrs["placeholder"] = "@username или ссылка"
        self.fields["max_messenger"].help_text = "Контакт или полная ссылка"
        # Копируем только пустые значения при создании. Введённые пользователем данные имеют приоритет.
        if not self.instance.pk:
            source = self.data if self.is_bound else self.initial
            lead_id = source.get("lead", "")
            mode = source.get("creation_mode") or ("lead" if lead_id else "manual")
            self.initial["creation_mode"] = mode
            if self.is_bound:
                self.data = self.data.copy()
                if mode == "manual":
                    self.data["lead"] = ""
            if mode == "lead" and str(lead_id).isdigit():
                lead = self.fields["lead"].queryset.filter(pk=lead_id).first()
                if lead:
                    target = self.data if self.is_bound else self.initial
                    manager_changed = self.fields["manager_selection_changed"].to_python(
                        self.data.get("manager_selection_changed", False)
                    ) if self.is_bound else False
                    if not manager_changed and not target.get("manager") and lead.manager_id:
                        if self.fields["manager"].queryset.filter(pk=lead.manager_id).exists():
                            target["manager"] = lead.manager_id
                    if not self.is_bound or str(self.imported_lead_id) != str(lead_id):
                        for field in self.lead_contact_fields:
                            if not str(target.get(field, "")).strip():
                                target[field] = getattr(lead, field)
                    self.imported_lead_id = str(lead_id)
        client_type = self.data.get("client_type") if self.is_bound else self.initial.get("client_type", self.instance.client_type)
        if client_type == Client.ClientType.B2B:
            self.fields["name"].label = "Название компании"
            self.fields["name"].widget.attrs["autocomplete"] = "organization"

    def clean(self):
        data = super().clean()
        if not self.instance.pk and data.get("creation_mode") == "lead" and not data.get("lead"):
            self.add_error("lead", "Выберите доступный лид для создания клиента.")
        return data

    def clean_phone(self):
        return normalize_russian_phone(self.cleaned_data.get("phone", ""))

    def clean_whatsapp(self):
        return normalize_russian_phone(self.cleaned_data.get("whatsapp", ""))


class EventFormatForm(BootstrapModelForm):
    class Meta:
        model = EventFormat
        fields = ["name", "description", "default_budget"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class VendorForm(BootstrapModelForm):
    class Meta:
        model = Vendor
        fields = [
            "name",
            "role_categories",
            "event_formats",
            "contact_person",
            "contact_position",
            "phone",
            "email",
            "website",
            "telegram",
            "whatsapp",
            "max_messenger",
            "instagram",
            "facebook",
            "vk",
            "social_links",
            "service_area",
            "preferred_contact_method",
            "availability_notes",
            "min_cost",
            "avg_cost",
            "rating",
            "reliability",
            "blacklisted",
        ]
        widgets = {
            "role_categories": forms.CheckboxSelectMultiple(),
            "event_formats": forms.CheckboxSelectMultiple(),
            "social_links": forms.Textarea(attrs={"rows": 3}),
            "availability_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role_categories"].queryset = VendorRole.objects.filter(is_active=True).order_by("order", "name")
        self.fields["role_categories"].widget.attrs["class"] = "vendor-choice-grid"
        self.fields["event_formats"].widget.attrs["class"] = "vendor-choice-grid"
        self.fields["telegram"].help_text = "Имя пользователя или полная ссылка"
        self.fields["whatsapp"].help_text = "Номер телефона или полная ссылка"
        self.fields["max_messenger"].help_text = "Контакт или полная ссылка"
        self.fields["instagram"].help_text = "Имя пользователя или полная ссылка"
        self.fields["facebook"].help_text = "Имя пользователя или полная ссылка"
        self.fields["vk"].help_text = "Имя пользователя или полная ссылка"
        self.fields["social_links"].label = "Другие ссылки и портфолио"
        self.fields["social_links"].help_text = "По одной полной ссылке в строке"
        self.fields["phone"].widget.attrs.update(
            {
                "autocomplete": "tel",
                "data-russian-phone": "true",
                "inputmode": "tel",
            }
        )
        self.fields["website"].widget.attrs.update(
            {
                "autocomplete": "url",
                "data-website-url": "true",
                "inputmode": "url",
            }
        )

    def clean_phone(self):
        """Нормализует российский номер до сохранения формы."""

        return normalize_russian_phone(self.cleaned_data.get("phone", ""))

    def clean_website(self):
        """Добавляет https:// к адресу сайта без указанной схемы."""

        return normalize_website_url(self.cleaned_data.get("website", ""))


class ServicePackageForm(BootstrapModelForm):
    class Meta:
        model = ServicePackage
        fields = ["name", "event_format", "services", "price"]
        widgets = {"services": forms.Textarea(attrs={"rows": 4})}


class FinancialFieldsFormMixin:
    """Исключает финансовые поля из отображения, валидации и сохранения без права доступа."""

    financial_fields = ()

    def __init__(self, *args, can_view_finance=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_view_finance:
            for name in self.financial_fields:
                self.fields.pop(name, None)


class EventForm(FinancialFieldsFormMixin, BootstrapModelForm):
    financial_fields = ("planned_budget",)

    class Meta:
        model = Event
        fields = [
            "client",
            "lead",
            "event_format",
            "title",
            "date",
            "city",
            "guests_count",
            "planned_budget",
            "goal",
            "preferences",
            "stop_factors",
            "status",
            "manager",
        ]
        widgets = {
            "date": forms.DateInput(),
            "goal": forms.Textarea(attrs={"rows": 3}),
            "preferences": forms.Textarea(attrs={"rows": 3}),
            "stop_factors": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.order_by("username")


class EventTaskForm(BootstrapModelForm):
    class Meta:
        model = EventTask
        fields = [
            "event",
            "title",
            "description",
            "deadline",
            "deadline_offset_days",
            "responsible",
            "status",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "deadline": forms.DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = User.objects.order_by("username")
        self.fields["event"].queryset = Event.objects.select_related("client").order_by("date", "title", "id")


class EventTimelineItemForm(BootstrapModelForm):
    class Meta:
        model = EventTimelineItem
        fields = ["event", "time", "block", "description", "responsible"]
        widgets = {
            "time": forms.TimeInput(format="%H:%M"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class EventRiskForm(BootstrapModelForm):
    class Meta:
        model = EventRisk
        fields = ["event", "description", "probability", "plan_b"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "plan_b": forms.Textarea(attrs={"rows": 3}),
        }


class EventOutcomeForm(FinancialFieldsFormMixin, BootstrapModelForm):
    financial_fields = ("final_profit",)

    class Meta:
        model = EventOutcome
        fields = ["event", "client_feedback", "final_profit", "lessons_learned", "media_links", "project_rating"]
        widgets = {
            "client_feedback": forms.Textarea(attrs={"rows": 3}),
            "lessons_learned": forms.Textarea(attrs={"rows": 3}),
            "media_links": forms.Textarea(attrs={"rows": 3, "placeholder": "https://..."}),
            "project_rating": forms.NumberInput(attrs={"min": 0, "max": 5}),
        }


class EventExpenseForm(BootstrapModelForm):
    class Meta:
        model = EventExpense
        fields = ["event", "category", "vendor_assignment", "amount", "paid_amount", "payment_status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_duplicate_warning = False
        self.duplicate_warning_message = ""
        self.fields["category"].queryset = ExpenseCategory.objects.filter(is_active=True).order_by("order", "name")
        self.fields["vendor_assignment"].help_text = "Выберите подрядчика, назначенного на это мероприятие."

    def clean(self):
        """Предупреждает о повторном расходе для того же подрядчика в мероприятии."""

        cleaned_data = super().clean()
        event = cleaned_data.get("event")
        vendor_assignment = cleaned_data.get("vendor_assignment")
        if event and vendor_assignment:
            duplicate_expenses = EventExpense.objects.filter(
                event=event,
                vendor_assignment__vendor=vendor_assignment.vendor,
            )
            if self.instance.pk:
                duplicate_expenses = duplicate_expenses.exclude(pk=self.instance.pk)
            if duplicate_expenses.exists():
                self.show_duplicate_warning = True
                self.duplicate_warning_message = (
                    f"В этом мероприятии уже есть расход для подрядчика «{vendor_assignment.vendor}». "
                    "Проверьте, не является ли новая запись дублем."
                )
        return cleaned_data


class EventVendorForm(BootstrapModelForm):
    class Meta:
        model = EventVendor
        fields = ["event", "vendor", "role", "cost", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        vendors = Vendor.objects.prefetch_related("role_categories").order_by("name")
        self.fields["vendor"].queryset = vendors
        role_map = {}
        for vendor in vendors:
            role_names = set(vendor.role_categories.values_list("name", flat=True))
            role_names.update(role.strip() for role in vendor.roles.split(",") if role.strip())
            role_map[str(vendor.pk)] = sorted(role_names, key=str.casefold)
        self.fields["vendor"].widget.attrs["data-role-map"] = json.dumps(role_map, ensure_ascii=False)
        self.fields["role"] = forms.ChoiceField(label="Роль", required=True)
        vendor_id = self.data.get("vendor") if self.is_bound else getattr(self.instance, "vendor_id", None)
        if vendor_id:
            vendor = Vendor.objects.prefetch_related("role_categories").filter(pk=vendor_id).first()
        else:
            vendor = None

        if vendor:
            role_names = set(vendor.role_categories.values_list("name", flat=True))
            role_names.update(role.strip() for role in vendor.roles.split(",") if role.strip())
        else:
            role_names = set()

        if self.instance.role:
            role_names.add(self.instance.role)
        if self.is_bound and self.data.get("role"):
            role_names.add(self.data["role"])
        self.fields["role"].choices = [("", "Сначала выберите подрядчика")] + [
            (name, name) for name in sorted(role_names, key=str.casefold)
        ]


class EventCommunicationForm(BootstrapModelForm):
    class Meta:
        model = EventCommunication
        fields = ["event", "communication_type", "date", "comment", "manager"]
        widgets = {
            "date": forms.DateTimeInput(),
            "comment": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.order_by("username")


class EventDocumentForm(BootstrapModelForm):
    class Meta:
        model = EventDocument
        fields = ["event", "document_type", "file", "status"]
