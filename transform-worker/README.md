# Публичный фид metarealty/2024-12 (Яндекс «Квартиры» / Поиск недвижимости)

Этот Worker **не хранит** XML в GitHub: при каждом запросе он скачивает актуальный фид с Битрикса, **преобразует** под требования PDF (корень `realty-feed`, `xmlns="http://webmaster.yandex.ru/schemas/feed/metarealty/2024-12"`, обязательные поля, порядок картинок, `decoration-type` вместо `renovation`, упрощённый `location`, валюта `RUB`, и т.д.) и отдаёт ответ.

## Что получится после деплоя

Публичная ссылка вида:

`https://metarealty-feed-sskuban.<ваш-поддомен>.workers.dev/realty.xml`

Её можно указать в кабинете рекламы как **URL фида объектов** (отдельно от фида кампаний).

## Развёртывание (Cloudflare)

1. Установите [Node.js](https://nodejs.org/) LTS.
2. Зарегистрируйтесь на [Cloudflare](https://dash.cloudflare.com/) (бесплатного тарифа достаточно).
3. В терминале:

```bash
cd transform-worker
npm install
npx wrangler login
npx wrangler deploy
```

4. Имя воркера задаётся в `wrangler.toml` (`name = "metarealty-feed-sskuban"`). При конфликте имён измените `name` и снова `wrangler deploy`.

### Переменные и секреты (опционально)

В **Cloudflare Dashboard** → Workers → ваш воркер → **Settings** → **Variables**:

| Тип | Имя | Назначение |
|-----|-----|------------|
| Variable | `FEED_SOURCE_URL` | URL исходного XML Битрикса (по умолчанию уже в `wrangler.toml`) |
| Variable | `DEFAULT_LAT` / `DEFAULT_LON` | Если в фиде нет координат, подставляются эти |
| Secret | `FEED_ACCESS_TOKEN` | Если задано, фид доступен только с `?token=СЕКРЕТ` в URL |

### Ограничения и стоимость

- Большой фид (~5 МБ) на бесплатном Worker обычно проходит, но при таймаутах увеличьте лимит CPU в платных настройках или разместите тот же код на **Render / Fly.io** как Node-сервис.
- Кэш ответа: `Cache-Control: max-age=300` (5 минут) — при необходимости поменяйте в `src/index.ts`.

## Локальная проверка

```bash
npm run dev
```

Откройте в браузере показанный `http://127.0.0.1:8787/realty.xml`.

## Кампании

Фид **кампаний** (`campaign-feed`) по-прежнему отдельный файл/URL — см. `feeds/campaign-feed.xml` в репозитории или свой HTTPS-эндпоинт.
