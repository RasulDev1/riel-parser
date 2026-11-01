"use client";

import { CITIES, DEALS, PROPERTY_TYPES } from "@/lib/cities";

export type FormState = Record<string, string | boolean>;

export const DEFAULT_FORM: FormState = {
  city: "moskva",
  propertyType: "kvartiry",
  deal: "prodam",
  district: "",
  priceMin: "",
  priceMax: "",
  areaMin: "",
  areaMax: "",
  floorMin: "",
  floorMax: "",
  totalFloorsMin: "",
  totalFloorsMax: "",
  notFirstFloor: false,
  notLastFloor: false,
  pages: "2",
};

const input =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20";
const label = "mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500";

function Range({
  title,
  name,
  form,
  set,
  unit,
}: {
  title: string;
  name: string;
  form: FormState;
  set: (k: string, v: string | boolean) => void;
  unit?: string;
}) {
  return (
    <div>
      <span className={label}>
        {title}
        {unit ? `, ${unit}` : ""}
      </span>
      <div className="flex gap-2">
        <input
          className={input}
          inputMode="numeric"
          placeholder="от"
          value={form[`${name}Min`] as string}
          onChange={(e) => set(`${name}Min`, e.target.value.replace(/[^\d.]/g, ""))}
        />
        <input
          className={input}
          inputMode="numeric"
          placeholder="до"
          value={form[`${name}Max`] as string}
          onChange={(e) => set(`${name}Max`, e.target.value.replace(/[^\d.]/g, ""))}
        />
      </div>
    </div>
  );
}

export function SearchForm({
  form,
  setForm,
  onSubmit,
  loading,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  const set = (k: string, v: string | boolean) => setForm({ ...form, [k]: v });

  return (
    <form
      className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:grid-cols-2 lg:grid-cols-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div>
        <span className={label}>Город</span>
        <select className={input} value={form.city as string} onChange={(e) => set("city", e.target.value)}>
          {CITIES.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <span className={label}>Категория</span>
        <select
          className={input}
          value={form.propertyType as string}
          onChange={(e) => set("propertyType", e.target.value)}
        >
          {PROPERTY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <span className={label}>Тип сделки</span>
        <select className={input} value={form.deal as string} onChange={(e) => set("deal", e.target.value)}>
          {DEALS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <span className={label}>Район / метро / улица</span>
        <input
          className={input}
          placeholder="например, Хамовники"
          value={form.district as string}
          onChange={(e) => set("district", e.target.value)}
        />
      </div>

      <Range title="Цена" name="price" unit="₽" form={form} set={set} />
      <Range title="Площадь" name="area" unit="м²" form={form} set={set} />
      <Range title="Этаж" name="floor" form={form} set={set} />
      <Range title="Этажей в доме" name="totalFloors" form={form} set={set} />

      <div className="flex flex-wrap items-center gap-4 sm:col-span-2">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="size-4 accent-emerald-600"
            checked={form.notFirstFloor as boolean}
            onChange={(e) => set("notFirstFloor", e.target.checked)}
          />
          Не первый этаж
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="size-4 accent-emerald-600"
            checked={form.notLastFloor as boolean}
            onChange={(e) => set("notLastFloor", e.target.checked)}
          />
          Не последний этаж
        </label>
      </div>

      <div className="flex items-end gap-3 sm:col-span-2">
        <div className="w-32">
          <span className={label}>Страниц</span>
          <select className={input} value={form.pages as string} onChange={(e) => set("pages", e.target.value)}>
            {[1, 2, 3, 5, 10].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={loading}
          className="flex-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-wait disabled:opacity-60"
        >
          {loading ? "Собираю объявления…" : "Найти"}
        </button>
      </div>
    </form>
  );
}
