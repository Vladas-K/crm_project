from django.db import migrations, models
import django.db.models.deletion


def copy_expense_categories(apps, schema_editor):
    EventExpense = apps.get_model("core", "EventExpense")
    ExpenseCategory = apps.get_model("core", "ExpenseCategory")

    category_names = EventExpense.objects.values_list("category", flat=True).distinct()
    categories = {}
    for name in category_names:
        if name:
            category, _ = ExpenseCategory.objects.get_or_create(name=name)
            categories[name] = category
    for expense in EventExpense.objects.all():
        expense.category_ref_id = categories[expense.category].pk
        expense.save(update_fields=["category_ref"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_remove_eventexpense_prepayment_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Название")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
            ],
            options={
                "ordering": ("order", "name"),
                "verbose_name": "Категория расходов",
                "verbose_name_plural": "Категории расходов",
            },
        ),
        migrations.AddField(
            model_name="eventexpense",
            name="category_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="expense_category_links",
                to="core.expensecategory",
                verbose_name="Категория",
            ),
        ),
        migrations.RunPython(copy_expense_categories, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="eventexpense",
            name="category",
        ),
        migrations.RenameField(
            model_name="eventexpense",
            old_name="category_ref",
            new_name="category",
        ),
        migrations.AlterField(
            model_name="eventexpense",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="expenses",
                to="core.expensecategory",
                verbose_name="Категория",
            ),
        ),
    ]
