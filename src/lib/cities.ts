/** Популярные города и их слаги в URL Авито. Список можно расширять. */
export const CITIES: { slug: string; name: string }[] = [
  { slug: "moskva", name: "Москва" },
  { slug: "moskovskaya_oblast", name: "Московская область" },
  { slug: "sankt-peterburg", name: "Санкт-Петербург" },
  { slug: "novosibirsk", name: "Новосибирск" },
  { slug: "ekaterinburg", name: "Екатеринбург" },
  { slug: "kazan", name: "Казань" },
  { slug: "nizhniy_novgorod", name: "Нижний Новгород" },
  { slug: "chelyabinsk", name: "Челябинск" },
  { slug: "samara", name: "Самара" },
  { slug: "ufa", name: "Уфа" },
  { slug: "rostov-na-donu", name: "Ростов-на-Дону" },
  { slug: "krasnodar", name: "Краснодар" },
  { slug: "omsk", name: "Омск" },
  { slug: "voronezh", name: "Воронеж" },
  { slug: "perm", name: "Пермь" },
  { slug: "volgograd", name: "Волгоград" },
  { slug: "sochi", name: "Сочи" },
  { slug: "mahachkala", name: "Махачкала" },
  { slug: "grozny", name: "Грозный" },
  { slug: "kaliningrad", name: "Калининград" },
];

export const PROPERTY_TYPES = [
  { value: "kvartiry", label: "Квартиры" },
  { value: "komnaty", label: "Комнаты" },
  { value: "doma_dachi_kottedzhi", label: "Дома, дачи, коттеджи" },
  { value: "kommercheskaya_nedvizhimost", label: "Коммерческая" },
] as const;

export const DEALS = [
  { value: "prodam", label: "Продажа" },
  { value: "sdam", label: "Аренда" },
] as const;
