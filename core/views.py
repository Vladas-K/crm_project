import calendar
from decimal import Decimal
from itertools import islice
from urllib.parse import parse_qs, urlsplit

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Avg, Case, Count, DecimalField, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import (
    ClientForm,
    EventCommunicationForm,
    EventDocumentForm,
    EventDirectoryFilterForm,
    EventExpenseForm,
    EventForm,
    EventFormatForm,
    EventOutcomeForm,
    EventRiskForm,
    EventTaskForm,
    EventTimelineItemForm,
    EventVendorForm,
    LeadForm,
    LeadStageForm,
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
    EventOutcome,
    EventRisk,
    EventTask,
    EventTimelineItem,
    EventVendor,
    Lead,
    PipelineStage,
    ServicePackage,
    TeamMemberProfile,
    Vendor,
    VendorRole,
    normalize_russian_phone,
    social_profile_url,
)

User = get_user_model()


def lead_matches_search(lead, query):
    """Проверяет совпадение запроса без учёта регистра, включая кириллицу."""

    normalized_query = query.casefold()
    return any(
        normalized_query in (value or "").casefold()
        for value in (lead.name, lead.phone, lead.email)
    )


def client_matches_search(client, query):
    """Проверяет совпадение запроса без учёта регистра в данных клиента."""

    normalized_query = query.casefold()
    text_match = any(
        normalized_query in (value or "").casefold()
        for value in (client.name, client.phone, client.email, client.contacts, client.telegram, client.whatsapp,
                      client.max_messenger, client.instagram, client.facebook, client.vk, client.messenger)
    )
    if text_match:
        return True
    # Сравниваем телефон независимо от оформления, сохраняя поиск имён на кириллице.
    if not all(character.isdigit() or character in "+()- ." for character in query):
        return False
    phone_query = client_phone_digits(query)
    return len(phone_query) >= 3 and any(
        phone_query in client_phone_digits(value) for value in (client.phone, client.whatsapp)
    )


def client_phone_digits(value):
    digits = "".join(character for character in value if character.isdigit())
    return f"7{digits[1:]}" if len(digits) == 11 and digits.startswith("8") else digits


def client_contact_items(client):
    """Готовит структурированные контакты для списка и профиля клиента."""

    items = []
    for field, label, kind in (
        ("phone", "Телефон", "phone"), ("email", "Email", "email"),
        ("telegram", "Telegram", "telegram"), ("whatsapp", "WhatsApp", "whatsapp"),
        ("max_messenger", "MAX", "max"), ("instagram", "Instagram", "instagram"),
        ("facebook", "Facebook", "facebook"), ("vk", "ВКонтакте", "vk"),
    ):
        value = getattr(client, field).strip()
        if not value:
            continue
        url = ""
        if field == "phone":
            url = f"tel:{value}"
        elif field == "email":
            url = f"mailto:{value}"
        elif value.startswith(("http://", "https://")):
            url = value
        elif field == "telegram":
            url = social_profile_url(value, "t.me")
        elif field == "whatsapp":
            digits = "".join(character for character in normalize_russian_phone(value) if character.isdigit())
            url = f"https://wa.me/{digits}" if digits else ""
        elif field in {"instagram", "facebook", "vk"}:
            url = social_profile_url(value, f"{field}.com")
        items.append({"kind": kind, "label": label, "value": value, "url": url,
                      "external": field not in {"phone", "email"}})
    return items


def event_matches_search(event, query):
    """Проверяет совпадение запроса в названии, городе или имени клиента."""

    normalized_query = query.casefold()
    return any(
        normalized_query in (value or "").casefold()
        for value in (event.title, event.city, event.client.name)
    )


def vendor_matches_search(vendor, query):
    """Проверяет совпадение запроса в профиле и контактах подрядчика."""

    normalized_query = query.casefold()
    return any(
        normalized_query in (value or "").casefold()
        for value in (
            vendor.name,
            vendor.role_label,
            vendor.contact_person,
            vendor.contact_position,
            vendor.phone,
            vendor.email,
            vendor.website,
            vendor.telegram,
            vendor.whatsapp,
            vendor.max_messenger,
            vendor.instagram,
            vendor.facebook,
            vendor.vk,
            vendor.social_links,
            vendor.service_area,
        )
    )


def pipeline_stage_color(stage):
    """Возвращает спокойный цвет для этапа воронки по его смыслу."""

    if stage.is_lost:
        return "rgba(225, 29, 72, 0.78)"
    if stage.probability >= 80:
        return "rgba(15, 159, 110, 0.78)"
    if stage.probability >= 50:
        return "rgba(217, 119, 6, 0.78)"
    if stage.order <= 1:
        return "rgba(100, 116, 139, 0.78)"
    return "rgba(31, 111, 235, 0.78)"


def shift_months(value, offset):
    """Сдвигает дату на указанное число месяцев, сохраняя первый день месяца."""

    month_index = value.month - 1 + offset
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=1)


def analytics_period_bounds(period):
    """Возвращает границы выбранного периода или ``(None, None)`` для всего периода."""

    if period not in {"6m", "12m"}:
        return None, None

    today = timezone.localdate()
    months_count = 6 if period == "6m" else 12
    return shift_months(today, -(months_count - 1)), today


class CRMLoginRequiredMixin(LoginRequiredMixin):
    """Требует авторизацию для CRM-страниц и действий."""


class CRMAccessMixin(CRMLoginRequiredMixin):
    """Проверяет CRM-профиль пользователя и требуемый флаг доступа."""

    required_profile_flag = None
    required_profile_flags = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        try:
            profile = request.user.crm_profile
        except TeamMemberProfile.DoesNotExist as exc:
            raise PermissionDenied("Для пользователя не настроен CRM-профиль.") from exc

        required_flags = self.required_profile_flags or ((self.required_profile_flag,) if self.required_profile_flag else ())
        if any(not getattr(profile, flag) for flag in required_flags):
            raise PermissionDenied("Недостаточно прав для доступа к разделу.")

        return super().dispatch(request, *args, **kwargs)


class ClientAccessMixin(CRMAccessMixin):
    """Требует доступ к клиентскому разделу."""

    required_profile_flag = "can_view_clients"


class AnalyticsAccessMixin(CRMAccessMixin):
    """Требует доступ к аналитике."""

    required_profile_flag = "can_view_analytics"


class SystemAccessMixin(CRMAccessMixin):
    """Требует право на управление системными настройками."""

    required_profile_flag = "can_manage_system"


class FinanceAccessMixin(CRMAccessMixin):
    """Требует право на управление финансовыми данными."""

    required_profile_flag = "can_view_finance"


class LeadManagementMixin(CRMAccessMixin):
    """Требует право на создание и редактирование лидов."""

    required_profile_flag = "can_manage_leads"


class ClientManagementMixin(CRMAccessMixin):
    """Требует право на создание и редактирование клиентов."""

    required_profile_flags = ("can_view_clients", "can_manage_clients")


class EventManagementMixin(CRMAccessMixin):
    """Требует право на изменение мероприятия и его рабочих данных."""

    required_profile_flag = "can_manage_events"


