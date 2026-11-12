# WebAudit AI — автономная платформа комплексного аудита веб-сайтов

Рекомендуемая концепция Hybrid AI Product

## 1. Суть проекта

WebAudit AI — AI-powered Website Quality Engineer.

Платформа, которая самостоятельно исследует сайт целиком, находит проблемы, оценивает их влияние на пользователей и бизнес, предлагает исправления и проверяет результат после изменений.

Это не просто SEO-аудитор с интегрированным LLM. Это мультиагентная система, объединяющая технический анализ, визуальную проверку и оценку пользовательского опыта.

Главная идея:

> AI должен не просто находить проблемы сайта, а доказывать их наличие, объяснять последствия, предлагать исправления и подтверждать улучшение качества.

## 2. Что анализирует WebAudit AI

Восемь направлений комплексного аудита:

## 01

SEO Audit

Индексация, метаданные, заголовки, canonical, sitemap, robots.txt, Schema.org, внутренние ссылки.

## 02

UX Audit

Навигация, пользовательские сценарии, CTA, формы, информационная архитектура.

## 03

UI / Design Audit

Типографика, контрасты, отступы, визуальная иерархия, консистентность интерфейса.

## 04

Accessibility Audit

WCAG 2.2 AA, клавиатурная навигация, screen readers, ARIA, семантический HTML.

## 05

Performance Audit

Core Web Vitals, LCP, INP, CLS, JavaScript, изображения, загрузка ресурсов.

## 06

Security Audit

HTTPS, TLS, security headers, CSP, cookies, mixed content, пассивные проверки конфигурации.

## 07

Responsive Audit

Mobile, tablet, desktop, overflow, адаптивность, touch targets.

## 08

Conversion Audit

Value proposition, CTA, формы, checkout, доверительные элементы и препятствия конверсии.

## 3. Как работает система

Website URL

Пользователь запускает аудит

Website Discovery & Crawling

Обнаружение страниц, шаблонов и сценариев

Specialized Audit Agents

SEO Agent

UX Agent

UI Agent

Accessibility Agent

Performance Agent

Security Agent

Conversion Agent

Chief Auditor

Дедупликация, проверка доказательств, приоритизация

Evidence-based Report

Проблемы, скриншоты, рекомендации, потенциальное влияние

Fix & Re-audit

Подготовка исправлений и повторная проверка

Важный архитектурный принцип: детерминированные инструменты собирают факты, LLM интерпретирует их, агенты формируют рекомендации. Не нужно поручать языковой модели вычисление контрастности, проверку HTTP-заголовков или измерение производительности.

## 4. Основные отличия продукта

WebAudit AI должен отличаться от обычных сканеров пятью возможностями:

1. Full-site analysis: исследование всего сайта с обнаружением шаблонов страниц, а не только проверка одного URL.
2. Cross-domain intelligence: обнаружение взаимосвязанных проблем SEO, UX, UI, Accessibility и Performance.
3. Evidence-based findings: каждое замечание подкреплено URL, скриншотом, HTML-элементом или измерением.
4. Business impact: оценка потенциального влияния проблемы на конверсию, SEO и пользовательский опыт.
5. Continuous monitoring: повторные аудиты после релизов и исправлений с отслеживанием динамики.

Например, если cookie-баннер перекрывает CTA на мобильном устройстве, система должна определить одну первопричину и связать с ней несколько последствий, а не выдавать четыре независимых замечания.

## 5. AI Engineering составляющая

Проект должен демонстрировать практически весь цикл современной AI-разработки.

| Компетенция | Реализация |
| --- | --- |
| Agent loop | Автономные аудиторские агенты |
| LLM product | AI-анализ и рекомендации |
| MCP | Browser, crawler и audit tools |
| RAG | База стандартов WCAG, SEO и технических правил |
| Prompt engineering | Структурированные результаты аудита |
| Tool calling | Вызов проверяющих инструментов |
| Vision | Анализ скриншотов интерфейса |
| Evals | Precision, Recall, False Positives |
| Observability | Логи, трассировки, токены, стоимость |
| Self-improving | Улучшение prompts и правил по feedback |
| CI/CD | Автоматические проверки агентов и изменений |
| Security | Изоляция браузера и безопасный crawling |
| Product analytics | Повторные аудиты и динамика качества |
| Cost optimization | Стоимость аудита 100 страниц |

