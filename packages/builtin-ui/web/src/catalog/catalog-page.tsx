import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import styles from "./catalog-page.module.css";

type CatalogItem = components["schemas"]["CatalogItemView"];

function Poster({ item }: { item: CatalogItem }) {
  const [failed, setFailed] = useState(false);
  if (item.poster_url === null || item.poster_url === undefined || failed) {
    return (
      <div className={styles.poster} data-testid="poster-placeholder">
        <span className={styles.posterMark} aria-hidden="true">
          MF
        </span>
      </div>
    );
  }
  return (
    <div className={styles.poster}>
      <img alt="" onError={() => setFailed(true)} src={item.poster_url} />
    </div>
  );
}

function CatalogCard({ item }: { item: CatalogItem }) {
  const { t } = useTranslation();
  const status = item.latest_acquisition_status;
  return (
    <Card
      aria-label={item.title}
      className={styles.card}
      component="article"
      padding={0}
      withBorder
    >
      <Link
        className={styles.cardLink}
        to={`/items/${encodeURIComponent(item.id)}`}
      >
        <Poster item={item} />
        <Stack gap="xs" p="sm">
          <Title order={2} size="h4">
            {item.title}
          </Title>
          <Group gap="xs">
            {item.year !== null && item.year !== undefined && (
              <Text size="sm">{item.year}</Text>
            )}
            <Text size="sm">{t(`mediaKind.${item.kind}`)}</Text>
            <Text c="dimmed" size="sm">
              {item.provider_key}
            </Text>
          </Group>
          {status !== null && status !== undefined && (
            <Badge
              color={
                status === "failed"
                  ? "red"
                  : status === "pending"
                    ? "yellow"
                    : "green"
              }
            >
              {status === "pending"
                ? t("catalog.pendingReconciliation")
                : t(`acquisition.${status}`)}
            </Badge>
          )}
        </Stack>
      </Link>
    </Card>
  );
}

export function CatalogPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const collectionId = searchParams.get("collection") ?? undefined;
  const uncategorized = searchParams.get("uncategorized") === "true";
  const collectionsQuery = useQuery({
    queryKey: ["control", "collections"],
    queryFn: ({ signal }) => client.listCollections(signal),
  });
  const catalogQuery = useInfiniteQuery({
    queryKey: [
      "control",
      "catalog",
      session.metadata_locale,
      collectionId,
      uncategorized,
    ],
    queryFn: ({ pageParam, signal }) =>
      client.listCatalog(
        {
          collectionId,
          cursor: pageParam,
          locale: session.metadata_locale,
          uncategorized,
        },
        signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });

  const selectFilter = (nextCollection?: string, nextUncategorized = false) => {
    const next = new URLSearchParams();
    if (nextCollection !== undefined) next.set("collection", nextCollection);
    if (nextUncategorized) next.set("uncategorized", "true");
    setSearchParams(next);
  };
  const items = catalogQuery.data?.pages.flatMap((page) => page.items) ?? [];

  if (collectionsQuery.isPending || catalogQuery.isPending) {
    return <Loader aria-label={t("catalog.loading")} />;
  }
  const failure = collectionsQuery.error ?? catalogQuery.error;
  if (failure !== null) {
    const code =
      failure instanceof ControlFailure ? failure.code : "unexpected_response";
    return (
      <Text role="alert">
        {t(`errors.${code}`, { defaultValue: t("errors.unexpected_response") })}
      </Text>
    );
  }

  return (
    <Stack gap="lg">
      <Title order={1}>{t("routes.catalog")}</Title>
      <Group
        aria-label={t("catalog.filters")}
        className={styles.filters}
        role="group"
      >
        <Button
          onClick={() => selectFilter()}
          variant={!collectionId && !uncategorized ? "filled" : "light"}
        >
          {t("catalog.all")}
        </Button>
        {(collectionsQuery.data?.items ?? []).map((collection) => (
          <Button
            key={collection.id}
            onClick={() => selectFilter(collection.id)}
            variant={collectionId === collection.id ? "filled" : "light"}
          >
            {collection.name}
          </Button>
        ))}
        <Button
          onClick={() => selectFilter(undefined, true)}
          variant={uncategorized ? "filled" : "light"}
        >
          {t("catalog.uncategorized")}
        </Button>
      </Group>
      {items.length === 0 ? (
        <Text>{t("catalog.empty")}</Text>
      ) : (
        <div className={styles.grid}>
          {items.map((item) => (
            <CatalogCard item={item} key={item.id} />
          ))}
        </div>
      )}
      {catalogQuery.hasNextPage && (
        <Button
          loading={catalogQuery.isFetchingNextPage}
          onClick={() => void catalogQuery.fetchNextPage()}
        >
          {t("catalog.loadMore")}
        </Button>
      )}
    </Stack>
  );
}
