/**
 * Прокси + преобразование фида Битрикс (Yandex realty 2010-06)
 * → metarealty/2024-12 по требованиям PDF «Яндекс Поиск Недвижимость / Квартиры».
 */
import { XMLBuilder, XMLParser } from "fast-xml-parser";

export interface Env {
  FEED_SOURCE_URL?: string;
  DEFAULT_LAT?: string;
  DEFAULT_LON?: string;
  /** Если задано в Secrets, запросы без ?token=... получают 403 */
  FEED_ACCESS_TOKEN?: string;
}

const NS = "http://webmaster.yandex.ru/schemas/feed/metarealty/2024-12";

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  parseTagValue: false,
  trimValues: true,
  removeNSPrefix: true,
});

const builder = new XMLBuilder({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  format: true,
  suppressEmptyNode: true,
  processEntities: false,
});

function asText(v: unknown): string | undefined {
  if (v == null) return undefined;
  if (typeof v === "string") {
    const t = v.trim();
    return t || undefined;
  }
  if (typeof v === "object" && "#text" in (v as object)) {
    const t = (v as { "#text": unknown })["#text"];
    return typeof t === "string" ? t.trim() || undefined : undefined;
  }
  return undefined;
}

function asArray<T>(v: T | T[] | undefined | null): T[] {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

const RENOVATION_TO_DECORATION: Record<string, string> = {
  "предчистовая отделка": "pre_clean",
  предчистовая: "pre_clean",
  черновая: "rough",
  чистовая: "clean",
  "под ключ": "turnkey",
  "белый короб": "white_box",
  "без отделки": "no_decoration",
};

function mapCurrency(c: string | undefined): string {
  const u = (c || "RUB").toUpperCase();
  if (u === "RUR") return "RUB";
  return u;
}

function collectImages(offer: Record<string, unknown>): string[] {
  const raw = offer.image;
  const items: { url: string; planFirst: number }[] = [];
  const consider = (node: unknown) => {
    if (typeof node === "string") {
      const u = node.trim();
      if (u) items.push({ url: u, planFirst: 0 });
      return;
    }
    if (!node || typeof node !== "object") return;
    const o = node as Record<string, unknown>;
    const url = asText(o["#text"]) ?? asText(o);
    if (!url) return;
    const tag = String(o["@_tag"] ?? o["@tag"] ?? "");
    let rank = 2;
    if (tag === "plan") rank = 0;
    else if (url.includes("/planers/p/")) rank = 1;
    else if (url.includes("/planers/floors/")) rank = 1;
    items.push({ url, planFirst: rank });
  };
  for (const x of asArray(raw)) consider(x);
  items.sort((a, b) => a.planFirst - b.planFirst || a.url.localeCompare(b.url));
  return items.map((i) => i.url);
}

function areaBlock(
  src: unknown,
  tag: "area" | "kitchen-space" | "living-space",
): Record<string, { value: string; unit: string }> | undefined {
  if (!src || typeof src !== "object") return undefined;
  const s = src as Record<string, unknown>;
  const value = asText(s.value);
  const unit = asText(s.unit) ?? "кв. м";
  if (!value) return undefined;
  return { [tag]: { value, unit } };
}

function buildLocation(
  loc: unknown,
  defLat: string,
  defLon: string,
): Record<string, string> | undefined {
  if (!loc || typeof loc !== "object") return undefined;
  const L = loc as Record<string, unknown>;
  const region = asText(L.region);
  const locality = asText(L["locality-name"] ?? L.locality_name);
  const addr = asText(L.address);
  const apartment = asText(L.apartment);
  const lat = asText(L.latitude) ?? defLat;
  const lon = asText(L.longitude) ?? defLon;
  let address = addr;
  if (address && region && !address.includes(region)) {
    address = `${region}, ${address}`;
  }
  if (address && locality && !address.includes(locality)) {
    address = `${locality}, ${address}`;
  }
  if (!address) return undefined;
  const out: Record<string, string> = { address, latitude: lat, longitude: lon };
  if (apartment) out.apartment = apartment;
  return out;
}

function transformOffer(
  offer: Record<string, unknown>,
  defLat: string,
  defLon: string,
): Record<string, unknown> | null {
  const id = asText(offer["@_internal-id"] ?? offer["@internal-id"]);
  if (!id) return null;
  const type = asText(offer.type);
  const category = asText(offer.category);
  if (!type || !category) return null;

  const location = buildLocation(offer.location, defLat, defLon);
  if (!location) return null;

  const dealStatus = asText(offer["deal-status"]);
  if (!dealStatus) return null;

  const priceEl = offer.price as Record<string, unknown> | undefined;
  const pVal = priceEl ? asText(priceEl.value) : undefined;
  const pCur = mapCurrency(priceEl ? (asText(priceEl.currency) as string) : undefined);
  if (!pVal) return null;

  const images = collectImages(offer);
  if (images.length === 0) return null;

  const area = areaBlock(offer.area, "area");
  if (!area) return null;

  const kitchen = areaBlock(offer["kitchen-space"], "kitchen-space");
  const living = areaBlock(offer["living-space"], "living-space");

  const renovation = asText(offer.renovation)?.toLowerCase() ?? "";
  let decoration: string | undefined;
  for (const [k, v] of Object.entries(RENOVATION_TO_DECORATION)) {
    if (renovation.includes(k)) {
      decoration = v;
      break;
    }
  }

  const yb = asText(offer["yandex-building-id"]);
  const yh = asText(offer["yandex-house-id"]);
  if (!yb || !yh) return null;

  const out: Record<string, unknown> = {
    "@_internal-id": id,
    type,
    category,
    location,
    "deal-status": dealStatus,
    price: { value: pVal, currency: pCur },
    ...area,
    ...kitchen,
    ...living,
  };

  out.image = images;

  const desc = asText(offer.description);
  if (desc) out.description = desc.slice(0, 10000);

  if (decoration) out["decoration-type"] = decoration;

  const copyOptional = [
    "rooms",
    "floor",
    "floors-total",
    "building-name",
    "yandex-building-id",
    "yandex-house-id",
    "building-type",
    "lift",
    "built-year",
    "ready-quarter",
    "building-state",
  ] as const;
  for (const k of copyOptional) {
    const v = asText(offer[k]);
    if (v) out[k] = v;
  }

  return out;
}

function checkAccess(request: Request, env: Env): boolean {
  const token = env.FEED_ACCESS_TOKEN;
  if (!token) return true;
  const url = new URL(request.url);
  const q = url.searchParams.get("token");
  return q === token;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!checkAccess(request, env)) {
      return new Response("Forbidden", { status: 403 });
    }

    const url = new URL(request.url);
    if (url.pathname !== "/" && url.pathname !== "/realty.xml") {
      return new Response("Not Found", { status: 404 });
    }

    const source =
      env.FEED_SOURCE_URL ?? "https://bx.sskuban.ru/local/integrat/feed/jcat/9019077";
    const defLat = env.DEFAULT_LAT ?? "44.9656";
    const defLon = env.DEFAULT_LON ?? "37.4492";

    let xmlIn: string;
    try {
      const r = await fetch(source, {
        headers: { "User-Agent": "metarealty-feed-transform/1.0" },
      });
      if (!r.ok) {
        return new Response(`Upstream ${r.status}`, { status: 502 });
      }
      xmlIn = await r.text();
    } catch (e) {
      return new Response(`Upstream error: ${String(e)}`, { status: 502 });
    }

    let data: Record<string, unknown>;
    try {
      data = parser.parse(xmlIn) as Record<string, unknown>;
    } catch (e) {
      return new Response(`XML parse error: ${String(e)}`, { status: 500 });
    }

    const feed = data["realty-feed"] as Record<string, unknown> | undefined;
    if (!feed) {
      return new Response("Invalid feed: missing realty-feed", { status: 500 });
    }

    const gen =
      asText(feed["generation-date"]) ??
      new Date().toISOString().replace("Z", "+00:00");

    const offersRaw = feed.offer;
    const offersIn = asArray(offersRaw) as Record<string, unknown>[];

    const offersOut: Record<string, unknown>[] = [];
    for (const o of offersIn) {
      const t = transformOffer(o, defLat, defLon);
      if (t) offersOut.push(t);
    }

    const doc = {
      "realty-feed": {
        "@_xmlns": NS,
        "generation-date": gen,
        offer: offersOut,
      },
    };

    let body: string;
    try {
      body = builder.build(doc);
    } catch (e) {
      return new Response(`XML build error: ${String(e)}`, { status: 500 });
    }

    const out =
      `<?xml version="1.0" encoding="utf-8"?>\n` +
      body.replace(/^<\?xml[^>]*>\s*/i, "");

    return new Response(out, {
      headers: {
        "Content-Type": "text/xml; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    });
  },
};
