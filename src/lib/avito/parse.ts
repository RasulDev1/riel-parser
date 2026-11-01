import * as cheerio from "cheerio";
import type { Listing } from "@/lib/types";

const AVITO_ORIGIN = "https://www.avito.ru";

function toNumber(raw: string | undefined | null): number | null {
  if (!raw) return null;
  const cleaned = raw.replace(/\s| | /g, "").replace(",", ".").replace(/[^\d.]/g, "");
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

/**
 * Достаёт площадь, этаж, этажность и комнатность из заголовка вида
 * "2-к. квартира, 54,3 м², 5/9 эт." или "Квартира-студия, 25 м², 3/17 эт."
 */
export function parseTitle(title: string) {
  const areaMatch = title.match(/(\d+(?:[.,]\d+)?)\s*м²/);
  const floorMatch = title.match(/(\d+)\s*\/\s*(\d+)\s*эт/);
  const roomsMatch = title.match(/(\d+)-к\.?/) ?? title.match(/(студия|свободная планировка)/i);

  return {
    area: areaMatch ? Number(areaMatch[1].replace(",", ".")) : null,
    floor: floorMatch ? Number(floorMatch[1]) : null,
    totalFloors: floorMatch ? Number(floorMatch[2]) : null,
    rooms: roomsMatch ? (/^\d+$/.test(roomsMatch[1]) ? `${roomsMatch[1]}-к` : roomsMatch[1].toLowerCase()) : null,
  };
}

/** Разбирает HTML страницы выдачи Авито в список объявлений. */
export function parseSearchPage(html: string): Listing[] {
  const $ = cheerio.load(html);
  const items: Listing[] = [];

  $('[data-marker="item"]').each((_, el) => {
    const node = $(el);
    const id = node.attr("data-item-id") ?? node.attr("id")?.replace(/^i/, "") ?? "";

    const titleEl = node.find('[data-marker="item-title"]').first();
    const title = (titleEl.attr("title") ?? titleEl.text() ?? node.find('[itemprop="name"]').first().text()).trim();
    if (!title) return;

    const href = titleEl.attr("href") ?? node.find('a[itemprop="url"]').attr("href") ?? "";
    const url = href.startsWith("http") ? href : `${AVITO_ORIGIN}${href}`;

    const price =
      toNumber(node.find('meta[itemprop="price"]').attr("content")) ??
      toNumber(node.find('[data-marker="item-price"]').first().text());

    const addressBlock = node.find('[data-marker="item-address"]').first();
    const address = addressBlock.find("p, span").first().text().trim() || addressBlock.text().trim() || null;
    // Район / метро Авито обычно выводит отдельной строкой под адресом
    const geoParts = addressBlock
      .find("p, div > span")
      .map((__, p) => $(p).text().trim())
      .get()
      .filter((t) => t && t !== address);
    const district = geoParts.length ? geoParts.join(", ") : null;

    const publishedAt = node.find('[data-marker="item-date"]').first().text().trim() || null;

    const { area, floor, totalFloors, rooms } = parseTitle(title);

    items.push({
      id: id || url,
      title,
      url,
      price,
      pricePerM2: price && area ? Math.round(price / area) : null,
      area,
      rooms,
      floor,
      totalFloors,
      address,
      district,
      publishedAt,
    });
  });

  return items;
}

/** Есть ли на странице признаки антибот-заглушки Авито. */
export function looksLikeBlockPage(html: string): boolean {
  return /firewall|Доступ ограничен|проблема с IP|captcha/i.test(html) && !html.includes('data-marker="item"');
}