class FinanceFormMixin:
    """Передаёт финансовое право из CRM-профиля в формы мероприятий и итогов."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        profile = getattr(self.request.user, "crm_profile", None)
        kwargs["can_view_finance"] = bool(profile and profile.can_view_finance)
        return kwargs


class DashboardView(CRMLoginRequiredMixin, TemplateView):
    """Показывает главную сводку CRM: KPI, последние лиды, события и задачи."""

    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        overdue_tasks = EventTask.objects.select_related("event", "responsible").exclude(
            status=EventTask.Status.DONE
        ).filter(deadline__lt=today).order_by("deadline", "id")
        unanswered_leads = Lead.objects.select_related("stage", "manager").filter(
            last_contact_at__isnull=True,
            created_at__lt=timezone.now() - timezone.timedelta(hours=24),
        ).order_by("created_at", "id")
        attention_sections = []
        if overdue_tasks.exists():
            attention_sections.append(
                {
                    "kind": "tasks",
                    "title": "Просроченные задачи",
                    "description": "Задачи, по которым уже прошёл срок выполнения.",
                    "items": overdue_tasks[:5],
                    "count": overdue_tasks.count(),
                }
            )
        if unanswered_leads.exists():
            attention_sections.append(
                {
                    "kind": "leads",
                    "title": "Лиды без ответа",
                    "description": "Новые обращения, с которыми не было контакта более 24 часов.",
                    "items": unanswered_leads[:5],
                    "count": unanswered_leads.count(),
                }
            )
        active_event_statuses = [Event.Status.PLANNING, Event.Status.IN_PROGRESS]
        risky_events = Event.objects.select_related("client").filter(
            risks__isnull=False,
            status__in=active_event_statuses,
        ).distinct().order_by("date", "id")
        events_without_outcome = Event.objects.select_related("client").filter(
            outcome__isnull=True,
            status__in=active_event_statuses,
        ).order_by("date", "id")
        events_without_manager = Event.objects.select_related("client").filter(
            manager__isnull=True,
            status__in=active_event_statuses,
        ).order_by("date", "id")
        if risky_events.exists():
            attention_sections.append(
                {
                    "kind": "risks",
                    "title": "Мероприятия с рисками",
                    "description": "Проекты, в которых зафиксированы потенциальные проблемы.",
                    "items": risky_events[:5],
                    "count": risky_events.count(),
                }
            )
        if events_without_outcome.exists():
            attention_sections.append(
                {
                    "kind": "outcomes",
                    "title": "Мероприятия без итогов",
                    "description": "Проекты, по которым ещё не заполнена финальная оценка.",
                    "items": events_without_outcome[:5],
                    "count": events_without_outcome.count(),
                }
            )
        if events_without_manager.exists():
            attention_sections.append(
                {
                    "kind": "unassigned",
                    "title": "Мероприятия без ответственного",
                    "description": "Активные проекты, которым ещё не назначен менеджер.",
                    "items": events_without_manager[:5],
                    "count": events_without_manager.count(),
                }
            )
        context["attention_sections"] = attention_sections
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


class LeadListView(CRMLoginRequiredMixin, ListView):
    """Отображает список лидов с поиском и фильтрами по этапу и менеджеру."""

    model = Lead
    template_name = "core/leads.html"
    context_object_name = "leads"
    def get_queryset(self):
        """Фильтрует лиды по поисковому запросу, этапу и ответственному."""

        queryset = Lead.objects.select_related("stage", "manager", "preliminary_event_format")
        search_query = self.request.GET.get("q", "").strip()
        stage_filter = self.request.GET.get("stage", "")
        manager_filter = self.request.GET.get("manager", "")
        source_filter = self.request.GET.get("source", "")
        attention_filter = self.request.GET.get("attention", "")
        sort = self.request.GET.get("sort", "newest")

        if stage_filter.isdigit():
            queryset = queryset.filter(stage_id=stage_filter)
        elif stage_filter == "unassigned":
            queryset = queryset.filter(stage__isnull=True)
        if manager_filter.isdigit():
            queryset = queryset.filter(manager_id=manager_filter)
        elif manager_filter == "unassigned":
            queryset = queryset.filter(manager__isnull=True)
        if source_filter:
            queryset = queryset.filter(source=source_filter)
        if attention_filter == "needs_response":
            queryset = queryset.filter(
                last_contact_at__isnull=True,
                created_at__lt=timezone.now() - timezone.timedelta(hours=24),
            )

        if sort == "oldest":
            queryset = queryset.order_by("created_at", "id")
        elif sort == "probability":
            queryset = queryset.order_by("-probability", "-created_at", "id")
        elif sort == "attention":
            attention_deadline = timezone.now() - timezone.timedelta(hours=24)
            queryset = queryset.annotate(
                attention_priority=Case(
                    When(last_contact_at__isnull=True, created_at__lt=attention_deadline, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            ).order_by("attention_priority", "created_at", "id")
        else:
            sort = "newest"
            queryset = queryset.order_by("-created_at", "id")

        if search_query:
            queryset = [lead for lead in queryset if lead_matches_search(lead, search_query)]

        return queryset

    def get_context_data(self, **kwargs):
        """Передаёт в шаблон значения фильтров и доступные варианты выбора."""

        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        context["stage_filter"] = self.request.GET.get("stage", "")
        context["manager_filter"] = self.request.GET.get("manager", "")
        context["source_filter"] = self.request.GET.get("source", "")
        context["attention_filter"] = self.request.GET.get("attention", "")
        context["lead_sort"] = self.request.GET.get("sort", "newest")
        if context["lead_sort"] not in {"newest", "oldest", "probability", "attention"}:
            context["lead_sort"] = "newest"
        context["pipeline_stages"] = PipelineStage.objects.order_by("order", "name")
        context["lead_managers"] = User.objects.filter(assigned_leads__isnull=False).distinct().order_by("username")
        context["lead_sources"] = (
            Lead.objects.exclude(source="").values_list("source", flat=True).distinct().order_by("source")
        )
        context["lead_selected_stage"] = PipelineStage.objects.filter(pk=context["stage_filter"]).first() if context["stage_filter"].isdigit() else None
        context["lead_selected_manager"] = User.objects.filter(pk=context["manager_filter"]).first() if context["manager_filter"].isdigit() else None

        all_leads = Lead.objects.all()
        attention_deadline = timezone.now() - timezone.timedelta(hours=24)
        average_probability = all_leads.aggregate(value=Avg("probability"))["value"] or 0
        context["lead_metrics"] = {
            "total": all_leads.count(),
            "recent": all_leads.filter(created_at__gte=timezone.now() - timezone.timedelta(days=7)).count(),
            "needs_response": all_leads.filter(
                last_contact_at__isnull=True,
                created_at__lt=attention_deadline,
            ).count(),
            "average_probability": round(average_probability),
        }
        return context


class LeadDetailView(CRMLoginRequiredMixin, DetailView):
    """Показывает контактные данные, этап и состояние SLA отдельного лида."""

    model = Lead
    template_name = "core/lead_detail.html"
    context_object_name = "lead"
    queryset = Lead.objects.select_related(
        "stage",
        "manager",
        "preliminary_event_format",
    )


class LeadAutocompleteView(CRMLoginRequiredMixin, View):
    """Возвращает короткий список совпадений для подсказок в поиске лидов."""

    def get(self, request):
        """Ищет лиды по имени, телефону или email после двух символов."""

        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        leads = [
            lead
            for lead in Lead.objects.order_by("name", "id")
            if lead_matches_search(lead, query)
        ][:8]
        return JsonResponse(
            {
                "results": [
                    {
                        "id": lead.pk,
                        "name": lead.name,
                        "phone": lead.phone,
                        "email": lead.email,
                    }
                    for lead in leads
                ]
            }
        )


class PipelineView(CRMLoginRequiredMixin, TemplateView):
    """Обзор лидов по этапам с ограниченными превью и полными списками."""

    template_name = "core/pipeline.html"
    preview_limit = 4

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_stages = list(PipelineStage.objects.all())
        stage_filter = self.request.GET.get("stage", "")
        manager_filter = self.request.GET.get("manager", "")
        query = self.request.GET.get("q", "").strip()
        attention = self.request.GET.get("attention", "")
        if stage_filter not in {str(stage.pk) for stage in all_stages} | {"unassigned"}:
            stage_filter = ""
        if not manager_filter.isdigit() and manager_filter != "unassigned":
            manager_filter = ""
        if attention != "needs_response":
            attention = ""
        leads = Lead.objects.select_related("manager", "stage")
        if stage_filter == "unassigned":
            leads = leads.filter(stage__isnull=True)
        elif stage_filter:
            leads = leads.filter(stage_id=stage_filter)
        if manager_filter == "unassigned":
            leads = leads.filter(manager__isnull=True)
        elif manager_filter:
            leads = leads.filter(manager_id=manager_filter)
        attention_query = Q(last_contact_at__isnull=True, created_at__lt=timezone.now() - timezone.timedelta(hours=24))
        if attention:
            leads = leads.filter(attention_query)
        if query:
            # SQLite не обеспечивает нужный поиск кириллицы через обычный icontains.
            matches = [lead.pk for lead in leads.iterator() if lead_matches_search(lead, query)]
            leads = leads.filter(pk__in=matches)
        stages = PipelineStage.objects.annotate(
            board_count=Count("leads", filter=Q(leads__in=leads)),
        ).order_by("order", "pk").prefetch_related(Prefetch(
            "leads", queryset=leads.order_by("-created_at", "-pk")[:self.preview_limit], to_attr="board_leads",
        ))
        if stage_filter == "unassigned":
            stages = stages.none()
        elif stage_filter:
            stages = stages.filter(pk=stage_filter)
        filters = {"q": query, "manager": manager_filter, "attention": attention}

        def all_leads_url(stage_key):
            return f"{reverse('core:leads')}?{urlencode({key: value for key, value in dict(filters, stage=stage_key).items() if value})}"

        groups = []
        unassigned = leads.filter(stage__isnull=True)
        unassigned_count = unassigned.count()
        if unassigned_count or stage_filter == "unassigned":
            groups.append({"stage": None, "name": "Без этапа", "total": unassigned_count,
                           "leads": list(unassigned.order_by("-created_at", "-pk")[:self.preview_limit]),
                           "all_url": all_leads_url("unassigned")})
        stage_list = list(stages)
        groups.extend({"stage": stage, "name": stage.name, "total": stage.board_count,
                       "leads": stage.board_leads, "all_url": all_leads_url(str(stage.pk))} for stage in stage_list)
        selected_stage = next((stage for stage in all_stages if str(stage.pk) == stage_filter), None)
        params = {key: value for key, value in dict(filters, stage=stage_filter).items() if value}
        context.update({
            "stages": stage_list, "pipeline_stages": all_stages, "pipeline_groups": groups,
            "search_query": query, "stage_filter": stage_filter, "manager_filter": manager_filter,
            "attention_filter": attention, "has_filters": bool(params), "pipeline_query": urlencode(params),
            "selected_stage": selected_stage,
            "selected_manager": User.objects.filter(pk=manager_filter).first() if manager_filter.isdigit() else None,
            "pipeline_managers": User.objects.filter(assigned_leads__isnull=False).distinct().order_by("username"),
            "filtered_count": leads.count(),
            "pipeline_metrics": Lead.objects.aggregate(
                total=Count("pk"), needs_response=Count("pk", filter=attention_query),
                unassigned=Count("pk", filter=Q(stage__isnull=True)),
            ),
        })
        return context




class ClientListView(ClientAccessMixin, ListView):
    """Показывает каталог клиентов с фильтрами и постраничной навигацией."""

    model = Client
    template_name = "core/clients.html"
    context_object_name = "clients"
    paginate_by = 20
    sort_options = {
        "name": ("name", "pk"),
        "newest": ("-created_at", "-pk"),
        "oldest": ("created_at", "pk"),
        "events": ("-events_count", "name", "pk"),
    }

    def get_queryset(self):
        queryset = Client.objects.select_related("lead", "manager").annotate(events_count=Count("events"))
        self.search_query = self.request.GET.get("q", "").strip()
        self.client_type = self.request.GET.get("client_type", "")
        self.segment = self.request.GET.get("segment", "")
        self.manager_filter = self.request.GET.get("manager", "")
        self.sort = self.request.GET.get("sort", "name")
        if self.client_type not in dict(Client.ClientType.choices):
            self.client_type = ""
        if self.segment not in dict(Client.Segment.choices):
            self.segment = ""
        if self.sort not in self.sort_options:
            self.sort = "name"
        if self.client_type:
            queryset = queryset.filter(client_type=self.client_type)
        if self.segment:
            queryset = queryset.filter(segment=self.segment)
        if self.manager_filter == "unassigned":
            queryset = queryset.filter(manager__isnull=True)
        elif self.manager_filter.isdigit():
            queryset = queryset.filter(manager_id=self.manager_filter)
        else:
            self.manager_filter = ""
        queryset = queryset.order_by(*self.sort_options[self.sort])
        if self.search_query:
            # Python casefold сохраняет корректный поиск кириллицы в локальной SQLite.
            return [item for item in queryset.iterator() if client_matches_search(item, self.search_query)]
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for item in context["clients"]:
            item.contact_items = client_contact_items(item)
        managers = User.objects.filter(managed_clients__isnull=False).distinct().order_by("username")
        selected_manager = next((item for item in managers if str(item.pk) == self.manager_filter), None)
        context.update({
            "search_query": self.search_query,
            "client_type_filter": self.client_type,
            "client_segment_filter": self.segment,
            "client_manager_filter": self.manager_filter,
            "client_sort": self.sort,
            "client_types": Client.ClientType.choices,
            "client_segments": Client.Segment.choices,
            "client_managers": managers,
            "selected_type": dict(Client.ClientType.choices).get(self.client_type),
            "selected_segment": dict(Client.Segment.choices).get(self.segment),
            "selected_manager": selected_manager,
            "has_filters": bool(self.search_query or self.client_type or self.segment or self.manager_filter),
            "client_metrics": Client.objects.aggregate(
                total=Count("pk"),
                companies=Count("pk", filter=Q(client_type=Client.ClientType.B2B)),
                individuals=Count("pk", filter=Q(client_type=Client.ClientType.B2C)),
                vip=Count("pk", filter=Q(segment=Client.Segment.VIP)),
            ),
        })
        params = self.request.GET.copy()
        params.pop("page", None)
        context["pagination_query"] = params.urlencode()
        return context


class ClientDetailView(ClientAccessMixin, DetailView):
    """Карточка клиента, доступная сотрудникам с правом просмотра клиентов."""

    model = Client
    template_name = "core/client_detail.html"
    context_object_name = "crm_client"

    def get_queryset(self):
        return Client.objects.select_related("lead", "manager")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["contact_items"] = client_contact_items(self.object)
        context["client_events"] = self.object.events.select_related("event_format").order_by("-date", "-pk")
        context["events_count"] = context["client_events"].count()
        return context


class ClientAutocompleteView(ClientAccessMixin, View):
    """Возвращает до восьми совпадений с прямыми ссылками на карточки."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        matches = (
            item for item in Client.objects.order_by("name", "pk").iterator()
            if client_matches_search(item, query)
        ) if len(query) >= 2 else ()
        response = JsonResponse({"results": [
            {"id": item.pk, "name": item.name, "phone": item.phone, "email": item.email,
             "url": reverse("core:client_detail", kwargs={"pk": item.pk})}
            for item in islice(matches, 8)
        ]})
        response["Cache-Control"] = "no-store"
        return response


