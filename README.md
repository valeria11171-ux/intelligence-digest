# Intelligence Digest Agent

Рабочий прототип для полуфинала хакатона «ИИ-ассистенты для энергетики». Система получает ИТ/ИБ-публикации, персонализированно ранжирует их, объединяет публикации в события, объясняет отбор и экспортирует дайджест в Markdown/DOCX.

## Что реализовано

- **Источники, которые добавляет сам пользователь**: ссылка на сайт (RSS находится автоматически), RSS/Atom, публичный Telegram-канал (`t.me/канал`, `@канал`), отдельная статья. Тип определяется сам, источник проверяется перед добавлением; у каждого источника виден статус, число материалов и ошибка; сбой одного не ломает остальные (`app/sources.py`, `configs/sources.yaml`);
- **собственные интересы**: любые слова и фразы на русском и английском (русская морфология: «уязвимость» находит «уязвимости»); каждый интерес становится тематическим разделом дайджеста;
- **период**: день / неделя / месяц (ежедневный для специалистов, ежемесячный для руководства);
- **обратная связь 👍/👎**: меняет веса интересов и подстраивает отбор под похожие материалы; профиль сохраняется в JSON;
- группировка публикаций об одном событии (общий CVE или тематическая близость), дедупликация;
- **доказуемость**: у каждого события ссылки на все первоисточники с датой и цитата-основание из текста;
- Markdown и DOCX (с кликабельными ссылками), веб-интерфейс Streamlit, CLI, FastAPI;
- структурное извлечение: CVE, CVSS, exploit/PoC; бизнес-теги для руководителя;
- режим «Приоритет РФ / энергетика / КИИ» включается по желанию (по умолчанию ассистент универсальный);
- golden dataset организаторов, метрики Precision@K/Recall@K/NDCG@K, 16 автотестов (включая сквозной тест с локальным RSS-сервером и тест интерфейса).

### CLI

```
python -m app.cli --audience tech --period day   --interests "CVE,Exchange,Kubernetes" --out artifacts/daily.md --docx
python -m app.cli --audience mgmt --period month --add-source https://t.me/true_secator --out artifacts/monthly.md
python -m app.cli --demo        # без сети
```

## Быстрый запуск

Требуется Python 3.11+.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows: .venv\\Scripts\\activate

pip install -e ".[dev]"
pytest -q
streamlit run frontend/app.py
```

Откройте `http://localhost:8501`.

API:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Swagger: `http://localhost:8000/docs`.

## Воспроизводимое demo

```bash
PYTHONPATH=. python scripts/demo.py
```

Создаёт в `artifacts/` Markdown и DOCX для двух персон. На одном наборе входных данных Security Engineer получает CVE/ransomware/Kubernetes, CIO — AI/cloud. Это демонстрирует обязательное требование «изменение подборки при изменении интересов».

Benchmark:

```bash
PYTHONPATH=. python scripts/benchmark.py
```

## Архитектура

```text
RSS / HTML / API / frozen corpus
             |
             v
      normalization
             |
             v
 lexical + semantic retrieval
             |
             v
 organizer-aware scoring
             |
             v
 dedup + event clustering
             |
        +----+----+
        |         |
 technical     executive
 extraction     tagging
        |         |
        +----+----+
             |
             v
 explainable digest -> Markdown / DOCX / API / UI
```

LLM вынесена за интерфейс `app/llm/base.py`. Основной сценарий не зависит от конкретного провайдера. Без API-ключа прототип полностью работает детерминированно; подключение Qwen/gpt-oss/Yandex-compatible модели улучшает summaries/judging, но не является single point of failure.

## Данные организаторов

Исходный XLSX сохранён в `data/reference/organizer_examples_v4.0.xlsx`. Нормализованные требования находятся в `app/evaluation/golden_dataset.py`, выводы — `docs/DATASET_FINDINGS.md`.

Фактические контракты из XLSX:

- technical: `Атака / Уязвимость / Инфо`, приоритет и структурированные признаки;
- executive: event-centric brief + 12 бизнес-тегов;
- энергетика/КИИ — сильный сигнал значимости;
- exploit/PoC повышает приоритет уязвимости;
- несколько публикаций об одном событии должны объединяться.

## Структура

```text
app/
  api/              FastAPI
  ingestion/        RSS/HTML connectors
  retrieval/        lexical + semantic retrieval
  intelligence/     scoring, extraction, clustering, feedback
  digest/           Markdown/DOCX
  evaluation/       golden set + metrics
  llm/              replaceable model interface
frontend/            Streamlit demo
configs/             profiles/taxonomy
data/                sample + organizer workbook
tests/               automated tests
scripts/             demo + benchmark
docs/                architecture/team/dataset/submission notes
artifacts/            generated examples
```

## Сценарий защиты (3 минуты)

1. Показать входной поток и счётчики `публикации -> события`.
2. Security Engineer: CVE/ransomware/Kubernetes, structured details, score и причины.
3. Переключить на CIO без изменения corpus: AI/cloud + executive representation.
4. Открыть источники и explainability.
5. Скачать DOCX.
6. На архитектурном слайде подчеркнуть model-agnostic design, event-centric clustering и organizer-aligned evaluation.

## Ограничения прототипа

- frozen corpus небольшой и предназначен для стабильного offline demo;
- rule-based extraction не заменяет полноценный NER/LLM judge на сложных текстах;
- live HTML зависит от структуры/доступности внешних сайтов;
- benchmark XLSX содержит примеры результатов, но не полный размеченный отрицательный corpus, поэтому нельзя честно заявлять production-level Recall на всём новостном потоке;
- перед production нужны persistent storage, scheduler, observability, auth/RBAC, source allowlist и security review.

## Что сдавать

1. весь этот репозиторий в выданный GitLab;
2. `submission/presentation.pdf`;
3. `artifacts/digest_security_engineer.docx` и `artifacts/digest_cio.docx` как примеры результата;
4. исходный organizer XLSX уже лежит в `data/reference/`;
5. README является инструкцией запуска и описанием возможностей/ограничений.

## Быстрый запуск демо (Windows / Python 3.11+)

Если нужен только интерфейс прототипа без API и внешней LLM:

```bash
python -m pip install -r requirements-demo.txt
python -m streamlit run frontend/app.py
```

При первом запуске Streamlit может запросить email — оставьте поле пустым и нажмите Enter.
Откройте `http://localhost:8501`.

### Сценарий демонстрации для жюри

1. Выберите **ИБ / ИТ специалист**: CVE, Microsoft, Kubernetes, ransomware — в топе окажутся технические ИБ-события.
2. Переключитесь на **Руководитель**: AI, cloud, regulation, digital transformation — состав и приоритеты дайджеста изменятся.
3. Покажите объяснение «Почему важно», сигналы отбора и ссылки на первоисточники.
4. Скачайте результат в Markdown или DOCX.

Так демонстрируется полный обязательный сценарий: входные публикации → персональный отбор → тематическая группировка → объяснимый дайджест → экспорт.
