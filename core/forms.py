import json

from django import forms
from django.contrib.auth import get_user_model

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
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "data-russian-phone": "true", "inputmode": "tel"}
        )
        self.fields["whatsapp"].widget.attrs.update(
            {"autocomplete": "tel", "data-russian-phone": "true", "inputmode": "tel"}
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


class PipelineStageForm(BootstrapModelForm):
    class Meta:
        model = PipelineStage
        fields = ["name", "code", "order", "probability", "is_lost"]


class ClientForm(BootstrapModelForm):
    class Meta:
        model = Client
        fields = [
            "lead",
            "client_type",
            "name",
            "phone",
            "email",
            "messenger",
            "contacts",
            "segment",
            "ltv",
            "preferences",
            "event_history",
        ]
        widgets = {
            "contacts": forms.Textarea(attrs={"rows": 3}),
            "preferences": forms.Textarea(attrs={"rows": 3}),
            "event_history": forms.Textarea(attrs={"rows": 4}),
        }


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


class EventForm(BootstrapModelForm):
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


class EventOutcomeForm(BootstrapModelForm):
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
