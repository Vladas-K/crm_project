from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0027_event_planned_budget_nonnegative")]

    operations = [
        migrations.DeleteModel(name="EventFormatTaskTemplate"),
        migrations.DeleteModel(name="EventFormatTimelineTemplate"),
        migrations.DeleteModel(name="EventFormatBudgetTemplate"),
        migrations.DeleteModel(name="EventFormatVendorTemplate"),
        migrations.RemoveField(model_name="eventformat", name="default_budget"),
    ]
