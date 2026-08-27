import { Burger, Button, Drawer, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  isRouteErrorResponse,
  NavLink,
  Outlet,
  type RouteObject,
  useLocation,
  useNavigation,
  useRouteError,
} from "react-router";

import { ControlFailure } from "./api/control-client";
import { useControl } from "./api/control-provider";
import { sessionQueryKey } from "./api/control-provider";
import styles from "./app-shell.module.css";
import { CatalogPage } from "./catalog/catalog-page";
import { MediaDetailPage } from "./catalog/media-detail-page";
import { ManualAddPage } from "./manual/manual-add-page";
import { ManualEditPage } from "./manual/manual-edit-page";
import { MetadataPage } from "./workflows/metadata-page";
import { ReleasePage } from "./workflows/release-page";

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("navigation.label")} className={styles.navigationLinks}>
      <NavLink
        className={styles.navigationLink}
        onClick={onNavigate}
        to="/"
        end
      >
        {t("navigation.catalog")}
      </NavLink>
      <NavLink className={styles.navigationLink} onClick={onNavigate} to="/add">
        {t("navigation.add")}
      </NavLink>
    </nav>
  );
}

function ApplicationShell() {
  const [drawerOpened, { close: closeDrawer, open: openDrawer }] =
    useDisclosure(false);
  const { client, session } = useControl();
  const queryClient = useQueryClient();
  const { i18n, t } = useTranslation();
  const location = useLocation();
  const navigation = useNavigation();
  const mainRef = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  const localeMutation = useMutation({
    mutationFn: (locale: "en" | "ru") =>
      client.updateSession({ ui_locale: locale }),
    onSuccess: async (updatedSession) => {
      queryClient.setQueryData(sessionQueryKey, updatedSession);
      await i18n.changeLanguage(updatedSession.ui_locale);
      await queryClient.invalidateQueries({
        predicate: ({ queryKey }) =>
          queryKey[0] === "control" && queryKey[1] !== "session",
      });
    },
  });

  useEffect(() => {
    if (i18n.resolvedLanguage !== session.ui_locale) {
      void i18n.changeLanguage(session.ui_locale);
    }
    document.documentElement.lang = session.ui_locale;
    document.title = i18n.getFixedT(session.ui_locale)("appName");
  }, [i18n, session.ui_locale]);

  useEffect(() => {
    if (previousPath.current !== location.pathname) {
      mainRef.current?.focus();
      previousPath.current = location.pathname;
    }
  }, [location.pathname]);

  const nextLocale = session.ui_locale === "en" ? "ru" : "en";
  const localeLabel =
    nextLocale === "ru"
      ? t("locale.switchToRussian")
      : t("locale.switchToEnglish");

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <Burger
          aria-label={t("navigation.open")}
          className={styles.mobileMenu}
          onClick={openDrawer}
          opened={drawerOpened}
        />
        <Text className={styles.brand} fw={700} size="lg">
          {t("appName")}
        </Text>
        <Button
          loading={localeMutation.isPending}
          onClick={() => localeMutation.mutate(nextLocale)}
          size="compact-sm"
          variant="subtle"
        >
          {localeLabel}
        </Button>
      </header>
      <Drawer onClose={closeDrawer} opened={drawerOpened} title={t("appName")}>
        <Navigation onNavigate={closeDrawer} />
      </Drawer>
      <div className={styles.body}>
        <aside className={styles.desktopNavigation}>
          <Navigation />
        </aside>
        <main className={styles.main} ref={mainRef} tabIndex={-1}>
          {navigation.state !== "idle" && (
            <Text role="status">{t("routes.loading")}</Text>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <Stack>
      <Title order={1}>{t("routes.notFound")}</Title>
      <Text>{t("routes.notFoundDescription")}</Text>
    </Stack>
  );
}

function RouteErrorPage() {
  const error = useRouteError();
  const { t } = useTranslation();
  let code = "unexpected_response";
  let requestId: string | null = null;
  if (error instanceof ControlFailure) {
    code = error.code;
    requestId = error.requestId;
  } else if (isRouteErrorResponse(error)) {
    code = "unexpected_response";
  }
  const key = `errors.${code}`;
  const message = t(key, { defaultValue: t("errors.unexpected_response") });
  return (
    <Stack role="alert">
      <Title order={1}>{message}</Title>
      {requestId !== null && (
        <Text>{t("errors.requestId", { requestId })}</Text>
      )}
    </Stack>
  );
}

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <ApplicationShell />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <CatalogPage /> },
      { path: "add", element: <MetadataPage /> },
      { path: "add/manual", element: <ManualAddPage /> },
      { path: "items/:itemId", element: <MediaDetailPage /> },
      { path: "items/:itemId/edit", element: <ManualEditPage /> },
      {
        path: "items/:itemId/releases",
        element: <ReleasePage />,
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