class EventListView(CRMLoginRequiredMixin, ListView):
    """Показывает рабочий каталог с проверенными фильтрами и постраничной сводкой."""

    model = Event
    template_name = "core/events.html"
    context_object_name = "events"
    paginate_by = 20
    sort_options = {
        "date_asc": ("date", "pk"),
        "date_desc": ("-date", "-pk"),
        "created_desc": ("-created_at", "-pk"),
    }
    active_statuses = (Event.Status.PLANNING, Event.Status.IN_PROGRESS)

    def get_queryset(self):
        self.today = timezone.localdate()
        self.filter_form = EventDirectoryFilterForm(self.request.GET)
        form_valid = self.filter_form.is_valid()
        filters = self.filter_form.cleaned_data
        self.scope = filters.get("scope", "active")
        self.period = filters.get("period", "all")
        self.sort = filters.get("sort", "date_asc")
        self.can_view_finance = bool(getattr(getattr(self.request.user, "crm_profile", None), "can_view_finance", False))
        queryset = Event.objects.select_related("client", "lead", "event_format", "manager")
        if not form_valid:
            return queryset.none().order_by(*self.sort_options[self.sort])
        if self.scope == "active":
            queryset = queryset.filter(status__in=self.active_statuses)
        elif self.scope == "archive":
            queryset = queryset.filter(status__in=(Event.Status.COMPLETED, Event.Status.CANCELLED))
        if filters["status"]:
            queryset = queryset.filter(status=filters["status"])
        if filters["event_format"]:
            queryset = queryset.filter(event_format_id=filters["event_format"])
        if self.period == "this_month":
            queryset = queryset.filter(
                date__gte=self.today.replace(day=1),
                date__lte=self.today.replace(day=calendar.monthrange(self.today.year, self.today.month)[1]),
            )
        elif self.period == "next_30":
            queryset = queryset.filter(date__gte=self.today, date__lte=self.today + timezone.timedelta(days=29))
        elif self.period == "custom":
            if filters["date_from"]:
                queryset = queryset.filter(date__gte=filters["date_from"])
            if filters["date_to"]:
                queryset = queryset.filter(date__lte=filters["date_to"])
        if filters["manager"] == "unassigned":
            queryset = queryset.filter(manager__isnull=True)
        elif filters["manager"]:
            queryset = queryset.filter(manager_id=filters["manager"])
        attention_filter = filters["attention"]
        if attention_filter == "risks":
            queryset = queryset.filter(risks__isnull=False, status__in=self.active_statuses).distinct()
        elif attention_filter == "outcomes":
            queryset = queryset.filter(outcome__isnull=True, status__in=self.active_statuses)
        elif attention_filter == "unassigned_manager":
            queryset = queryset.filter(manager__isnull=True, status__in=self.active_statuses)
        elif attention_filter == "overdue_tasks":
            queryset = queryset.filter(
                tasks__deadline__lt=self.today,
                tasks__status__in=(EventTask.Status.TODO, EventTask.Status.IN_PROGRESS),
                status__in=self.active_statuses,
            ).distinct()
        if filters["q"]:
            # SQLite не поддерживает регистронезависимый поиск кириллицы штатным icontains.
            candidates = queryset.select_related(None).select_related("client").only("pk", "title", "city", "client__name")
            matching_ids = [event.pk for event in candidates.iterator() if event_matches_search(event, filters["q"])]
            queryset = queryset.filter(pk__in=matching_ids)
        return queryset.order_by(*self.sort_options[self.sort])

    @staticmethod
    def related_count(model, **filters):
        counts = model.objects.filter(event_id=OuterRef("pk"), **filters).order_by().values("event_id").annotate(
            total=Count("pk")
        ).values("total")[:1]
        return Coalesce(Subquery(counts, output_field=IntegerField()), Value(0))

    def annotate_page(self, queryset):
        """Считает сводку только для текущей страницы без перемножения связей."""

        annotations = {
            "open_tasks_count": self.related_count(EventTask, status__in=(EventTask.Status.TODO, EventTask.Status.IN_PROGRESS)),
            "overdue_tasks_count": self.related_count(
                EventTask, status__in=(EventTask.Status.TODO, EventTask.Status.IN_PROGRESS), deadline__lt=self.today,
            ),
            "vendors_count": self.related_count(EventVendor),
            "documents_count": self.related_count(EventDocument),
            "signed_documents_count": self.related_count(EventDocument, status=EventDocument.Status.SIGNED),
        }
        if self.can_view_finance:
            expenses = EventExpense.objects.filter(event_id=OuterRef("pk")).order_by().values("event_id").annotate(
                total=Sum("amount")
            ).values("total")[:1]
            amount_field = DecimalField(max_digits=14, decimal_places=2)
            annotations["directory_total_expenses"] = Coalesce(
                Subquery(expenses, output_field=amount_field), Value(Decimal("0")), output_field=amount_field,
            )
        return queryset.annotate(**annotations)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = self.annotate_page(context["events"])
        for event in events:
            event.directory_days_until = (event.date - self.today).days
            event.directory_active = event.status in self.active_statuses
            event.directory_date_overdue = event.directory_active and event.directory_days_until < 0
            event.directory_status_kind = {
                Event.Status.PLANNING: "soft", Event.Status.IN_PROGRESS: "",
                Event.Status.COMPLETED: "success", Event.Status.CANCELLED: "soft",
            }.get(event.status, "soft")
            if self.can_view_finance:
                budget = event.planned_budget
                event.directory_margin = ((budget - event.directory_total_expenses) / budget * 100) if budget else Decimal("0")
                formatted = format(budget, ",.0f" if budget == budget.to_integral_value() else ",.2f")
                event.directory_budget_display = formatted.replace(",", "\u00a0").replace(".", ",")
        context["events"] = context["object_list"] = context["page_obj"].object_list = events
        filters = self.filter_form.cleaned_data
        attention_filter = filters.get("attention", "")
        context.update({
            "filter_form": self.filter_form,
            "search_query": filters.get("q", self.filter_form.data.get("q", "")),
            "event_status_filter": filters.get("status", ""),
            "event_format_filter": filters.get("event_format", ""),
            "event_date_from": self.filter_form.data.get("date_from", ""),
            "event_date_to": self.filter_form.data.get("date_to", ""),
            "event_month_filter": self.request.GET.get("month", ""),
            "event_manager_filter": filters.get("manager", ""),
            "event_attention_filter": attention_filter,
            "event_scope": self.scope,
            "event_period": self.period,
            "event_sort": self.sort,
            "event_managers": self.filter_form.event_managers,
            "event_statuses": [
                (value, label) for value, label in Event.Status.choices
                if self.scope == "all" or (value in self.active_statuses) == (self.scope == "active")
            ],
            "event_formats": self.filter_form.event_formats,
            "filtered_count": context["paginator"].count,
            "advanced_filters_open": bool(
                filters.get("event_format") or filters.get("manager") or attention_filter or self.sort != "date_asc"
                or any(field in self.filter_form.errors for field in ("event_format", "manager", "attention", "sort"))
            ),
            "has_filters": bool(
                filters.get("q") or filters.get("status") or filters.get("event_format") or filters.get("manager")
                or attention_filter or self.period != "all" or self.scope != "active" or self.sort != "date_asc"
                or self.filter_form.errors
            ),
            "attention_label": {
                "risks": "Показаны мероприятия с рисками.",
                "outcomes": "Показаны мероприятия без заполненных итогов.",
                "unassigned_manager": "Показаны мероприятия без ответственного менеджера.",
                "overdue_tasks": "Показаны мероприятия с просроченными задачами.",
            }.get(attention_filter, ""),
        })
        params = self.request.GET.copy()
        params.pop("page", None)
        context["pagination_query"] = params.urlencode()
        scope_tabs = []
        for scope, label in EventDirectoryFilterForm.SCOPE_CHOICES:
            tab_params = params.copy()
            tab_params["scope"] = scope
            if scope == "archive":
                tab_params.pop("attention", None)
            status = filters.get("status")
            if (scope == "active" and status and status not in self.active_statuses) or (
                scope == "archive" and status in self.active_statuses
            ):
                tab_params.pop("status", None)
            scope_tabs.append({
                "label": label, "url": f"{reverse('core:events')}?{tab_params.urlencode()}", "active": self.scope == scope,
            })
        context["scope_tabs"] = scope_tabs
        return context


