from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from .forms import ClientForm, EventForm, EventFormatForm, LeadForm, PipelineStageForm, ServicePackageForm, VendorForm

from .models import (
    Client,
    Event,
    EventFormat,
    EventTask,
    Lead,
    PipelineStage,
    ServicePackage,
    TeamMemberProfile,
    Vendor,
)

User = get_user_model()


class DashboardView(TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["stats"] = {
            "leads_count": Lead.objects.count(),
            "clients_count": Client.objects.count(),
            "events_count": Event.objects.count(),
            "vendors_count": Vendor.objects.count(),
        }
        context["latest_leads"] = Lead.objects.select_related("stage", "manager")[:5]
        context["upcoming_events"] = Event.objects.select_related("client", "event_format").order_by("date")[:5]
        context["open_tasks"] = EventTask.objects.select_related("event", "responsible").exclude(
            status=EventTask.Status.DONE
        )[:5]
        context["pipeline_summary"] = PipelineStage.objects.annotate(total=Count("leads"))
        return context


class LeadListView(ListView):
    model = Lead
    template_name = "core/leads.html"
    context_object_name = "leads"
    queryset = Lead.objects.select_related("stage", "manager", "preliminary_event_format")


class PipelineView(TemplateView):
    template_name = "core/pipeline.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["stages"] = PipelineStage.objects.prefetch_related("leads__manager").all()
        return context


class ClientListView(ListView):
    model = Client
    template_name = "core/clients.html"
    context_object_name = "clients"


class EventListView(ListView):
    model = Event
    template_name = "core/events.html"
    context_object_name = "events"
    queryset = Event.objects.select_related("client", "lead", "event_format", "manager")


class EventFormatListView(ListView):
    model = EventFormat
    template_name = "core/formats.html"
    context_object_name = "formats"


class VendorListView(ListView):
    model = Vendor
    template_name = "core/vendors.html"
    context_object_name = "vendors"


class PackageListView(ListView):
    model = ServicePackage
    template_name = "core/packages.html"
    context_object_name = "packages"
    queryset = ServicePackage.objects.select_related("event_format")


class CalendarView(ListView):
    model = Event
    template_name = "core/calendar.html"
    context_object_name = "events"
    queryset = Event.objects.select_related("client", "manager").order_by("date")


class AnalyticsView(TemplateView):
    template_name = "core/analytics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        total_leads = Lead.objects.count() or 1
        qualified_clients = Client.objects.count()
        total_revenue = Event.objects.aggregate(total=Sum("planned_budget"))["total"] or 0
        context["metrics"] = {
            "conversion": round((qualified_clients / total_leads) * 100, 1),
            "average_check": round(total_revenue / max(Event.objects.count(), 1), 2),
            "profit": sum(event.profit for event in Event.objects.prefetch_related("expenses")),
            "sources": Lead.objects.values("source").annotate(total=Count("id")).order_by("-total"),
            "team_load": User.objects.annotate(total_events=Count("managed_events")).order_by("-total_events")[:6],
        }
        return context


class TeamView(ListView):
    model = TeamMemberProfile
    template_name = "core/team.html"
    context_object_name = "profiles"
    queryset = TeamMemberProfile.objects.select_related("user")


class CRUDContextMixin:
    page_title = ""
    submit_label = "Сохранить"
    cancel_url = reverse_lazy("core:dashboard")

    def get_cancel_url(self):
        return self.cancel_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.get_cancel_url()
        return context


class SuccessMessageMixin:
    success_message = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class LeadCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = Lead
    form_class = LeadForm
    template_name = "core/object_form.html"
    page_title = "Новый лид"
    success_message = "Лид создан."
    success_url = reverse_lazy("core:leads")
    cancel_url = reverse_lazy("core:leads")


class LeadUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = Lead
    form_class = LeadForm
    template_name = "core/object_form.html"
    page_title = "Редактирование лида"
    success_message = "Лид обновлён."
    success_url = reverse_lazy("core:leads")
    cancel_url = reverse_lazy("core:leads")


class LeadDeleteView(DeleteView):
    model = Lead
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:leads")


class PipelineStageCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "core/object_form.html"
    page_title = "Новый этап воронки"
    success_message = "Этап воронки создан."
    success_url = reverse_lazy("core:pipeline")
    cancel_url = reverse_lazy("core:pipeline")


class PipelineStageUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "core/object_form.html"
    page_title = "Редактирование этапа"
    success_message = "Этап воронки обновлён."
    success_url = reverse_lazy("core:pipeline")
    cancel_url = reverse_lazy("core:pipeline")


class PipelineStageDeleteView(DeleteView):
    model = PipelineStage
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:pipeline")


class ClientCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "core/object_form.html"
    page_title = "Новый клиент"
    success_message = "Клиент создан."
    success_url = reverse_lazy("core:clients")
    cancel_url = reverse_lazy("core:clients")


class ClientUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "core/object_form.html"
    page_title = "Редактирование клиента"
    success_message = "Клиент обновлён."
    success_url = reverse_lazy("core:clients")
    cancel_url = reverse_lazy("core:clients")


class ClientDeleteView(DeleteView):
    model = Client
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:clients")


class EventCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "core/object_form.html"
    page_title = "Новое мероприятие"
    success_message = "Мероприятие создано."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = "core/object_form.html"
    page_title = "Редактирование мероприятия"
    success_message = "Мероприятие обновлено."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventDeleteView(DeleteView):
    model = Event
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:events")


class EventFormatCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventFormat
    form_class = EventFormatForm
    template_name = "core/object_form.html"
    page_title = "Новый формат"
    success_message = "Формат мероприятия создан."
    success_url = reverse_lazy("core:formats")
    cancel_url = reverse_lazy("core:formats")


class EventFormatUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventFormat
    form_class = EventFormatForm
    template_name = "core/object_form.html"
    page_title = "Редактирование формата"
    success_message = "Формат мероприятия обновлён."
    success_url = reverse_lazy("core:formats")
    cancel_url = reverse_lazy("core:formats")


class EventFormatDeleteView(DeleteView):
    model = EventFormat
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:formats")


class VendorCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = Vendor
    form_class = VendorForm
    template_name = "core/object_form.html"
    page_title = "Новый подрядчик"
    success_message = "Подрядчик создан."
    success_url = reverse_lazy("core:vendors")
    cancel_url = reverse_lazy("core:vendors")


class VendorUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = Vendor
    form_class = VendorForm
    template_name = "core/object_form.html"
    page_title = "Редактирование подрядчика"
    success_message = "Подрядчик обновлён."
    success_url = reverse_lazy("core:vendors")
    cancel_url = reverse_lazy("core:vendors")


class VendorDeleteView(DeleteView):
    model = Vendor
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:vendors")


class ServicePackageCreateView(CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = ServicePackage
    form_class = ServicePackageForm
    template_name = "core/object_form.html"
    page_title = "Новый пакет"
    success_message = "Пакет услуг создан."
    success_url = reverse_lazy("core:packages")
    cancel_url = reverse_lazy("core:packages")


class ServicePackageUpdateView(CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = ServicePackage
    form_class = ServicePackageForm
    template_name = "core/object_form.html"
    page_title = "Редактирование пакета"
    success_message = "Пакет услуг обновлён."
    success_url = reverse_lazy("core:packages")
    cancel_url = reverse_lazy("core:packages")


class ServicePackageDeleteView(DeleteView):
    model = ServicePackage
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:packages")
