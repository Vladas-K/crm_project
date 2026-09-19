from django.db import migrations, models

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_normalize_vendor_role_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="contact_person",
            field=models.CharField(blank=True, max_length=255, verbose_name="Контактное лицо"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="contact_position",
            field=models.CharField(blank=True, max_length=150, verbose_name="Должность контактного лица"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Email"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="phone",
            field=models.CharField(blank=True, max_length=30, verbose_name="Телефон"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="preferred_contact_method",
            field=models.CharField(
                blank=True,
                choices=[("phone", "Телефон"), ("email", "Email"), ("telegram", "Telegram"), ("other", "Другой")],
                max_length=20,
                verbose_name="Предпочтительный способ связи",
            ),
        ),
        migrations.AddField(
            model_name="vendor",
            name="service_area",
            field=models.CharField(blank=True, max_length=255, verbose_name="Город / регион работы"),
        ),
        migrations.AddField(
            model_name="vendor",
            name="social_links",
            field=models.TextField(
                blank=True,
                help_text="Полные ссылки, включая https://, по одной в строке",
                validators=[core.models.validate_url_list],
                verbose_name="Соцсети и портфолио",
            ),
        ),
        migrations.AddField(
            model_name="vendor",
            name="telegram",
            field=models.CharField(
                blank=True,
                help_text="Username или полная ссылка",
                max_length=150,
                verbose_name="Telegram",
            ),
        ),
        migrations.AddField(
            model_name="vendor",
            name="website",
            field=models.URLField(blank=True, verbose_name="Сайт"),
        ),
        migrations.RemoveField(
            model_name="vendor",
            name="contacts",
        ),
    ]