class EventAutocompleteView(CRMLoginRequiredMixin, View):
    """Возвращает совпадения для подсказок в поиске мероприятий."""

    def get(self, request):
        """Ищет мероприятия по названию, клиенту или городу после двух символов."""

        query = request.GET.get("q", "").strip()
        matches = (
            event for event in Event.objects.select_related("client").only("pk", "title", "city", "client__name").order_by(
                "date", "title", "id"
            ).iterator() if event_matches_search(event, query)
        ) if len(query) >= 2 else ()
        response = JsonResponse(
            {
                "results": [
                    {
                        "id": event.pk,
                        "title": event.title or str(event.client),
                        "client": str(event.client),
                        "city": event.city,
                        "url": reverse("core:event_detail", args=[event.pk]),
                    }
                    for event in islice(matches, 8)
                ]
            }
        )
        response["Cache-Control"] = "no-store"
        return response


class EventDetailView(CRMLoginRequiredMixin, DetailView):
    """Рабочая карточка мероприятия с вкладками, фильтрами и связанной операционной информацией."""

    model = Event
    template_name = "core/event_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        """Загружает мероприятие вместе со связанными блоками для карточки."""

        return (
            Event.objects.select_related("client", "lead", "event_format", "manager")
            .prefetch_related(
                "tasks__responsible",
                "timeline_items",
                "risks",
                "outcome",
                "expenses",
                "event_vendors__vendor",
                "communications__manager",
                "documents",
            )
        )

    def get_context_data(self, **kwargs):
        """Готовит вкладки, фильтры и статусную сводку карточки мероприятия."""

        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        try:
            can_view_finance = self.request.user.crm_profile.can_view_finance
        except TeamMemberProfile.DoesNotExist:
            can_view_finance = False

        active_tab = self.request.GET.get("tab", "tasks")
        if active_tab not in {
            "tasks",
            "timeline",
            "risks",
            "outcome",
            "expenses",
            "vendors",
            "communications",
            "documents",
        }:
            active_tab = "tasks"
        if active_tab == "expenses" and not can_view_finance:
            active_tab = "tasks"
        task_filter = self.request.GET.get("task_filter", "all")
        expense_filter = self.request.GET.get("expense_filter", "all")
        vendor_filter = self.request.GET.get("vendor_filter", "all")
        communication_filter = self.request.GET.get("communication_filter", "all")
        document_filter = self.request.GET.get("document_filter", "all")

        tasks = self.object.tasks.select_related("responsible").all()
        timeline_items = self.object.timeline_items.all()
        risks = self.object.risks.all()
        outcome = getattr(self.object, "outcome", None)
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
        context["event_date_overdue"] = (
            self.object.date < today
            and self.object.status in {Event.Status.PLANNING, Event.Status.IN_PROGRESS}
        )
        context["active_tab"] = active_tab
        context["task_filter"] = task_filter
        context["expense_filter"] = expense_filter
        context["vendor_filter"] = vendor_filter
        context["communication_filter"] = communication_filter
        context["document_filter"] = document_filter
        context["detail_tasks"] = tasks
        context["detail_timeline_items"] = timeline_items
        context["detail_risks"] = risks
        context["event_outcome"] = outcome
        context["detail_expenses"] = expenses if can_view_finance else EventExpense.objects.none()
        context["detail_event_vendors"] = event_vendors
        context["detail_communications"] = communications
        context["detail_documents"] = documents
        context["event_status_summary"] = {
            "open_tasks": self.object.tasks.exclude(status=EventTask.Status.DONE).count(),
            "overdue_tasks": self.object.tasks.exclude(status=EventTask.Status.DONE).filter(deadline__lt=today).count(),
            "total_expenses": self.object.total_expenses,
            "approved_vendors": self.object.event_vendors.filter(status=EventVendor.Status.APPROVED).count(),
            "signed_documents": self.object.documents.filter(status=EventDocument.Status.SIGNED).count(),
        }
        context["overdue_tasks_count"] = self.object.tasks.exclude(status=EventTask.Status.DONE).filter(
            deadline__lt=today
        ).count()
        return context


TASK_FILTERS = {"all", "open", "overdue", "done"}
TASK_SORTS = {
    "priority": "Сначала открытые",
    "deadline": "По сроку: сначала ближайшие",
    "deadline_desc": "По сроку: сначала поздние",
    "newest": "Сначала новые",
}


def task_list_params(query):
    """Нормализует только поддерживаемые параметры списка задач."""
    params = {}
    search = query.get("q", "").strip()[:200]
    if search:
        params["q"] = search
    state = query.get("filter", "all")
    if state in TASK_FILTERS - {"all"}:
        params["filter"] = state
    event = query.get("event", "")
    if event.isascii() and event.isdecimal() and len(event) <= 18 and int(event) > 0:
        params["event"] = str(int(event))
    if query.get("mine") == "1":
        params["mine"] = "1"
    sort = query.get("sort", "priority")
    if sort in TASK_SORTS and sort != "priority":
        params["sort"] = sort
    page = query.get("page", "")
    if page.isascii() and page.isdecimal() and len(page) <= 9 and int(page) > 1:
        params["page"] = str(int(page))
    return params


def task_list_url(params):
    query = urlencode(params)
    return reverse("core:tasks") + (f"?{query}" if query else "")


def safe_task_return_url(value):
    """Разрешает возврат только в локальный список задач без произвольных URL."""
    try:
        target = urlsplit(value)
    except ValueError:
        return None
    if target.scheme or target.netloc or target.path != reverse("core:tasks"):
        return None
    query = {key: values[-1] for key, values in parse_qs(target.query).items()}
    return task_list_url(task_list_params(query))


class TaskListView(CRMLoginRequiredMixin, ListView):
    """Рабочий список задач с поиском, фильтрами, сортировкой и страницами."""

    model = EventTask
    template_name = "core/tasks.html"
    context_object_name = "tasks"
    paginate_by = 20

    def get_queryset(self):
        self.params = task_list_params(self.request.GET)
        today = timezone.localdate()
        queryset = EventTask.objects.select_related("event__client", "responsible")
        if self.params.get("event"):
            queryset = queryset.filter(event_id=self.params["event"])
        if self.params.get("mine"):
            queryset = queryset.filter(responsible=self.request.user)
        if self.params.get("q"):
            # SQLite не обеспечивает регистронезависимый поиск кириллицы.
            query = self.params["q"].casefold()
            ids = [task.pk for task in queryset if any(
                query in value.casefold() for value in
                (task.title, task.description, task.event.title, task.event.client.name)
            )]
            queryset = queryset.filter(pk__in=ids)
        self.task_scope = queryset
        state = self.params.get("filter", "all")
        if state == "open":
            queryset = queryset.exclude(status=EventTask.Status.DONE)
        elif state == "overdue":
            queryset = queryset.exclude(status=EventTask.Status.DONE).filter(deadline__lt=today)
        elif state == "done":
            queryset = queryset.filter(status=EventTask.Status.DONE)
        sort = self.params.get("sort", "priority")
        if sort == "newest":
            return queryset.order_by("-pk")
        if sort == "deadline_desc":
            return queryset.order_by(F("deadline").desc(nulls_last=True), "pk")
        if sort == "deadline":
            return queryset.order_by(F("deadline").asc(nulls_last=True), "pk")
        return queryset.annotate(
            done_order=Case(When(status=EventTask.Status.DONE, then=Value(1)), default=Value(0))
        ).order_by("done_order", F("deadline").asc(nulls_last=True), "pk")

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(queryset, page_size)
        page = paginator.get_page(self.params.get("page", "1"))
        return paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        params = self.params.copy()
        params.pop("page", None)
        active_filter = params.get("filter", "all")
        stats = self.task_scope.aggregate(
            total=Count("pk"),
            open=Count("pk", filter=~Q(status=EventTask.Status.DONE)),
            overdue=Count("pk", filter=~Q(status=EventTask.Status.DONE) & Q(deadline__lt=today)),
            done=Count("pk", filter=Q(status=EventTask.Status.DONE)),
        )
        tabs = []
        for value, label in (("all", "Всего задач"), ("open", "Открытые"),
                             ("overdue", "Просроченные"), ("done", "Завершённые")):
            tab_params = {key: item for key, item in params.items() if key != "filter"}
            if value != "all":
                tab_params["filter"] = value
            tabs.append({"url": task_list_url(tab_params), "label": label,
                         "count": stats["total" if value == "all" else value], "active": value == active_filter})
        return_params = params.copy()
        if context["page_obj"].number > 1:
            return_params["page"] = str(context["page_obj"].number)
        return_url = task_list_url(return_params)
        context.update(
            today=today, active_filter=active_filter, task_stats=stats, task_tabs=tabs,
            task_search=params.get("q", ""), task_event=params.get("event", ""),
            task_mine=params.get("mine") == "1", task_sort=params.get("sort", "priority"),
            task_sorts=TASK_SORTS.items(),
            task_events=Event.objects.select_related("client").order_by("date", "title", "pk"),
            pagination_query=urlencode(params), task_return_url=return_url,
            task_return_query=urlencode({"return_to": return_url}),
        )
        return context


class TaskDetailView(CRMLoginRequiredMixin, DetailView):
    """Показывает отдельную карточку задачи и ее состояние относительно дедлайна."""

    model = EventTask
    template_name = "core/task_detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return EventTask.objects.select_related("responsible", "event__client", "event__event_format")

    def get_context_data(self, **kwargs):
        """Добавляет флаги просрочки и дедлайна на сегодня."""

        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context["today"] = today
        context["is_overdue"] = bool(
            self.object.deadline and self.object.deadline < today and self.object.status != EventTask.Status.DONE
        )
        context["is_due_today"] = bool(
            self.object.deadline and self.object.deadline == today and self.object.status != EventTask.Status.DONE
        )
        return_url = safe_task_return_url(self.request.GET.get("return_to", ""))
        if return_url:
            context["task_return_url"] = return_url
            context["task_return_query"] = urlencode({"return_to": return_url})
        return context


class EventFormatListView(CRMLoginRequiredMixin, ListView):
    """Отображает список форматов мероприятий и их шаблонов."""

    model = EventFormat
    template_name = "core/formats.html"
    context_object_name = "formats"


class VendorListView(CRMLoginRequiredMixin, ListView):
    """Отображает справочник подрядчиков с поиском и фильтрами."""

    model = Vendor
    template_name = "core/vendors.html"
    context_object_name = "vendors"

    def get_queryset(self):
        """Фильтрует и сортирует подрядчиков для рабочего каталога."""

        queryset = Vendor.objects.prefetch_related("event_formats", "role_categories")
        search_query = self.request.GET.get("q", "").strip()
        blacklist_filter = self.request.GET.get("blacklisted", "")
        format_filter = self.request.GET.get("event_format", "")
        role_filter = self.request.GET.get("role", "")
        requested_sort = self.request.GET.get("sort", "name")

        if blacklist_filter in {"yes", "no"}:
            queryset = queryset.filter(blacklisted=blacklist_filter == "yes")
        if format_filter.isdigit():
            queryset = queryset.filter(event_formats__id=format_filter).distinct()
        if role_filter.isdigit():
            queryset = queryset.filter(role_categories__id=role_filter).distinct()

        ordering = {
            "name": ("name",),
            "rating": ("-rating", "name"),
            "reliability": ("-reliability", "name"),
            "cost": ("avg_cost", "name"),
        }
        try:
            can_view_finance = self.request.user.crm_profile.can_view_finance
        except TeamMemberProfile.DoesNotExist:
            can_view_finance = False
        if requested_sort == "cost" and not can_view_finance:
            requested_sort = "name"
        self.vendor_sort = requested_sort if requested_sort in ordering else "name"
        queryset = queryset.order_by(*ordering[self.vendor_sort])
        if search_query:
            queryset = [vendor for vendor in queryset if vendor_matches_search(vendor, search_query)]

        return queryset

    def get_context_data(self, **kwargs):
        """Передаёт в шаблон значения фильтров и доступные форматы."""

        context = super().get_context_data(**kwargs)
        context["vendor_search_query"] = self.request.GET.get("q", "")
        context["vendor_blacklist_filter"] = self.request.GET.get("blacklisted", "")
        context["vendor_format_filter"] = self.request.GET.get("event_format", "")
        context["vendor_role_filter"] = self.request.GET.get("role", "")
        context["vendor_sort"] = getattr(self, "vendor_sort", "name")
        context["vendor_formats"] = EventFormat.objects.order_by("name")
        context["vendor_roles"] = VendorRole.objects.filter(is_active=True).order_by("order", "name")
        context["vendor_selected_format"] = EventFormat.objects.filter(
            pk=context["vendor_format_filter"] if context["vendor_format_filter"].isdigit() else None
        ).first()
        context["vendor_selected_role"] = VendorRole.objects.filter(
            pk=context["vendor_role_filter"] if context["vendor_role_filter"].isdigit() else None
        ).first()
        return context


class VendorDetailView(CRMLoginRequiredMixin, DetailView):
    """Показывает профиль подрядчика, историю назначений и финансовую сводку."""

    model = Vendor
    template_name = "core/vendor_detail.html"
    context_object_name = "vendor"
    queryset = Vendor.objects.prefetch_related("event_formats", "role_categories")

    def get_context_data(self, **kwargs):
        """Собирает показатели и историю сотрудничества с учётом финансового доступа."""

        context = super().get_context_data(**kwargs)
        assignments = self.object.event_assignments.select_related(
            "event",
            "event__client",
            "event__event_format",
        ).annotate(
            expense_amount_total=Sum("expenses__amount"),
            paid_amount_total=Sum("expenses__paid_amount"),
        ).order_by("-event__date", "-id")
        context["vendor_assignments"] = assignments
        context["vendor_summary"] = {
            "events": assignments.values("event_id").distinct().count(),
            "approved": assignments.filter(status=EventVendor.Status.APPROVED).count(),
            "completed": assignments.filter(event__status=Event.Status.COMPLETED).count(),
        }

        try:
            can_view_finance = self.request.user.crm_profile.can_view_finance
        except TeamMemberProfile.DoesNotExist:
            can_view_finance = False

        if can_view_finance:
            assignment_totals = self.object.event_assignments.aggregate(total_cost=Sum("cost"))
            expense_totals = EventExpense.objects.filter(
                vendor_assignment__vendor=self.object
            ).aggregate(total=Sum("amount"), paid=Sum("paid_amount"))
            total = expense_totals["total"] or 0
            paid = expense_totals["paid"] or 0
            context["vendor_finance_summary"] = {
                "total_cost": assignment_totals["total_cost"] or 0,
                "expenses": total,
                "paid": paid,
                "remaining": total - paid,
            }

        return context


class VendorAutocompleteView(CRMLoginRequiredMixin, View):
    """Возвращает совпадения для подсказок в поиске подрядчиков."""

    def get(self, request):
        """Ищет подрядчиков по имени, ролям или контактам после двух символов."""

        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        vendors = [
            vendor
            for vendor in Vendor.objects.order_by("name", "id")
            if vendor_matches_search(vendor, query)
        ][:8]
        return JsonResponse(
            {
                "results": [
                    {
                        "id": vendor.pk,
                        "name": vendor.name,
                        "roles": vendor.role_label,
                        "contacts": vendor.contact_summary,
                    }
                    for vendor in vendors
                ]
            }
        )


class PackageListView(CRMLoginRequiredMixin, ListView):
    """Отображает пакеты услуг с привязкой к формату мероприятия."""

    model = ServicePackage
    template_name = "core/packages.html"
    context_object_name = "packages"
    queryset = ServicePackage.objects.select_related("event_format")


class CalendarView(CRMLoginRequiredMixin, ListView):
    """Показывает календарный список мероприятий."""

    model = Event
    template_name = "core/calendar.html"
    context_object_name = "events"
    queryset = Event.objects.select_related("client", "manager").order_by("date")


class AnalyticsView(AnalyticsAccessMixin, TemplateView):
    """Показывает базовую аналитику по продажам, прибыли, источникам и команде."""

    template_name = "core/analytics.html"

    def get_context_data(self, **kwargs):
        """Собирает агрегированные показатели для аналитического дашборда."""

        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", "all")
        if period not in {"all", "6m", "12m"}:
            period = "all"
        period_start, period_end = analytics_period_bounds(period)

        leads = Lead.objects.all()
        clients = Client.objects.all()
        events = Event.objects.all()
        if period_start and period_end:
            leads = leads.filter(created_at__date__range=(period_start, period_end))
            clients = clients.filter(created_at__date__range=(period_start, period_end))
            events = events.filter(date__range=(period_start, period_end))

        total_leads = leads.count() or 1
        qualified_clients = clients.count()
        total_revenue = events.aggregate(total=Sum("planned_budget"))["total"] or 0
        can_view_finance = self.request.user.crm_profile.can_view_finance
        stage_totals = dict(leads.values("stage_id").annotate(total=Count("id")).values_list("stage_id", "total"))
        pipeline_chart = [
            {
                "label": stage.name,
                "total": stage_totals.get(stage.pk, 0),
                "color": pipeline_stage_color(stage),
                "url": f"{reverse('core:pipeline')}?stage={stage.pk}",
            }
            for stage in PipelineStage.objects.order_by("order", "name")
        ]
        source_chart = [
            {
                "label": source["source"] or "Не указан",
                "total": source["total"],
                "url": f"{reverse('core:leads')}?{urlencode({'source': source['source']})}" if source["source"] else reverse("core:leads"),
            }
            for source in leads.values("source").annotate(total=Count("id")).order_by("-total", "source")
        ]
        month_names = (
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        )
        monthly_totals = {}
        for event_date in events.values_list("date", flat=True):
            month_key = event_date.strftime("%Y-%m")
            monthly_totals[month_key] = monthly_totals.get(month_key, 0) + 1
        monthly_chart = [
            {
                "label": f"{month_names[int(month_key[5:7]) - 1]} {month_key[:4]}",
                "total": total,
                "url": f"{reverse('core:events')}?scope=all&month={month_key}",
            }
            for month_key, total in sorted(monthly_totals.items())
        ]
        manager_totals = list(
            events.values("manager_id")
            .exclude(manager_id=None)
            .annotate(total=Count("id"))
            .order_by("-total", "manager_id")[:8]
        )
        managers = User.objects.in_bulk(item["manager_id"] for item in manager_totals)
        team_chart = [
            {
                "label": managers[item["manager_id"]].get_username(),
                "total": item["total"],
                "url": f"{reverse('core:events')}?scope=all&manager={item['manager_id']}",
            }
            for item in manager_totals
        ]
        finance_monthly_chart = []
        if can_view_finance:
            finance_totals = {}
            for event in events.prefetch_related("expenses"):
                month_key = event.date.strftime("%Y-%m")
                month_data = finance_totals.setdefault(month_key, {"budget": 0, "expenses": 0})
                month_data["budget"] += float(event.planned_budget)
                month_data["expenses"] += float(event.total_expenses)
            finance_monthly_chart = [
                {
                    "label": f"{month_names[int(month_key[5:7]) - 1]} {month_key[:4]}",
                    "budget": values["budget"],
                    "expenses": values["expenses"],
                    "url": f"{reverse('core:events')}?scope=all&month={month_key}",
                }
                for month_key, values in sorted(finance_totals.items())
            ]
        context["metrics"] = {
            "conversion": round((qualified_clients / total_leads) * 100, 1),
            "average_check": round(total_revenue / max(events.count(), 1), 2),
            "profit": sum(event.profit for event in events.prefetch_related("expenses")),
            "sources": leads.values("source").annotate(total=Count("id")).order_by("-total"),
            "team_load": team_chart,
        }
        context["analytics_period"] = period
        context["analytics_period_choices"] = (("all", "Весь период"), ("6m", "Последние 6 месяцев"), ("12m", "Последние 12 месяцев"))
        context["pipeline_chart"] = pipeline_chart
        context["source_chart"] = source_chart
        context["monthly_chart"] = monthly_chart
        context["team_chart"] = team_chart
        context["finance_monthly_chart"] = finance_monthly_chart
        return context


class TeamView(SystemAccessMixin, ListView):
    """Отображает пользователей CRM, роли и флаги доступа."""

    model = TeamMemberProfile
    template_name = "core/team.html"
    context_object_name = "profiles"
    queryset = TeamMemberProfile.objects.select_related("user")


class CRUDContextMixin(CRMLoginRequiredMixin):
    """Добавляет общий контекст для универсального шаблона CRUD-форм."""

    page_title = ""
    submit_label = "Сохранить"
    cancel_url = reverse_lazy("core:dashboard")

    def get_cancel_url(self):
        """Возвращает URL для кнопок Назад/Отмена в форме."""

        return self.cancel_url

    def get_context_data(self, **kwargs):
        """Передает в шаблон заголовок, текст submit-кнопки и cancel URL."""

        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.get_cancel_url()
        return context


class SuccessMessageMixin:
    """Показывает flash-сообщение после успешного сохранения формы."""

    success_message = ""

    def form_valid(self, form):
        """Добавляет success message после штатного сохранения формы."""

        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class ExpenseDuplicateWarningMixin:
    """Просит подтвердить сохранение расхода с уже использованным подрядчиком."""

    def form_valid(self, form):
        """Показывает предупреждение до сохранения возможного дубля."""

        if (
            form.show_duplicate_warning
            and self.request.POST.get("confirm_duplicate") != "1"
        ):
            form.show_duplicate_warning = True
            return self.render_to_response(self.get_context_data(form=form))
        return super().form_valid(form)


class EventScopedFormMixin(CRMLoginRequiredMixin):
    """Привязывает nested-формы к мероприятию и возвращает пользователя в нужную вкладку."""

    event_kwarg = "event_pk"
    return_tab = "tasks"

    def dispatch(self, request, *args, **kwargs):
        """Находит родительское мероприятие, если оно передано в URL."""

        self.parent_event = None
        event_pk = kwargs.get(self.event_kwarg)
        if event_pk:
            self.parent_event = get_object_or_404(Event, pk=event_pk)
        return super().dispatch(request, *args, **kwargs)

    def get_event_detail_url(self, event):
        """Строит URL карточки мероприятия с вкладкой по умолчанию для view."""

        return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.return_tab}#event-tabs"

    def get_return_tab(self):
        """Определяет вкладку возврата из запроса или настройки view."""

        return self.request.GET.get("return_tab") or self.request.POST.get("return_tab") or self.return_tab

    def get_initial(self):
        """Предзаполняет поле event для nested-форм."""

        initial = super().get_initial()
        if self.parent_event:
            initial["event"] = self.parent_event
        return initial

    def get_form(self, form_class=None):
        """Фиксирует поле event на родительском мероприятии при создании из карточки."""

        form = super().get_form(form_class)
        event = self.parent_event or getattr(form.instance, "event", None)
        if event and "vendor_assignment" in form.fields:
            form.fields["vendor_assignment"].queryset = EventVendor.objects.filter(event=event).select_related("vendor")
        if self.parent_event and "event" in form.fields:
            form.fields["event"].initial = self.parent_event
            form.fields["event"].queryset = Event.objects.filter(pk=self.parent_event.pk)
            form.fields["event"].disabled = True
        return form

    def get_context_data(self, **kwargs):
        """Передает return_tab в форму, чтобы сохранить направление возврата после POST."""

        context = super().get_context_data(**kwargs)
        context["return_tab"] = self.get_return_tab()
        return context

    def form_valid(self, form):
        """Гарантирует привязку сохраняемого объекта к родительскому мероприятию."""

        if self.parent_event and "event" in form.fields:
            form.instance.event = self.parent_event
        return super().form_valid(form)

    def get_cancel_url(self):
        """Возвращает пользователя в карточку мероприятия и нужную вкладку."""

        if self.parent_event:
            return f"{reverse('core:event_detail', kwargs={'pk': self.parent_event.pk})}?tab={self.get_return_tab()}#event-tabs"
        event = getattr(getattr(self, "object", None), "event", None)
        if event:
            return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.get_return_tab()}#event-tabs"
        return super().get_cancel_url()

    def get_success_url(self):
        """После сохранения возвращает пользователя в рабочую вкладку карточки мероприятия."""

        event = self.parent_event or getattr(getattr(self, "object", None), "event", None)
        if event:
            return f"{reverse('core:event_detail', kwargs={'pk': event.pk})}?tab={self.get_return_tab()}#event-tabs"
        return super().get_success_url()


class LeadStageUpdateView(LeadManagementMixin, SuccessMessageMixin, UpdateView):
    """Быстрая смена этапа с серверной проверкой причины отказа."""

    model = Lead
    form_class = LeadStageForm
    template_name = "core/lead_stage_form.html"
    success_message = "Этап лида обновлён."

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self.current_stage = str(obj.stage) if obj.stage else "Без этапа"
        return obj

    def get_success_url(self):
        params = {key: self.request.GET[key] for key in ("q", "stage", "manager", "attention") if self.request.GET.get(key)}
        url = reverse("core:pipeline")
        return f"{url}?{urlencode(params)}" if params else url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.get_success_url()
        context["current_stage"] = self.current_stage
        return context



class LeadCreateView(LeadManagementMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает новый лид через основной CRM-интерфейс."""

    model = Lead
    form_class = LeadForm
    template_name = "core/lead_form.html"
    page_title = "Новый лид"
    success_message = "Лид создан."
    success_url = reverse_lazy("core:leads")
    cancel_url = reverse_lazy("core:leads")


