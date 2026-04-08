from django.db import migrations


def seed_pipeline_stages(apps, schema_editor):
    PipelineStage = apps.get_model("core", "PipelineStage")
    stages = [
        ("Новый лид", "new_lead", 1, 10, False),
        ("Связались", "contacted", 2, 20, False),
        ("Бриф", "brief", 3, 35, False),
        ("КП отправлено", "proposal_sent", 4, 50, False),
        ("Переговоры", "negotiation", 5, 65, False),
        ("Договор", "contract", 6, 80, False),
        ("Оплата", "payment", 7, 95, False),
        ("Потерян", "lost", 8, 0, True),
    ]
    for name, code, order, probability, is_lost in stages:
        PipelineStage.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "order": order,
                "probability": probability,
                "is_lost": is_lost,
            },
        )


def unseed_pipeline_stages(apps, schema_editor):
    PipelineStage = apps.get_model("core", "PipelineStage")
    PipelineStage.objects.filter(
        code__in=[
            "new_lead",
            "contacted",
            "brief",
            "proposal_sent",
            "negotiation",
            "contract",
            "payment",
            "lost",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_eventformat_pipelinestage_remove_task_deal_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_pipeline_stages, unseed_pipeline_stages),
    ]
