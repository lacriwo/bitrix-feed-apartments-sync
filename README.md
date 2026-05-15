# bitrix-feed-apartments-sync

Автоматически подтягивает XML-фид квартир из **1С-Битрикс** (формат Яндекс.Недвижимость) и сохраняет актуальный список в `data/apartments.json`.

## Как это работает

1. Скрипт [`scripts/sync_feed.py`](scripts/sync_feed.py) скачивает фид по URL, парсит все `<offer>` и пишет JSON.
2. GitHub Actions ([`.github/workflows/sync-feed.yml`](.github/workflows/sync-feed.yml)) запускается **по расписанию** (каждые ~30 минут) и вручную (**Actions → Sync apartments from Bitrix feed → Run workflow**).
3. Если данные изменились относительно предыдущего коммита, workflow делает коммит `chore: sync apartments from Bitrix feed`.

Таким образом **список квартир в репозитории обновляется всякий раз, когда в Битриксе обновился фид** (с задержкой до одного интервала cron).

## Подключение к сайту / приложению

- Сырой JSON: `https://raw.githubusercontent.com/<ваш-логин>/bitrix-feed-apartments-sync/main/data/apartments.json` (после публикации репозитория).
- Либо клонируйте репозиторий / используйте GitHub API для получения того же файла.

## Настройка URL фида

По умолчанию используется публичный URL:

`https://bx.sskuban.ru/local/integrat/feed/jcat/9019077`

Чтобы указать другой фид, в репозитории GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|--------|
| `BITRIX_FEED_URL` | полный HTTPS-URL вашего XML-фида |

При ручном запуске workflow можно передать поле **feed_url** (переопределяет секрет и значение по умолчанию).

## Локальный запуск

```bash
python scripts/sync_feed.py
```

Переменные окружения:

| Переменная | Назначение |
|------------|------------|
| `FEED_URL` | URL XML-фида |
| `OUT_JSON` | путь к выходному `apartments.json` (по умолчанию `data/apartments.json`) |
| `OUT_META` | путь к `sync_meta.json` |

## Формат `data/apartments.json`

Корневой объект:

- `feed_url`, `generation_date` — из фида
- `synced_at` — время генерации JSON (UTC, ISO 8601)
- `count` — число квартир
- `apartments` — массив объектов с полями: `internal_id`, цена, адрес, комнаты, этаж, площадь, литер, `yandex_*`, первые до 30 URL картинок и др.

## Лицензия

MIT
