from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_vendor_online_contacts"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="instagram",
            field=models.CharField(blank=True, help_text="Username или полная ссылка", max_length=150, verbose_name="Instagram"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="vk",
            field=models.CharField(blank=True, help_text="Username или полная ссылка", max_length=150, verbose_name="ВКонтакте"),
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
                    ("instagram", "Instagram"),
                    ("vk", "ВКонтакте"),
                    ("other", "Другой"),
                ],
                max_length=20,
                verbose_name="Предпочтительный способ связи",
            ),
        ),
    ]
