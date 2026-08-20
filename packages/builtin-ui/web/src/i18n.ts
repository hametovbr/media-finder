import i18next, { type i18n } from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import ru from "./locales/ru.json";

export const uiResources = {
  en: { translation: en },
  ru: { translation: ru },
} as const;

export function createUiI18n(locale: "en" | "ru" = "en"): i18n {
  const instance = i18next.createInstance();
  void instance.use(initReactI18next).init({
    fallbackLng: "en",
    initAsync: false,
    interpolation: { escapeValue: false },
    lng: locale,
    resources: uiResources,
    returnNull: false,
  });
  return instance;
}