class LeadUpdateView(LeadManagementMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует существующий лид."""

    model = Lead
    form_class = LeadForm
    template_name = "core/lead_form.html"
    page_title = "Редактирование лида"
    success_message = "Лид обновлён."
    def get_success_url(self):
        """После сохранения возвращает пользователя в карточку лида."""

        return reverse("core:lead_detail", kwargs={"pk": self.object.pk})

    def get_cancel_url(self):
        """Отмена редактирования возвращает пользователя в карточку лида."""

        return reverse("core:lead_detail", kwargs={"pk": self.object.pk})


class LeadDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет лид после подтверждения."""

    model = Lead
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:leads")


class PipelineStageCreateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает новый этап воронки продаж."""

    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "core/pipeline_stage_form.html"
    page_title = "Новый этап воронки"
    submit_label = "Создать этап"
    success_message = "Этап воронки создан."
    success_url = reverse_lazy("core:pipeline")
    cancel_url = reverse_lazy("core:pipeline")


class PipelineStageUpdateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует этап воронки продаж."""

    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "core/pipeline_stage_form.html"
    page_title = "Редактирование этапа"
    submit_label = "Сохранить изменения"
    success_message = "Этап воронки обновлён."
    success_url = reverse_lazy("core:pipeline")
    cancel_url = reverse_lazy("core:pipeline")


class PipelineStageDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет этап воронки после подтверждения."""

    model = PipelineStage
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:pipeline")


class ClientFormContextMixin:
    """Подготавливает создание из лида и фактическую историю мероприятий клиента."""

    def get_initial(self):
        initial = super().get_initial()
        if not getattr(self, "object", None) and self.request.GET.get("lead", "").isdigit():
            initial["lead"] = self.request.GET["lead"]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        context["client_events"] = obj.events.order_by("-date", "-pk") if obj else []
        return context


class ClientLeadDataView(ClientManagementMixin, View):
    """Ищет доступные лиды и отдаёт контакты выбранного лида для формы клиента."""

    def get(self, request):
        eligible = Q(client__isnull=True)
        client_id = request.GET.get("client_id", "")
        if client_id.isdigit():
            eligible |= Q(client__pk=client_id)
        leads = Lead.objects.filter(eligible).order_by("name", "pk")
        lead_id = request.GET.get("lead_id")
        if lead_id is not None:
            if not lead_id.isdigit():
                return JsonResponse({"error": "Некорректный лид"}, status=400)
            lead = get_object_or_404(leads, pk=lead_id)
            manager_id = lead.manager_id if User.objects.filter(
                pk=lead.manager_id, is_active=True, crm_profile__isnull=False,
            ).exists() else None
            response = JsonResponse({
                "fields": {field: getattr(lead, field) for field in ClientForm.lead_contact_fields},
                "manager_id": manager_id,
            })
        else:
            query = request.GET.get("q", "").strip()
            matches = (lead for lead in leads if lead_matches_search(lead, query))
            response = JsonResponse({"results": [
                {"id": lead.pk, "name": lead.name, "contact": lead.phone or lead.email}
                for lead in islice(matches, 8)
            ]})
        response["Cache-Control"] = "no-store"
        return response


class ClientCreateView(ClientManagementMixin, ClientFormContextMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает нового клиента."""

    model = Client
    form_class = ClientForm
    template_name = "core/client_form.html"
    page_title = "Новый клиент"
    submit_label = "Создать клиента"
    success_message = "Клиент создан."
    success_url = reverse_lazy("core:clients")
    cancel_url = reverse_lazy("core:clients")

    def get_success_url(self):
        return reverse("core:client_detail", kwargs={"pk": self.object.pk})


class ClientUpdateView(ClientManagementMixin, ClientFormContextMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует карточку клиента."""

    model = Client
    form_class = ClientForm
    template_name = "core/client_form.html"
    page_title = "Редактирование клиента"
    success_message = "Клиент обновлён."
    success_url = reverse_lazy("core:clients")
    cancel_url = reverse_lazy("core:clients")

    def get_success_url(self):
        return reverse("core:client_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.get_success_url()
        return context


class ClientDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет клиента после подтверждения."""

    model = Client
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:clients")


class EventCreateView(EventManagementMixin, FinanceFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает новое мероприятие."""

    model = Event
    form_class = EventForm
    template_name = "core/event_form.html"
    page_title = "Новое мероприятие"
    submit_label = "Создать мероприятие"
    success_message = "Мероприятие создано."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")

    def get_success_url(self):
        return reverse("core:event_detail", kwargs={"pk": self.object.pk})


class EventUpdateView(EventManagementMixin, FinanceFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует основные данные мероприятия."""

    model = Event
    form_class = EventForm
    template_name = "core/event_form.html"
    page_title = "Редактирование мероприятия"
    submit_label = "Сохранить изменения"
    success_message = "Мероприятие обновлено."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")

    def get_success_url(self):
        return reverse("core:event_detail", kwargs={"pk": self.object.pk})

    def get_cancel_url(self):
        return self.get_success_url()


class EventDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет мероприятие после подтверждения."""

    model = Event
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:events")


class TaskReturnMixin:
    """Сохраняет происхождение действия: общий список или вкладка мероприятия."""

    def get_task_list_url(self):
        if getattr(self, "parent_event", None):
            return None
        if (self.request.POST.get("return_tab") or self.request.GET.get("return_tab")) == "tasks":
            return None
        value = self.request.POST.get("return_to") or self.request.GET.get("return_to", "")
        return safe_task_return_url(value) or reverse("core:tasks")

    def get_success_url(self):
        return self.get_task_list_url() or super().get_success_url()

    def get_cancel_url(self):
        return self.get_task_list_url() or super().get_cancel_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return_url = self.get_task_list_url()
        if return_url:
            context.update(return_to=return_url, cancel_url=return_url, return_tab="")
        elif not context.get("cancel_url") and getattr(self, "object", None):
            context["cancel_url"] = f"{reverse('core:event_detail', args=[self.object.event_id])}?tab=tasks#event-tabs"
        return context


class TaskCreateView(TaskReturnMixin, EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает задачу, отдельно или из карточки мероприятия."""

    model = EventTask
    form_class = EventTaskForm
    template_name = "core/object_form.html"
    return_tab = "tasks"
    page_title = "Новая задача"
    success_message = "Задача создана."
    success_url = reverse_lazy("core:tasks")
    cancel_url = reverse_lazy("core:tasks")


class TaskUpdateView(TaskReturnMixin, EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует задачу и возвращает пользователя в контекст мероприятия при необходимости."""

    model = EventTask
    form_class = EventTaskForm
    template_name = "core/object_form.html"
    return_tab = "tasks"
    page_title = "Редактирование задачи"
    success_message = "Задача обновлена."
    success_url = reverse_lazy("core:tasks")
    cancel_url = reverse_lazy("core:tasks")


class EventTimelineItemCreateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет блок тайминга к мероприятию."""

    model = EventTimelineItem
    form_class = EventTimelineItemForm
    template_name = "core/object_form.html"
    return_tab = "timeline"
    page_title = "Новый блок тайминга"
    success_message = "Блок тайминга добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventTimelineItemUpdateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует блок тайминга мероприятия."""

    model = EventTimelineItem
    form_class = EventTimelineItemForm
    template_name = "core/object_form.html"
    return_tab = "timeline"
    page_title = "Редактирование блока тайминга"
    success_message = "Блок тайминга обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventTimelineItemDeleteView(EventManagementMixin, DeleteView):
    """Удаляет блок тайминга после подтверждения."""

    model = EventTimelineItem
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Возвращает пользователя на вкладку тайминга после удаления блока."""

        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=timeline#event-tabs"


class EventRiskCreateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет риск к мероприятию."""

    model = EventRisk
    form_class = EventRiskForm
    template_name = "core/object_form.html"
    return_tab = "risks"
    page_title = "Новый риск"
    success_message = "Риск добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventRiskUpdateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует риск мероприятия."""

    model = EventRisk
    form_class = EventRiskForm
    template_name = "core/object_form.html"
    return_tab = "risks"
    page_title = "Редактирование риска"
    success_message = "Риск обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventRiskDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет риск после подтверждения и возвращает пользователя к рискам мероприятия."""

    model = EventRisk
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Возвращает пользователя на вкладку рисков после удаления."""

        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=risks#event-tabs"


class EventOutcomeCreateView(EventManagementMixin, FinanceFormMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет итоги к мероприятию."""

    model = EventOutcome
    form_class = EventOutcomeForm
    template_name = "core/object_form.html"
    return_tab = "outcome"
    page_title = "Итоги мероприятия"
    success_message = "Итоги мероприятия сохранены."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventOutcomeUpdateView(EventManagementMixin, FinanceFormMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует итоги мероприятия."""

    model = EventOutcome
    form_class = EventOutcomeForm
    template_name = "core/object_form.html"
    return_tab = "outcome"
    page_title = "Редактирование итогов"
    success_message = "Итоги мероприятия обновлены."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventOutcomeDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет итоги мероприятия после подтверждения."""

    model = EventOutcome
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Возвращает пользователя на вкладку итогов после удаления."""

        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=outcome#event-tabs"


class TaskDeleteView(TaskReturnMixin, SystemAccessMixin, DeleteView):
    """Удаляет задачу и возвращает пользователя в список задач или вкладку мероприятия."""

    model = EventTask
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Выбирает URL возврата по месту, откуда пользователь пришел удалять задачу."""

        return self.get_task_list_url() or (
            f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=tasks#event-tabs"
        )


class TaskStatusUpdateView(EventManagementMixin, View):
    """Быстро меняет статус задачи из карточки мероприятия."""

    allowed_statuses = {choice[0] for choice in EventTask.Status.choices}

    def post(self, request, pk):
        """Обновляет статус задачи, если POST содержит допустимое значение."""

        task = get_object_or_404(EventTask, pk=pk)
        status = request.POST.get("status")
        if status in self.allowed_statuses:
            task.status = status
            task.save(update_fields=["status"])
            messages.success(request, "Статус задачи обновлён.")
        return_url = safe_task_return_url(request.POST.get("return_to", ""))
        if request.POST.get("return_task") == "1":
            detail_url = reverse("core:task_detail", args=[task.pk])
            if return_url:
                detail_url += "?" + urlencode({"return_to": return_url})
            return redirect(detail_url)
        return redirect(return_url or f"{reverse('core:event_detail', kwargs={'pk': task.event.pk})}?tab=tasks#event-tabs")


class EventExpenseCreateView(
    ExpenseDuplicateWarningMixin,
    FinanceAccessMixin,
    EventScopedFormMixin,
    CRUDContextMixin,
    SuccessMessageMixin,
    CreateView,
):
    """Добавляет расход к мероприятию."""

    model = EventExpense
    form_class = EventExpenseForm
    template_name = "core/object_form.html"
    return_tab = "expenses"
    page_title = "Новый расход"
    success_message = "Расход добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventExpenseUpdateView(
    ExpenseDuplicateWarningMixin,
    FinanceAccessMixin,
    EventScopedFormMixin,
    CRUDContextMixin,
    SuccessMessageMixin,
    UpdateView,
):
    """Редактирует расход мероприятия."""

    model = EventExpense
    form_class = EventExpenseForm
    template_name = "core/object_form.html"
    return_tab = "expenses"
    page_title = "Редактирование расхода"
    success_message = "Расход обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventExpenseDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет расход после подтверждения и возвращает пользователя к расходам мероприятия."""

    model = EventExpense
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Возвращает пользователя на вкладку расходов после удаления."""

        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=expenses#event-tabs"


class EventVendorCreateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет подрядчика в конкретное мероприятие."""

    model = EventVendor
    form_class = EventVendorForm
    template_name = "core/object_form.html"
    return_tab = "vendors"
    page_title = "Новый подрядчик мероприятия"
    success_message = "Подрядчик добавлен в мероприятие."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventVendorUpdateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует назначение подрядчика на мероприятие."""

    model = EventVendor
    form_class = EventVendorForm
    template_name = "core/object_form.html"
    return_tab = "vendors"
    page_title = "Редактирование подрядчика мероприятия"
    success_message = "Подрядчик мероприятия обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventVendorDeleteView(EventManagementMixin, DeleteView):
    """Удаляет назначение подрядчика только из конкретного мероприятия."""

    model = EventVendor
    template_name = "core/object_confirm_delete.html"

    def get_success_url(self):
        """Возвращает пользователя на вкладку подрядчиков после удаления назначения."""

        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event.pk})}?tab=vendors#event-tabs"


class EventVendorStatusUpdateView(EventManagementMixin, View):
    """Быстро меняет статус подрядчика внутри карточки мероприятия."""

    allowed_statuses = {choice[0] for choice in EventVendor.Status.choices}

    def post(self, request, pk):
        """Обновляет статус назначения подрядчика, если значение допустимо."""

        assignment = get_object_or_404(EventVendor, pk=pk)
        status = request.POST.get("status")
        if status in self.allowed_statuses:
            assignment.status = status
            assignment.save(update_fields=["status"])
            messages.success(request, "Статус подрядчика обновлён.")
        return redirect(f"{reverse('core:event_detail', kwargs={'pk': assignment.event.pk})}?tab=vendors#event-tabs")


class EventRecordDeleteView(EventManagementMixin, DeleteView):
    """Удаляет запись мероприятия и возвращает в её фиксированную вкладку."""

    template_name = "core/object_confirm_delete.html"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().select_related("event")

    def get_success_url(self):
        return f"{reverse('core:event_detail', kwargs={'pk': self.object.event_id})}?tab={self.return_tab}#event-tabs"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title=self.page_title,
            parent_event=self.object.event,
            cancel_url=self.get_success_url(),
            return_tab=self.return_tab,
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class EventCommunicationDeleteView(EventRecordDeleteView):
    """Удаляет коммуникацию после подтверждения."""

    model = EventCommunication
    page_title = "Удаление коммуникации"
    return_tab = "communications"
    success_message = "Коммуникация удалена."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["communication_date"] = self.object.date
        context["communication_comment"] = self.object.comment
        return context


class EventDocumentDeleteView(EventRecordDeleteView):
    """Удаляет документ и освобождает его файл после фиксации изменения в БД."""

    model = EventDocument
    page_title = "Удаление документа"
    return_tab = "documents"
    success_message = "Документ удалён."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["document_status"] = self.object.get_status_display()
        if self.object.file:
            context["attachment_name"] = self.object.file.name.rsplit("/", 1)[-1]
        return context

    def form_valid(self, form):
        storage = self.object.file.storage
        filename = self.object.file.name

        def delete_attachment():
            # Один физический файл может остаться связан с другой записью документа.
            if not EventDocument.objects.filter(file=filename).exists():
                storage.delete(filename)

        with transaction.atomic():
            response = super().form_valid(form)
            if filename:
                transaction.on_commit(delete_attachment, robust=True)
        return response


class EventCommunicationCreateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет коммуникацию к мероприятию."""

    model = EventCommunication
    form_class = EventCommunicationForm
    template_name = "core/object_form.html"
    return_tab = "communications"
    page_title = "Новая коммуникация"
    success_message = "Коммуникация добавлена."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventCommunicationUpdateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует коммуникацию мероприятия."""

    model = EventCommunication
    form_class = EventCommunicationForm
    template_name = "core/object_form.html"
    return_tab = "communications"
    page_title = "Редактирование коммуникации"
    success_message = "Коммуникация обновлена."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventDocumentCreateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Добавляет документ к мероприятию."""

    model = EventDocument
    form_class = EventDocumentForm
    template_name = "core/object_form.html"
    return_tab = "documents"
    page_title = "Новый документ"
    success_message = "Документ добавлен."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventDocumentUpdateView(EventManagementMixin, EventScopedFormMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует документ мероприятия."""

    model = EventDocument
    form_class = EventDocumentForm
    template_name = "core/object_form.html"
    return_tab = "documents"
    page_title = "Редактирование документа"
    success_message = "Документ обновлён."
    success_url = reverse_lazy("core:events")
    cancel_url = reverse_lazy("core:events")


class EventFormatCreateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает формат мероприятия."""

    model = EventFormat
    form_class = EventFormatForm
    template_name = "core/object_form.html"
    page_title = "Новый формат"
    success_message = "Формат мероприятия создан."
    success_url = reverse_lazy("core:formats")
    cancel_url = reverse_lazy("core:formats")


class EventFormatUpdateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует формат мероприятия."""

    model = EventFormat
    form_class = EventFormatForm
    template_name = "core/object_form.html"
    page_title = "Редактирование формата"
    success_message = "Формат мероприятия обновлён."
    success_url = reverse_lazy("core:formats")
    cancel_url = reverse_lazy("core:formats")


class EventFormatDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет формат мероприятия после подтверждения."""

    model = EventFormat
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:formats")


class VendorCreateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает подрядчика в справочнике."""

    model = Vendor
    form_class = VendorForm
    template_name = "core/vendor_form.html"
    page_title = "Новый подрядчик"
    submit_label = "Создать подрядчика"
    success_message = "Подрядчик создан."
    success_url = reverse_lazy("core:vendors")
    cancel_url = reverse_lazy("core:vendors")


class VendorUpdateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует подрядчика в справочнике."""

    model = Vendor
    form_class = VendorForm
    template_name = "core/vendor_form.html"
    page_title = "Редактирование подрядчика"
    submit_label = "Сохранить изменения"
    success_message = "Подрядчик обновлён."
    success_url = reverse_lazy("core:vendors")
    cancel_url = reverse_lazy("core:vendors")


class VendorDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет подрядчика после подтверждения."""

    model = Vendor
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:vendors")


class ServicePackageCreateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, CreateView):
    """Создает пакет услуг."""

    model = ServicePackage
    form_class = ServicePackageForm
    template_name = "core/object_form.html"
    page_title = "Новый пакет"
    success_message = "Пакет услуг создан."
    success_url = reverse_lazy("core:packages")
    cancel_url = reverse_lazy("core:packages")


class ServicePackageUpdateView(SystemAccessMixin, CRUDContextMixin, SuccessMessageMixin, UpdateView):
    """Редактирует пакет услуг."""

    model = ServicePackage
    form_class = ServicePackageForm
    template_name = "core/object_form.html"
    page_title = "Редактирование пакета"
    success_message = "Пакет услуг обновлён."
    success_url = reverse_lazy("core:packages")
    cancel_url = reverse_lazy("core:packages")


class ServicePackageDeleteView(SystemAccessMixin, DeleteView):
    """Удаляет пакет услуг после подтверждения."""

    model = ServicePackage
    template_name = "core/object_confirm_delete.html"
    success_url = reverse_lazy("core:packages")
