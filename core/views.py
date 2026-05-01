from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Count, Sum
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import (
    ClientForm,
    EventCommunicationForm,
    EventDocumentForm,
    EventExpenseForm,
    EventForm,
    EventFormatForm,
    EventTaskForm,
    EventVendorForm,
    LeadForm,
    PipelineStageForm,
    ServicePackageForm,
    VendorForm,
)

from .models import (
    Client,
    Event,
    EventCommunication,
    EventDocument,
    EventExpense,
    EventFormat,
    EventTask,
    EventVendor,
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


class EventDetailView(DetailView):
    model = Event
    template_name = "core/event_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        return (
            Event.objects.select_related("client", "lead", "event_format", "manager")
            .prefetch_related(
                "tasks__responsible",
                "expenses",
                "event_vendors__vendor",
                "communications__manager",
                "documents",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        active_tab = self.request.GET.get("tab", "tasks")
        if active_tab not in {"tasks", "expenses", "vendors", "communications", "documents"}:
            active_tab = "tasks"
        task_filter = self.request.GET.get("task_filter", "all")
        expense_filter = self.request.GET.get("expense_filter", "all")
        vendor_filter = self.request.GET.get("vendor_filter", "all")
        communication_filter = self.request.GET.get("communication_filter", "all")
        document_filter = self.request.GET.get("document_filter", "all")

        tasks = self.object.tasks.select_related("responsible").all()
        expenses = self.object.expenses.all()
        event_vendors = self.object.event_vendors.select_related("vendor").all()
        communications = self.object.communications.select_related("manager").all()
        documents = self.object.documents.all()

        if task_filter == "open":
            tasks = tasks.exclude(status=EventTask.Status.DONE)
        elif task_filter == "overdue":
            tasks = tasks.exclude(status=EventTask.Status.DONE).filter(deadline__lt=today)
        elif task_filter == "done":
            tasks = tasks.filter(status=EventTask.Status.DONE)

        if expense_filter in {choice[0] for choice in EventExpense.PaymentStatus.choices}:
            expenses = expenses.filter(payment_status=expense_filter)

        if vendor_filter in {choice[0] for choice in EventVendor.Status.choices}:
            event_vendors = event_vendors.filter(status=vendor_filter)

        if communication_filter in {choice[0] for choice in EventCommunication.Type.choices}:
            communications = communications.filter(communication_type=communication_filter)

        if document_filter in {choice[0] for choice in EventDocument.Status.choices}:
            documents = documents.filter(status=document_filter)

        context["today"] = today
        context["active_tab"] = active_tab
        context["task_filter"] = task_filter
        context["expense_filter"] = expense_filter
        context["vendor_filter"] = vendor_filter
        context["communication_filter"] = communication_filter
        context["document_filter"] = document_filter
        context["detail_tasks"] = tasks
        context["detail_expenses"] = expenses
        context["detail_event_vendors"] = event_vendors
        context["detail_communications"] = communications
        context["detail_documents"] = documents
        context["overdue_tasks_count"] = self.object.tasks.exclude(status=EventTask.Status.DONE).filter(
            deadline__lt=today
        ).count()
        return context


class TaskListView(ListView):
    model = EventTask
    template_name = "core/tasks.html"
    context_object_name = "tasks"

    def get_queryset(self):
        today = timezone.localdate()
        queryset = EventTask.objects.select_related("event", "responsible").order_by("deadline", "id")
        task_filter = self.request.GET.get("filter", "all")

        if task_filter == "open":
            queryset = queryset.exclude(status=EventTask.Status.DONE)
        elif task_filter == "overdue":
            queryset = queryset.exclude(status=EventTask.Status.DONE).filter(deadline__lt=today)
        elif task_filter == "done":
            queryset = queryset.filter(status=EventTask.Status.DONE)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        active_filter = self.request.GET.get("filter", "all")
        context["today"] = today
        context["active_filter"] = active_filter
        context["task_stats"] = {
            "total": EventTask.objects.count(),
            "open": EventTask.objects.exclude(status=EventTask.Status.DONE).count(),
            "overdue": EventTask.objects.exclude(status=EventTask.Status.DONE).filter(deadline__lt=today).count(),
            "done": EventTask.objects.filter(status=EventTask.Status.DONE).count(),
        }
        return context


class TaskDetailView(DetailView):
    model = EventTask
    template_name = "core/task_detail.html"
    context_object_name = "task"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context["today"] = today
        context["is_overdue"] = bool(
            self.object.deadline and self.object.deadline < today and self.object.status != EventTask.Status.DONE
        )
        context["is_due_today"] = bool(
            self.object.deadline and self.object.deadline == today and self.object.status != EventTask.Status.DONE
        )
        return context


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


class EventScopedFormMixin:
    event_kwarg = "event_pk"
    return_tab = "tasks"

    def dispatch(self, request, *args, **kwargs):
        self.parent_event = None
        event_pk = kwargs.get(self.event_kwarg)
        if event_pk:
            self.parent_event = get_object_or_404(Event, pk=event_pk)
        return super().dispatch(request, *args, **kwargs)

    def get_event_detail_url(self, event):
        return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.return_tab}"

    def get_return_tab(self):
        return self.request.GET.get("return_tab") or self.request.POST.get("return_tab") or self.return_tab

    def get_initial(self):
        initial = super().get_initial()
        if self.parent_event:
            initial["event"] = self.parent_event
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.parent_event and "event" in form.fields:
            form.fields["event"].initial = self.parent_event
            form.fields["event"].queryset = Event.objects.filter(pk=self.parent_event.pk)
            form.fields["event"].disabled = True
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return_tab"] = self.get_return_tab()
        return context

    def form_valid(self, form):
        if self.parent_event and "event" in form.fields:
            form.instance.event = self.parent_event
        return super().form_valid(form)

    def get_cancel_url(self):
        if self.parent_event:
            return f"{reverse('core:event_detail', kwargs={'pk': self.parent_event.pk})}?tab={self.get_return_tab()}"
        event = getattr(getattr(self, "object", None), "event", None)
        if event:
            return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.get_return_tab()}"
        return super().get_cancel_url()

    def get_success_url(self):
        event = self.parent_event or getattr(getattr(self, "object", None), "event", None)
        if event:
            return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.get_return_tab()}"
        return super().get_success_url()


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


class TaskCreateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventTask
    form_class = EventTaskForm
    template_name = "core/object_form.html"
    return_tab = "tasks"
    page_title = "Новая задача"
    success_message = "Задача создана."
    success_url = reverse_lazy("core:tasks")
    cancel_url = reverse_lazy("core:tasks")


class TaskUpdateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventTask
    form_class = EventTaskForm
    template_name = "core/object_form.html"
    return_tab = "tasks"
    page_title = "Редактирование задачи"
    success_message = "Задача обновлена."
    success_url = reverse_lazy("core:tasks")
    cancel_url = reverse_lazy("core:tasks")


class TaskDeleteView(DeleteView):
    model = EventTask
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        return reverse("core:event_detail", kwargs={"pk": self.object.event.pk})


class TaskStatusUpdateView(View):
    allowed_statuses = {choice[0] for choice in EventTask.Status.choices}

    def post(self, request, pk):
        task = get_object_or_404(EventTask, pk=pk)
        status = request.POST.get("status")
        if status in self.allowed_statuses:
            task.status = status
            task.save(update_fields=["status"])
            messages.success(request, "Статус задачи обновлён.")
        return redirect(f"{reverse('core:event_detail', kwargs={'pk': task.event.pk})}?tab=tasks")


class EventExpenseCreateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventExpense
    form_class = EventExpenseForm
    template_name = "core/object_form.html"
    return_tab = "expenses"
    page_title = "Новый расход"
    success_message = "Расход добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventExpenseUpdateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventExpense
    form_class = EventExpenseForm
    template_name = "core/object_form.html"
    return_tab = "expenses"
    page_title = "Редактирование расхода"
    success_message = "Расход обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventVendorCreateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventVendor
    form_class = EventVendorForm
    template_name = "core/object_form.html"
    return_tab = "vendors"
    page_title = "Новый подрядчик мероприятия"
    success_message = "Подрядчик добавлен в мероприятие."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventVendorUpdateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventVendor
    form_class = EventVendorForm
    template_name = "core/object_form.html"
    return_tab = "vendors"
    page_title = "Редактирование подрядчика мероприятия"
    success_message = "Подрядчик мероприятия обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventVendorStatusUpdateView(View):
    allowed_statuses = {choice[0] for choice in EventVendor.Status.choices}

    def post(self, request, pk):
        assignment = get_object_or_404(EventVendor, pk=pk)
        status = request.POST.get("status")
        if status in self.allowed_statuses:
            assignment.status = status
            assignment.save(update_fields=["status"])
            messages.success(request, "Статус подрядчика обновлён.")
        return redirect(f"{reverse('core:event_detail', kwargs={'pk': assignment.event.pk})}?tab=vendors")


class EventCommunicationCreateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventCommunication
    form_class = EventCommunicationForm
    template_name = "core/object_form.html"
    return_tab = "communications"
    page_title = "Новая коммуникация"
    success_message = "Коммуникация добавлена."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventCommunicationUpdateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventCommunication
    form_class = EventCommunicationForm
    template_name = "core/object_form.html"
    return_tab = "communications"
    page_title = "Редактирование коммуникации"
    success_message = "Коммуникация обновлена."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventDocumentCreateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    model = EventDocument
    form_class = EventDocumentForm
    template_name = "core/object_form.html"
    return_tab = "documents"
    page_title = "Новый документ"
    success_message = "Документ добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventDocumentUpdateView(EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    model = EventDocument
    form_class = EventDocumentForm
    template_name = "core/object_form.html"
    return_tab = "documents"
    page_title = "Редактирование документа"
    success_message = "Документ обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


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
