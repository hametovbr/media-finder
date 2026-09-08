import i18next, { type i18n } from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import ru from "./locales/ru.json";

export const uiResources = {
  en: { translation: en },
  ru: { translation: ru },
} as const;

const supportedLocales = ["en", "ru"] as const;

function browserLocale(): "en" | "ru" {
  const languages =
    typeof navigator !== "undefined" && navigator.languages?.length
      ? navigator.languages
      : typeof navigator !== "undefined" && navigator.language
        ? [navigator.language]
        : [];
  for (const language of languages) {
    const primary = language.split("-")[0]?.toLowerCase();
    if (
      supportedLocales.includes(primary as (typeof supportedLocales)[number])
    ) {
      return primary as "en" | "ru";
    }
  }
  return "en";
}

export function createUiI18n(locale?: "en" | "ru"): i18n {
  const instance = i18next.createInstance();
  void instance.use(initReactI18next).init({
    fallbackLng: "en",
    initAsync: false,
    interpolation: { escapeValue: false },
    lng: locale ?? browserLocale(),
    resources: uiResources,
    returnNull: false,
  });
  return instance;
}
