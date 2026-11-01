/**
 * Офлайн-проверка парсера и фильтров на сохранённой HTML-странице.
 * Запуск: npm run test:parser [путь-к-html]
 * Чтобы проверить на реальной вёрстке, сохраните страницу выдачи Авито из браузера (Ctrl+S)
 * и передайте путь к файлу.
 */
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { parseSearchPage } from "../src/lib/avito/parse";
import { applyFilters } from "../src/lib/filter";

const file = process.argv[2] ?? new URL("./fixtures/search.html", import.meta.url).pathname;
const listings = parseSearchPage(readFileSync(file, "utf8"));
console.table(listings.map(({ id, price, area, floor, totalFloors, address, district }) => ({ id, price, area, floor, totalFloors, address, district })));

if (!process.argv[2]) {
  assert.equal(listings.length, 3);
  assert.deepEqual([listings[0].area, listings[0].floor, listings[0].totalFloors, listings[0].price], [54.3, 5, 9, 14500000]);
  assert.equal(listings[2].price, 23000000);
  assert.equal(listings[0].district, "Хамовники");
  const base = { city: "moskva", propertyType: "kvartiry", deal: "prodam" } as const;
  assert.deepEqual(applyFilters(listings, { ...base, district: "хамовники" }).map((l) => l.id), ["1001", "1003"]);
  assert.deepEqual(applyFilters(listings, { ...base, areaMin: 30, notLastFloor: true }).map((l) => l.id), ["1001"]);
  assert.deepEqual(applyFilters(listings, { ...base, priceMax: 10_000_000 }).map((l) => l.id), ["1002"]);
  assert.deepEqual(applyFilters(listings, { ...base, notFirstFloor: true, totalFloorsMax: 12 }).map((l) => l.id), ["1001", "1003"]);
  console.log("✓ Все проверки парсера и фильтров прошли");
}
