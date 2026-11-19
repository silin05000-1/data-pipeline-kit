# data-pipeline-kit

Скрипт чистки и сборки данных с отправкой результата в REST API и уведомлениями в Telegram, Slack, email или произвольный webhook.

Проект написан на Python 3.10+ и **не требует сторонних библиотек** — только стандартная библиотека. Все секреты читаются из переменных окружения и никогда не попадают в репозиторий, логи или уведомления.

### Карточка кейса

- **Рутина:** вручную чистить и сводить CSV/JSON, загружать результат в API и писать отчёты в чаты — заменяется одним запуском.
- **Вход:** CSV / JSON / JSONL (локальный файл или URL) + JSON-конфиг правил; секреты — только в переменных окружения.
- **Выход:** очищенный CSV/JSON/JSONL, POST/PUT в REST API, уведомление в Telegram / Slack / email / webhook.
- **Экономия:** около 30–60 минут ручной работы на каждый регулярный прогон; повтор запуска — одна команда.

## Что делает скрипт

Конвейер выполняет шаги в фиксированном порядке:

1. **Загрузка** — читает данные из CSV, JSON или JSONL: локальный файл или HTTP(S)-URL. Несколько источников объединяются (конкатенация или JOIN по ключу).
2. **Очистка** — нормализация названий колонок, удаление пустых строк, trim пробелов, переименование/удаление колонок, приведение типов (`int`, `float`, `bool`, `date`), заполнение пропусков, фильтры, дедупликация.
3. **Валидация** — обязательные поля, регулярные выражения, уникальность, минимальное число строк. При ошибке конвейер останавливается.
4. **Сборка** — группировка с агрегатами `sum`, `count`, `avg`, `min`, `max`, `first`, `last`, `nunique`.
5. **Вывод** — запись в CSV / JSON / JSONL.
6. **REST API** — отправка результата на настроенный endpoint с bearer/basic/ header-авторизацией, повторными попытками и экспоненциальной задержкой.
7. **Уведомления** — отчёт об успехе и/или ошибке в Telegram, Slack, email и/или generic webhook.

## Быстрый старт

