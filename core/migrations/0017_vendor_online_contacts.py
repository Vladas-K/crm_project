from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_vendor_contact_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="max_messenger",
            field=models.CharField(blank=True, help_text="Контакт или полная ссылка", max_length=150, verbose_name="MAX"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="whatsapp",
            field=models.CharField(
                blank=True,
                help_text="Номер телефона или полная ссылка",
                max_length=150,
                verbose_name="WhatsApp",
            ),
        ),
        migrations.AlterField(
            model_name="vendor",
            name="preferred_contact_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("phone", "Телефон"),
                    ("email", "Email"),
                    ("telegram", "Telegram"),
                    ("whatsapp", "WhatsApp"),
                    ("max", "MAX"),
                    ("other", "Другой"),
                ],
                max_length=20,
                verbose_name="Предпочтительный способ связи",
            ),
        ),
    ]
