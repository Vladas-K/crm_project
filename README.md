# CRM Project

CRM-проект для event-агентства на Django с шаблонами и Bootstrap.

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Что уже есть

- Django-проект `crm_project`
- Приложение `core`
- Bootstrap через CDN
- Разделы CRM:
  - дашборд
  - лиды
  - воронка продаж
  - клиенты
  - мероприятия
  - форматы мероприятий
  - подрядчики
  - пакеты услуг
  - календарь
  - аналитика
  - пользователи и роли
- Архитектура данных:
  - `Lead`
  - `PipelineStage`
  - `Client`
  - `Event`
  - `EventExpense`
  - `EventVendor`
  - `EventTask`
  - `EventTimelineItem`
  - `EventRisk`
  - `EventCommunication`
  - `EventDocument`
  - `EventOutcome`
  - `EventFormat` и его шаблоны
  - `Vendor`
  - `ServicePackage`
  - `TeamMemberProfile`
- Автологика:
  - автоназначение `Sales Manager` для новых лидов
  - контроль лида без ответа более 24 часов
  - автосоздание задач, тайминга, бюджета и подрядчиков при выборе формата мероприятия

## Следующий шаг

Можно добавить авторизацию, CRUD-формы, фильтры, поиск, сиды тестовых данных и перенос точного визуала из `CRM fin.pages`.
