from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    CRMRole,
    Client,
    Event,
    EventCommunication,
    EventExpense,
    EventFormat,
    EventFormatBudgetTemplate,
    EventFormatTaskTemplate,
    EventFormatTimelineTemplate,
    EventFormatVendorTemplate,
    EventOutcome,
    Lead,
    PipelineStage,
    ServicePackage,
    TeamMemberProfile,
    Vendor,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Loads reusable demo data for the CRM project."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Loading demo data...")

        users = self.create_users()
        stages = {stage.code: stage for stage in PipelineStage.objects.all()}
        formats = self.create_formats_and_templates()
        vendors = self.create_vendors(formats)
        self.create_packages(formats)
        leads = self.create_leads(users, stages, formats)
        clients = self.create_clients(leads)
        self.create_events(users, clients, leads, formats, vendors)

        self.stdout.write(self.style.SUCCESS("Demo data loaded successfully."))

    def create_users(self):
        user_specs = [
            ("sales_anna", "sales_anna@example.com", "SalesAnna123!", CRMRole.SALES_MANAGER, True, True, False, False),
            ("sales_igor", "sales_igor@example.com", "SalesIgor123!", CRMRole.SALES_MANAGER, True, True, False, False),
            ("pm_elena", "pm_elena@example.com", "ProjectElena123!", CRMRole.PROJECT_MANAGER, True, True, True, False),
            ("finance_max", "finance_max@example.com", "FinanceMax123!", CRMRole.FINANCE, True, False, True, False),
            ("admin_kate", "admin_kate@example.com", "AdminKate123!", CRMRole.ADMIN, True, True, True, True),
        ]
        users = {}
        for username, email, password, role, finance, clients, analytics, system in user_specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email},
            )
            if created:
                user.email = email
                user.set_password(password)
                user.save()
            TeamMemberProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": role,
                    "can_view_finance": finance,
                    "can_view_clients": clients,
                    "can_view_analytics": analytics,
                    "can_manage_system": system,
                },
            )
            users[username] = user
        return users

    def create_formats_and_templates(self):
        specs = [
            {
                "name": "Свадьба",
                "description": "Полный цикл организации свадьбы с банкетом, церемонией и шоу-программой.",
                "budget": Decimal("1200000.00"),
                "tasks": [
                    ("Подготовить концепцию", "Согласовать стиль и moodboard.", -45),
                    ("Согласовать площадку", "Выбрать и забронировать локацию.", -40),
                    ("Подтвердить подрядчиков", "Фотограф, ведущий, декор.", -30),
                ],
                "timeline": [
                    ("15:00", "Сбор гостей", "Регистрация и welcome drink.", "Координатор"),
                    ("16:00", "Церемония", "Официальная часть.", "Ведущий"),
                    ("18:00", "Банкет", "Ужин и шоу-программа.", "Банкетный менеджер"),
                ],
                "budget_lines": [
                    ("Площадка", "Loft Hall", Decimal("350000.00")),
                    ("Декор", "Bloom Atelier", Decimal("220000.00")),
                    ("Фото/видео", "Visual Stories", Decimal("180000.00")),
                ],
            },
            {
                "name": "Корпоратив",
                "description": "Внутреннее или клиентское мероприятие компании с деловой и развлекательной частью.",
                "budget": Decimal("800000.00"),
                "tasks": [
                    ("Собрать бриф", "Понять цели компании и KPI мероприятия.", -35),
                    ("Согласовать технику", "Свет, звук, экран.", -20),
                    ("Подготовить сценарий", "Тайминг блока выступлений.", -14),
                ],
                "timeline": [
                    ("17:00", "Регистрация", "Встреча гостей.", "Администратор"),
                    ("18:00", "Официальная часть", "Выступление руководства.", "Project Manager"),
                    ("19:30", "Нетворкинг", "Фуршет и активности.", "Координатор"),
                ],
                "budget_lines": [
                    ("Техника", "Stage Pro", Decimal("150000.00")),
                    ("Кейтеринг", "Taste Factory", Decimal("210000.00")),
                    ("Сцена", "Event Build", Decimal("120000.00")),
                ],
            },
        ]

        formats = {}
        for spec in specs:
            event_format, _ = EventFormat.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "description": spec["description"],
                    "default_budget": spec["budget"],
                },
            )
            event_format.task_templates.all().delete()
            event_format.timeline_templates.all().delete()
            event_format.budget_templates.all().delete()
            event_format.vendor_templates.all().delete()

            for title, description, offset in spec["tasks"]:
                EventFormatTaskTemplate.objects.create(
                    event_format=event_format,
                    title=title,
                    description=description,
                    deadline_offset_days=offset,
                )
            for time, block, description, responsible in spec["timeline"]:
                EventFormatTimelineTemplate.objects.create(
                    event_format=event_format,
                    time=time,
                    block=block,
                    description=description,
                    responsible_label=responsible,
                )
            for category, vendor_name, amount in spec["budget_lines"]:
                EventFormatBudgetTemplate.objects.create(
                    event_format=event_format,
                    category=category,
                    vendor_name=vendor_name,
                    amount=amount,
                )
            formats[spec["name"]] = event_format
        return formats

    def create_vendors(self, formats):
        specs = [
            ("Bloom Atelier", "декоратор, флорист", ["Свадьба"], Decimal("150000.00"), Decimal("220000.00"), Decimal("4.80"), 95),
            ("Visual Stories", "фотограф, видеограф", ["Свадьба", "Корпоратив"], Decimal("120000.00"), Decimal("180000.00"), Decimal("4.90"), 98),
            ("Stage Pro", "свет, звук, экран", ["Корпоратив"], Decimal("90000.00"), Decimal("150000.00"), Decimal("4.70"), 93),
            ("Taste Factory", "кейтеринг", ["Корпоратив", "Свадьба"], Decimal("180000.00"), Decimal("260000.00"), Decimal("4.60"), 90),
        ]
        vendors = {}
        for name, roles, format_names, min_cost, avg_cost, rating, reliability in specs:
            vendor, _ = Vendor.objects.update_or_create(
                name=name,
                defaults={
                    "roles": roles,
                    "min_cost": min_cost,
                    "avg_cost": avg_cost,
                    "rating": rating,
                    "reliability": reliability,
                    "contacts": f"{name.lower().replace(' ', '')}@example.com",
                    "availability_notes": "Свободен по будням, подтверждение за 7 дней.",
                    "blacklisted": False,
                },
            )
            vendor.event_formats.set([formats[item] for item in format_names])
            vendors[name] = vendor

        EventFormatVendorTemplate.objects.create(
            event_format=formats["Свадьба"],
            vendor=vendors["Bloom Atelier"],
            role="Декор",
            cost=Decimal("220000.00"),
        )
        EventFormatVendorTemplate.objects.create(
            event_format=formats["Свадьба"],
            vendor=vendors["Visual Stories"],
            role="Фото/видео",
            cost=Decimal("180000.00"),
        )
        EventFormatVendorTemplate.objects.create(
            event_format=formats["Корпоратив"],
            vendor=vendors["Stage Pro"],
            role="Техника",
            cost=Decimal("150000.00"),
        )
        EventFormatVendorTemplate.objects.create(
            event_format=formats["Корпоратив"],
            vendor=vendors["Taste Factory"],
            role="Кейтеринг",
            cost=Decimal("210000.00"),
        )
        return vendors

    def create_packages(self, formats):
        packages = [
            (
                "Wedding Premium",
                formats["Свадьба"],
                "Концепция, площадка, координация, фото/видео, декор, шоу-программа.",
                Decimal("1650000.00"),
            ),
            (
                "Corporate Launch",
                formats["Корпоратив"],
                "Бриф, площадка, техника, кейтеринг, продакшн, координация.",
                Decimal("980000.00"),
            ),
        ]
        for name, event_format, services, price in packages:
            ServicePackage.objects.update_or_create(
                name=name,
                defaults={
                    "event_format": event_format,
                    "services": services,
                    "price": price,
                },
            )

    def create_leads(self, users, stages, formats):
        leads = {}
        specs = [
            (
                "Анна и Михаил",
                "+7 999 111-22-33",
                "anna@example.com",
                "@anna_wed",
                "Instagram",
                formats["Свадьба"],
                "Ищут организацию свадьбы под ключ на 120 гостей.",
                "proposal_sent",
                users["sales_anna"],
                timezone.now() - timezone.timedelta(hours=6),
            ),
            (
                "ООО Альфа Тех",
                "+7 999 222-33-44",
                "events@alphatech.ru",
                "",
                "сайт",
                formats["Корпоратив"],
                "Нужен летний корпоратив для команды из 200 человек.",
                "negotiation",
                users["sales_igor"],
                timezone.now() - timezone.timedelta(hours=10),
            ),
            (
                "Екатерина Смирнова",
                "+7 999 333-44-55",
                "katya@example.com",
                "@katya_party",
                "рекомендация",
                formats["Свадьба"],
                "Запрос на камерную свадьбу в Подмосковье.",
                "contacted",
                users["sales_anna"],
                None,
            ),
        ]
        for name, phone, email, messenger, source, event_format, comment, stage_code, manager, last_contact in specs:
            lead, _ = Lead.objects.update_or_create(
                name=name,
                defaults={
                    "phone": phone,
                    "email": email,
                    "messenger": messenger,
                    "source": source,
                    "preliminary_event_format": event_format,
                    "comment": comment,
                    "stage": stages[stage_code],
                    "probability": stages[stage_code].probability,
                    "manager": manager,
                    "last_contact_at": last_contact,
                },
            )
            leads[name] = lead
        return leads

    def create_clients(self, leads):
        clients = {}
        specs = [
            (
                "Анна и Михаил",
                leads["Анна и Михаил"],
                Client.ClientType.B2C,
                Client.Segment.VIP,
                Decimal("1800000.00"),
                "Любят современную классику, важен сервис уровня concierge.",
            ),
            (
                "ООО Альфа Тех",
                leads["ООО Альфа Тех"],
                Client.ClientType.B2B,
                Client.Segment.STANDARD,
                Decimal("2500000.00"),
                "Сильный бренд-слой, важна отчётность по KPI и чёткий тайминг.",
            ),
        ]
        for name, lead, client_type, segment, ltv, preferences in specs:
            client, _ = Client.objects.update_or_create(
                name=name,
                defaults={
                    "lead": lead,
                    "client_type": client_type,
                    "phone": lead.phone,
                    "email": lead.email,
                    "messenger": lead.messenger,
                    "contacts": f"{lead.phone}, {lead.email}",
                    "segment": segment,
                    "ltv": ltv,
                    "preferences": preferences,
                    "event_history": "Первый проект в CRM" if not Event.objects.filter(client__name=name).exists() else "Повторный клиент",
                },
            )
            clients[name] = client
        return clients

    def create_events(self, users, clients, leads, formats, vendors):
        event_specs = [
            {
                "title": "Свадьба Анны и Михаила",
                "client": clients["Анна и Михаил"],
                "lead": leads["Анна и Михаил"],
                "event_format": formats["Свадьба"],
                "date": timezone.localdate() + timezone.timedelta(days=45),
                "city": "Москва",
                "guests": 120,
                "budget": Decimal("1650000.00"),
                "goal": "Сделать премиальную свадьбу с сильным wow-эффектом.",
                "preferences": "Светлая палитра, живая музыка, фото-зоны.",
                "stop_factors": "Не использовать стандартный банкетный сценарий.",
                "status": Event.Status.PLANNING,
                "manager": users["pm_elena"],
                "communications": [
                    ("meeting", 2, "Очная встреча по сценарию и площадке."),
                    ("message", 1, "Отправили презентацию по декору."),
                ],
                "extra_expenses": [("Транспорт", "City Drive", Decimal("85000.00"), Decimal("30000.00"))],
                "outcome": False,
            },
            {
                "title": "Летний корпоратив Alpha Tech",
                "client": clients["ООО Альфа Тех"],
                "lead": leads["ООО Альфа Тех"],
                "event_format": formats["Корпоратив"],
                "date": timezone.localdate() + timezone.timedelta(days=20),
                "city": "Санкт-Петербург",
                "guests": 200,
                "budget": Decimal("980000.00"),
                "goal": "Усилить командную вовлечённость и employer brand.",
                "preferences": "Комбинация деловой части и вечернего нетворкинга.",
                "stop_factors": "Исключить задержки в официальной части.",
                "status": Event.Status.IN_PROGRESS,
                "manager": users["pm_elena"],
                "communications": [
                    ("call", 4, "Созвон по техническому райдеру."),
                    ("message", 1, "Подтверждение меню фуршета."),
                ],
                "extra_expenses": [("Полиграфия", "Print Lab", Decimal("45000.00"), Decimal("10000.00"))],
                "outcome": False,
            },
        ]

        for spec in event_specs:
            event, created = Event.objects.update_or_create(
                title=spec["title"],
                defaults={
                    "client": spec["client"],
                    "lead": spec["lead"],
                    "event_format": spec["event_format"],
                    "date": spec["date"],
                    "city": spec["city"],
                    "guests_count": spec["guests"],
                    "planned_budget": spec["budget"],
                    "goal": spec["goal"],
                    "preferences": spec["preferences"],
                    "stop_factors": spec["stop_factors"],
                    "status": spec["status"],
                    "manager": spec["manager"],
                },
            )
            if not created:
                event.bootstrap_from_format()
            for category, vendor_name, amount, prepayment in spec["extra_expenses"]:
                EventExpense.objects.update_or_create(
                    event=event,
                    category=category,
                    vendor_name=vendor_name,
                    defaults={
                        "amount": amount,
                        "prepayment": prepayment,
                        "payment_status": EventExpense.PaymentStatus.PARTIAL,
                    },
                )
            for communication_type, days_ago, comment in spec["communications"]:
                EventCommunication.objects.update_or_create(
                    event=event,
                    communication_type=communication_type,
                    date=timezone.now() - timezone.timedelta(days=days_ago),
                    defaults={"comment": comment, "manager": spec["manager"]},
                )

        completed_event, _ = Event.objects.update_or_create(
            title="Новогодний гала-ужин",
            defaults={
                "client": clients["ООО Альфа Тех"],
                "lead": leads["ООО Альфа Тех"],
                "event_format": formats["Корпоратив"],
                "date": timezone.localdate() - timezone.timedelta(days=70),
                "city": "Москва",
                "guests_count": 150,
                "planned_budget": Decimal("1100000.00"),
                "goal": "Подвести итоги года и наградить команду.",
                "preferences": "Строгий дресс-код и премиальный сервис.",
                "stop_factors": "Исключить паузы в награждении.",
                "status": Event.Status.COMPLETED,
                "manager": users["pm_elena"],
            },
        )
        EventExpense.objects.update_or_create(
            event=completed_event,
            category="Общий продакшн",
            vendor_name="Event Build",
            defaults={
                "amount": Decimal("760000.00"),
                "prepayment": Decimal("250000.00"),
                "payment_status": EventExpense.PaymentStatus.PAID,
            },
        )
        EventOutcome.objects.update_or_create(
            event=completed_event,
            defaults={
                "client_feedback": "Клиент отметил высокий уровень продакшна и сервиса.",
                "final_profit": Decimal("340000.00"),
                "lessons_learned": "Нужно раньше фиксировать финальный список гостей.",
                "media_links": "https://example.com/ny-gala-media",
                "project_rating": 9,
            },
        )
