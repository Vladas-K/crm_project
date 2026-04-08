from django import forms
from django.contrib.auth import get_user_model

from .models import Client, Event, EventFormat, Lead, PipelineStage, ServicePackage, Vendor

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
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            if isinstance(widget, forms.DateTimeInput):
                widget.input_type = "datetime-local"
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
            "messenger",
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
            "roles",
            "event_formats",
            "min_cost",
            "avg_cost",
            "rating",
            "reliability",
            "contacts",
            "availability_notes",
            "blacklisted",
        ]
        widgets = {
            "contacts": forms.Textarea(attrs={"rows": 3}),
            "availability_notes": forms.Textarea(attrs={"rows": 3}),
        }


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