Репозиторий: [https://github.com/silin05000-1/data-pipeline-kit.git](https://github.com/silin05000-1/data-pipeline-kit.git)

```bash
git clone https://github.com/silin05000-1/data-pipeline-kit.git
cd data-pipeline-kit

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .

# Проверка конфигурации и «сухой прогон» (без записи, API и уведомлений)
python -m pipeline --config examples/config.json --validate-config
python -m pipeline --config examples/config.json --dry-run

# Реальный запуск демо-конфигурации
python -m pipeline --config examples/config.json --summary-json
```

Результат демо-запуска появится в `out/result.csv`:

```csv
status,amount_sum,order_id_count
paid,820.5,4
pending,200.0,1
```

Запуск без установки пакета тоже работает:

```bash
PYTHONPATH=src python3 -m pipeline --config examples/config.json
```

## Переменные окружения и секреты

Скопируйте шаблон и заполните значения:

```bash
cp .env.example .env
set -a && source .env && set +a
```

Файл `.env` добавлен в `.gitignore`. **Никогда не передавайте токены в аргументах CLI и не пишите их в JSON-конфиг.** В конфиге указываются только *имена* переменных (`token_env`, `webhook_url_env`, …) или плейсхолдеры вида `${API_TOKEN}`.

Поддерживаются два способа:

```json
{
  "url": "${API_URL:-https://httpbin.org/post}",
  "api": {"auth": {"type": "bearer", "token_env": "API_TOKEN"}}
}
```

- `${NAME}` — обязательная переменная; при отсутствии запуск завершится ошибкой с указанием имени.
- `${NAME:-значение}` — переменная с значением по умолчанию.
- `*_env` — имя переменной, содержащей секрет. Такое значение регистрируется в лог-фильтре и заменяется на `***` во всех логах и уведомлениях.

## Описание конфигурации

### Источники

```json
"sources": [
  {"name": "orders", "type": "csv", "path": "examples/input.csv", "delimiter": ","},
  {"name": "managers", "type": "json", "path": "examples/users.json", "root": null},
  {"name": "remote", "type": "jsonl", "url": "https://example.test/rows.jsonl"}
]
```

- `type`: `csv`, `json`, `jsonl`;
- `path` или `url` — источник; также поддерживаются `"rows": [...]` (данные прямо в конфиге);
- `root` — ключ списка в JSON (например, `"data"`);
- `encoding`, `delimiter`, `timeout` — необязательные параметры.

Несколько источников по умолчанию объединяются последовательно. Для JOIN добавьте:

```json
"merge": {"on": "order_id", "how": "left"}
```

`how`: `left`, `right`, `inner`, `outer`.

### Очистка (`clean`)

| Ключ | Что делает |
|---|---|
| `normalize_headers` | имена колонок → `snake_case` (по умолчанию `true`) |
| `strip_whitespace` | обрезка пробелов у строк (по умолчанию `true`) |
| `drop_empty_rows` | удаление полностью пустых строк (по умолчанию `true`) |
| `rename` | `{"старое": "новое"}` |
| `drop_columns` | список колонок для удаления |
| `cast` | `{"колонка": "int\|float\|bool\|date"}` |
| `fill` | значения для пустых ячеек |
| `filters` | список правил (см. ниже) |
| `drop_duplicates` | `["id"]` — по ключу, `true` — по всей строке |

Операторы фильтров: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, `regex`, `not_null`, `is_null`.

```json
"filters": [
  {"field": "amount", "op": "gte", "value": 10},
  {"field": "status", "op": "in", "value": ["paid", "pending"]}
]
```

### Валидация (`validate`)

```json
{
  "required": ["order_id", "status"],
  "regex": {"email": "^[^@]+@[^@]+\\.[^@]+$"},
  "unique": ["order_id"],
  "min_rows": 1
}
```

### Сборка (`transform`)

```json
"transform": {
  "group_by": {
    "by": ["status"],
    "aggs": {"amount": "sum", "order_id": "count"}
  }
}
```

Имена выходных колонок: `<поле>_<агрегат>`, например `amount_sum`.

### Вывод (`output`)

```json
"output": {"path": "out/result.json", "format": "json"}
```

Форматы: `csv`, `json`, `jsonl`.

### REST API (`api`)

```json
"api": {
  "enabled": true,
  "method": "POST",
  "url": "${API_URL:-https://httpbin.org/post}",
  "auth": {"type": "bearer", "token_env": "API_TOKEN"},
  "payload_key": "rows",
  "include_meta": true,
  "timeout": 20,
  "retry": {"attempts": 3, "backoff": 1.0},
  "expect_status": [200, 201, 202, 204]
}
```

- `auth.type`: `bearer` (`token_env`), `basic` (`username_env` + `password_env`) или `header` (`name` + `value_env`);
- `payload_key` — имя ключа для строк; без него отправляется массив;
- `include_meta` — добавить метаданные запуска в тело запроса;
- `headers` — дополнительные заголовки;
- `retry.attempts` и `retry.backoff` — число попыток и базовая задержка (удваивается после каждой неудачи);
- при `enabled: false` (по умолчанию) вызов не выполняется.

Формат тела запроса:

```json
{
  "meta": {"name": "demo orders", "rows_out": 2, "started_at": "..."},
  "data": {"rows": [{"status": "paid", "amount_sum": 820.5}]}
}
```

### Уведомления (`notify`)

```json
"notify": {
  "on": ["success", "failure"],
  "telegram": {"enabled": true, "bot_token_env": "TELEGRAM_BOT_TOKEN", "chat_id_env": "TELEGRAM_CHAT_ID"},
  "slack": {"enabled": true, "webhook_url_env": "SLACK_WEBHOOK_URL"},
  "email": {
    "enabled": false,
    "host": "smtp.example.com", "port": 587, "use_tls": true,
    "from": "pipeline@example.com", "to": ["ops@example.com"],
    "username_env": "SMTP_USER", "password_env": "SMTP_PASSWORD"
  },
  "webhook": {"enabled": false, "url": "${NOTIFY_WEBHOOK_URL}"}
}
```

- `on` — события, при которых отправлять уведомления;
- `strict: true` — считать ошибку уведомления ошибкой конвейера (по умолчанию ошибки уведомлений только логируются);
- для email доступны `use_ssl` (SMTP_SSL, порт 465) и `use_tls` (STARTTLS, по умолчанию `true`).

Полный пример со всеми интеграциями: [`examples/config_full.json`](examples/config_full.json).

## CLI

```bash
python -m pipeline --config examples/config.json --dry-run
python -m pipeline --config examples/config.json --validate-config
python -m pipeline --config examples/config.json --log-level DEBUG --log-file out/pipeline.log
python -m pipeline --config examples/config.json --summary-json
```

| Флаг | Назначение |
|---|---|
| `-c, --config` | путь к JSON-конфигу (по умолчанию `config.json`) |
| `--dry-run` | обработать данные, но не писать файлы, не вызывать API и не отправлять уведомления |
| `--validate-config` | только проверить конфиг и наличие переменных окружения |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-file` | дополнительно писать логи в файл |
| `--summary-json` | вывести итоговую сводку в JSON |
| `-v, --version` | версия |

Коды возврата: `0` — успех, `1` — ошибка конфигурации/данных/API, `130` — прерывание.

## Тесты

```bash
python -m unittest discover -s tests -t . -v
```

## Структура

```
src/pipeline/
  cli.py            # аргументы командной строки
  pipeline.py       # оркестрация шагов
  config.py         # JSON-конфиг и подстановка env
  sources.py        # чтение CSV/JSON/JSONL и JOIN
  cleaner.py        # шаги очистки и валидации
  transform.py      # группировка и агрегаты
  writers.py        # запись результата
  api.py            # REST API-клиент с ретраями
  notify.py         # Telegram / Slack / email / webhook
  logging_utils.py  # логирование и маскировка секретов
  errors.py         # исключения
examples/           # демо-данные и конфигурации
tests/              # unit-тесты
```

## Безопасность

- В репозитории нет токенов, паролей и ключей — только имена переменных окружения.
- `.env` и файлы ключей (`*.pem`, `*.key`, `*.p12`) игнорируются Git.
- Значения секретов заменяются на `***` в логах и тексте уведомлений.
- Перед коммитом проверьте `git status` и убедитесь, что в конфигах нет реальных значений.

## Лицензия

MIT — см. [LICENSE](LICENSE).
