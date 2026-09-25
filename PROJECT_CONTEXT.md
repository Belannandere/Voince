# Voince — Project Context

## 1. Что это

Voince — SaaS для автоматического извлечения данных из PDF-инвойсов.

Пользователь:
1. регистрируется / входит;
2. загружает PDF invoice;
3. AI извлекает данные;
4. Python валидирует данные;
5. пользователь проверяет и редактирует результат;
6. пользователь может Approve / Reject;
7. результат можно экспортировать в CSV / Excel.

Главная идея:
AI используется для extraction, но финансовая логика и validation выполняются детерминированным Python-кодом.

---

## 2. Текущий статус

Проект является работающим MVP, который готовится к публичному SaaS deployment.

Есть:

- регистрация;
- login;
- email/password;
- Google OAuth;
- GitHub OAuth;
- user sessions;
- user data isolation;
- invoice upload;
- PDF text extraction;
- Ollama + Llama;
- structured JSON extraction;
- Pydantic validation;
- business validation;
- invoice review;
- inline editing;
- line items editing;
- Approve / Reject;
- SQLite;
- CSV export;
- Excel export;
- monthly usage limits;
- Free plan;
- Pro plan;
- pricing page;
- crypto payment;
- internal balance;
- automatic subscription renewal;
- settings;
- dark UI;
- multilingual UI.

---

## 3. Тарифы

Free:
- $0/month
- 10 invoices/month

Pro:
- $10/month
- 100 invoices/month
- priority processing
- future premium features

Оплата:
crypto only.

---

## 4. AI

Current AI architecture:

PDF
↓
pypdf
↓
Ollama
↓
Llama 3.2
↓
structured JSON
↓
Pydantic
↓
Python validation
↓
SQLite
↓
Web UI
↓
CSV / Excel

AI не принимает финансовые решения.

---

## 5. Ограничения

Пока нет:

- OCR для scanned PDFs;
- email invoice import;
- QuickBooks integration;
- Xero integration.

Поддерживаются PDF с текстовым слоем.

---

## 6. Backend

Stack:

- Python 3.11+
- FastAPI
- Uvicorn
- Jinja2
- Bootstrap
- SQLModel
- SQLAlchemy
- SQLite
- Pydantic 2
- pypdf
- httpx
- Ollama

---

## 7. Production goal

Проект должен работать на VPS.

Предполагаемая архитектура:

Internet
↓
Domain
↓
Nginx
↓
FastAPI
↓
Ollama
↓
Llama

На первом этапе не использовать Kubernetes,
микросервисы, Redis или Celery без необходимости.

Главная цель:
простой, дешёвый и стабильный production deployment.

---

## 8. Production environment

Планируется:

Ubuntu VPS
+
Nginx
+
HTTPS
+
systemd
+
FastAPI
+
Ollama
+
SQLite

В будущем SQLite может быть заменён на PostgreSQL.

---

## 9. Navigation

Для авторизованного пользователя:

Invoices | Upload | Pricing

Справа:

language selector | usage | profile

Для неавторизованного пользователя:

Features | How it works | Pricing

Справа:

Log in | Get started

---

## 10. UI

Стиль:

- dark theme;
- modern SaaS;
- minimal;
- purple accent;
- rounded cards;
- clean typography;
- responsive;
- desktop + mobile.

Не нужно полностью переделывать дизайн без необходимости.

---

## 11. Landing page

На landing page есть:

- hero;
- Upload Invoice CTA;
- View invoices;
- benefits;
- upload area;
- How it works;
- example result;
- pricing;
- FAQ.

Основной message:

Upload invoice → AI extracts data → Review → Export.

---

## 12. Account

Account показывает:

- email;
- member since;
- current plan;
- monthly usage;
- remaining invoices;
- balance;
- subscription.

---

## 13. Settings

Settings позволяет:

- change email;
- change password;
- delete account.

Удаление аккаунта должно удалять пользовательские данные.

---

## 14. Security requirements

Критически важно:

User A must NEVER be able to access User B's invoices.

Все invoice queries должны быть scoped to authenticated user.

Frontend нельзя считать доверенным источником.

Все limits должны проверяться backend.

Passwords должны храниться только в hashed form.

Secrets должны находиться в .env.

---

## 15. Current task

Текущая задача:

Подготовить Voince к production deployment на VPS.

Нужно проверить:

- production configuration;
- .env;
- security;
- authentication;
- OAuth;
- database;
- file storage;
- upload security;
- billing;
- webhooks;
- limits;
- Ollama;
- logging;
- health checks;
- error handling;
- systemd;
- nginx;
- HTTPS;
- domain;
- backups.

---

## 16. Important development rules

НЕ переписывать проект с нуля.

НЕ менять существующую архитектуру без необходимости.

НЕ удалять работающие функции.

НЕ менять UI без прямой необходимости.

Сначала анализировать существующий код.

Если можно решить проблему минимальным изменением — использовать минимальное изменение.

После каждого изменения проверять, что существующий функционал не сломан.

---

## 17. Repository structure

[ЗДЕСЬ НУЖНО ВСТАВИТЬ АКТУАЛЬНУЮ СТРУКТУРУ ПРОЕКТА]

Например:

app/
├── main.py
├── config.py
├── database.py
├── models.py
├── schemas.py
├── repository.py
├── ai.py
├── pdf.py
├── validation.py
├── export.py
├── timing.py
└── ...

templates/
static/
docs/
requirements.txt
.env.example
README.md

---

## 18. Important

Перед внесением изменений:

1. Проанализируй проект.
2. Определи существующую архитектуру.
3. Не предполагай, что код устроен так, как описано выше.
4. Если PROJECT_CONTEXT противоречит реальному коду — доверяй реальному коду.
5. Покажи, какие файлы нужно изменить.
6. Затем внеси минимальные изменения.

Главная цель:
сделать Voince стабильным SaaS для первых реальных пользователей.