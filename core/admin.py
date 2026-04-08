from django.contrib import admin

from .models import (
    Client,
    Event,
    EventCommunication,
    EventDocument,
    EventExpense,
    EventFormat,
    EventFormatBudgetTemplate,
    EventFormatTaskTemplate,
    EventFormatTimelineTemplate,
    EventFormatVendorTemplate,
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
)


class EventExpenseInline(admin.TabularInline):
    model = EventExpense
    extra = 0


class EventTaskInline(admin.TabularInline):
    model = EventTask
    extra = 0


class EventVendorInline(admin.TabularInline):
    model = EventVendor
    extra = 0


@admin.register(TeamMemberProfile)
class TeamMemberProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "can_view_finance", "can_view_analytics", "can_manage_system")
    list_filter = ("role",)


@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "probability", "is_lost")
    list_editable = ("order", "probability", "is_lost")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "stage", "probability", "manager", "created_at")
    list_filter = ("stage", "source")
    search_fields = ("name", "phone", "email", "messenger")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "client_type", "segment", "ltv", "created_at")
    list_filter = ("client_type", "segment")
    search_fields = ("name", "contacts", "phone", "email")


@admin.register(EventFormat)
class EventFormatAdmin(admin.ModelAdmin):
    list_display = ("name", "default_budget")
    search_fields = ("name",)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "roles", "avg_cost", "rating", "reliability", "blacklisted")
    list_filter = ("blacklisted",)
    search_fields = ("name", "roles", "contacts")


@admin.register(ServicePackage)
class ServicePackageAdmin(admin.ModelAdmin):
    list_display = ("name", "event_format", "price")
    list_filter = ("event_format",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "event_format", "date", "city", "status", "manager")
    list_filter = ("status", "event_format", "city")
    search_fields = ("title", "client__name", "city")
    inlines = (EventExpenseInline, EventTaskInline, EventVendorInline)


@admin.register(EventTimelineItem)
class EventTimelineItemAdmin(admin.ModelAdmin):
    list_display = ("event", "time", "block", "responsible")


@admin.register(EventRisk)
class EventRiskAdmin(admin.ModelAdmin):
    list_display = ("event", "probability")


@admin.register(EventCommunication)
class EventCommunicationAdmin(admin.ModelAdmin):
    list_display = ("event", "communication_type", "date", "manager")
    list_filter = ("communication_type",)


@admin.register(EventDocument)
class EventDocumentAdmin(admin.ModelAdmin):
    list_display = ("event", "document_type", "status")
    list_filter = ("document_type", "status")


@admin.register(EventOutcome)
class EventOutcomeAdmin(admin.ModelAdmin):
    list_display = ("event", "final_profit", "project_rating")


@admin.register(EventFormatTaskTemplate)
class EventFormatTaskTemplateAdmin(admin.ModelAdmin):
    list_display = ("event_format", "title", "deadline_offset_days")


@admin.register(EventFormatTimelineTemplate)
class EventFormatTimelineTemplateAdmin(admin.ModelAdmin):
    list_display = ("event_format", "time", "block", "responsible_label")


@admin.register(EventFormatBudgetTemplate)
class EventFormatBudgetTemplateAdmin(admin.ModelAdmin):
    list_display = ("event_format", "category", "amount")


@admin.register(EventFormatVendorTemplate)
class EventFormatVendorTemplateAdmin(admin.ModelAdmin):
    list_display = ("event_format", "vendor", "role", "cost")
