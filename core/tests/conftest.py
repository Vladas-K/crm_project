import pytest
from django.utils import timezone

from core.models import (
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
    Vendor,
)


@pytest.fixture
def crm_objects(db):
    stage = PipelineStage.objects.create(name="Новый", code="new", order=1, probability=10)
    event_format = EventFormat.objects.create(name="Корпоратив", default_budget=100000)
    lead = Lead.objects.create(name="Иван Петров", stage=stage)
    client = Client.objects.create(name="ООО Ромашка", lead=lead)
    event = Event.objects.create(
        client=client,
        lead=lead,
        event_format=event_format,
        title="Корпоратив Ромашка",
        date=timezone.localdate(),
        city="Москва",
        planned_budget=100000,
    )
    task = EventTask.objects.create(event=event, title="Подготовить бриф")
    expense = EventExpense.objects.create(event=event, category="Площадка", amount=50000)
    vendor = Vendor.objects.create(name="Stage Pro", roles="Техника")
    event_vendor = EventVendor.objects.create(
        event=event,
        vendor=vendor,
        role="Техника",
        cost=50000,
    )
    communication = EventCommunication.objects.create(
        event=event,
        communication_type=EventCommunication.Type.CALL,
        date=timezone.now(),
    )
    document = EventDocument.objects.create(
        event=event,
        document_type=EventDocument.Type.CONTRACT,
    )
    service_package = ServicePackage.objects.create(
        name="Базовый",
        event_format=event_format,
        services="Организация",
        price=100000,
    )

    return {
        "stage": stage,
        "event_format": event_format,
        "lead": lead,
        "client": client,
        "event": event,
        "task": task,
        "expense": expense,
        "vendor": vendor,
        "event_vendor": event_vendor,
        "communication": communication,
        "document": document,
        "service_package": service_package,
    }