## 6. Технологический стек

| Компонент | Предлагаемые технологии |
| --- | --- |
| Backend | Python, FastAPI |
| Frontend | Next.js |
| Browser automation | Playwright |
| Crawling | Scrapy / собственный crawler |
| SEO | Lighthouse, собственные проверки |
| Accessibility | axe-core |
| Performance | Lighthouse, Chrome DevTools Protocol |
| AI | LLM API, Vision models |
| Agent orchestration | Собственный orchestrator |
| Tool protocol | MCP |
| RAG | PostgreSQL + pgvector |
| Database | PostgreSQL |
| Queue | Redis |
| Sandbox | Docker |
| Observability | OpenTelemetry |
| CI/CD | GitHub Actions |
| Automation | n8n |

## 7. MVP: 6–8 недель вечерами

Не нужно пытаться сразу создать полноценную платформу по всем направлениям.

Предлагаемый охват:

| Направление | Глубина MVP |
| --- | --- |
| SEO | Глубокая |
| Accessibility | Глубокая |
| Performance | Глубокая |
| UX | Эвристический AI-анализ |
| UI | Vision-анализ скриншотов |
| Responsive | Три разрешения |
| Security | Пассивные проверки |
| Conversion | Эвристическая оценка |

Начальный масштаб — 5–10 сайтов и 50–100 репрезентативных страниц в benchmark. Для оценки качества потребуется ручная разметка эталонных проблем.

## 8. Метрики и результаты

## Целевые показатели MVP

# 100+

Страниц в benchmark

# 8

Направлений аудита

# 3

Разрешения экрана

# 2+

Версии агента для сравнения

Метрики, которые попадут в публичный отчёт:

- Findings precision и recall.
- False positive rate.
- Duplicate finding rate.
- Pages audited.
- Audit cost per 100 pages.
- Median audit duration.
- Fix acceptance rate.
- Regression-free fix rate.
  Все числа в верхней части — плановые ориентиры, а не достигнутые результаты.

## 9. Конкуренты и позиционирование

Существующие инструменты уже закрывают значительную часть отдельных задач:

| Продукт | Основная специализация |
| --- | --- |
| Google Lighthouse | Performance, SEO, Accessibility |
| Screaming Frog | Техническое SEO и crawling |
| Siteimprove | SEO, Accessibility, Quality |
| Semrush | SEO |
| BrowserStack | Cross-browser testing |
| WAVE | Accessibility |

WebAudit AI не должен пытаться заменить все эти продукты. Его ценность — объединение результатов, интеллектуальная интерпретация, поиск взаимосвязей, проверяемые рекомендации и контроль исправлений.

## 10. Что должно остаться после разработки

Четыре публичных артефакта:

1. GitHub Repository — полноценная реализация, тесты, AGENTS.md, CI/CD и документация.
2. Live Demo — интерфейс аудита сайта с реальными результатами.
3. Public Benchmark — набор страниц, эталонные проблемы и воспроизводимые результаты.
4. Engineering Report — сравнение качества, скорости, стоимости и точности разных версий AI-системы.

### Формулировка для CV

> Built WebAudit AI, an autonomous multi-agent website quality auditing platform covering SEO, UX, UI, accessibility, performance and security. Implemented browser automation, MCP tool integrations, vision-based analysis, evidence-driven findings, evaluation pipelines and automated re-auditing. Measured detection precision, false-positive rates and audit cost across \[N\] pages.

## Итоговое позиционирование

# WebAudit AI

## Autonomous Website Quality Engineer

Что делает: исследует сайт целиком, выявляет проблемы, объясняет их последствия, предлагает исправления и проверяет результат.

Для кого: владельцы сайтов, разработчики, SEO-специалисты и веб-агентства.

Главное отличие: не просто сканирует сайт, а объединяет технические факты, визуальный анализ и AI-интерпретацию в единый проверяемый аудит.

Формат: SaaS с возможностью регулярного мониторинга.

Срок MVP: 6–8 недель вечерами.

Моя рекомендация: оставить A11yGate как исходную идею и развивать её под брендом WebAudit AI. Accessibility станет одним из наиболее глубоких и хорошо измеряемых модулей, а не всем продуктом. Это даст более широкий продуктовый потенциал и одновременно позволит продемонстрировать серьёзную инженерную работу с агентами, браузерной автоматизацией, vision-моделями и evals.