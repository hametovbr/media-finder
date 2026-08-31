import {
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import styles from "./media-detail-page.module.css";

function DetailPoster({
  posterUrl,
  title,
}: {
  posterUrl: string | null;
  title: string;
}) {
  const { t } = useTranslation();
  const [failedPosterUrl, setFailedPosterUrl] = useState<string | null>(null);

  if (posterUrl === null || failedPosterUrl === posterUrl) {
    return (
      <div
        aria-label={t("metadata.posterUnavailable", { title })}
        className={styles.poster}
        data-poster-fallback="true"
        role="img"
      >
        <span aria-hidden="true">MF</span>
      </div>
    );
  }

  return (
    <div className={styles.poster}>
      <img
        alt={t("metadata.posterFor", { title })}
        loading="lazy"
        onError={() => setFailedPosterUrl(posterUrl)}
        referrerPolicy="no-referrer"
        src={posterUrl}
      />
    </div>
  );
}

export function MediaDetailPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const { itemId = "" } = useParams();
  const detailQuery = useQuery({
    queryKey: ["control", "media-item", itemId, session.metadata_locale],
    queryFn: ({ signal }) =>
      client.getMediaItem(itemId, session.metadata_locale, signal),
    enabled: itemId.length > 0,
  });

  if (detailQuery.isPending) {
    return <Loader aria-label={t("detail.loading")} />;
  }
  if (detailQuery.isError) {
    const failure = detailQuery.error;
    const code =
      failure instanceof ControlFailure ? failure.code : "unexpected_response";
    return (
      <Stack role="alert">
        <Text>
          {t(`errors.${code}`, {
            defaultValue: t("errors.unexpected_response"),
          })}
        </Text>
        {failure instanceof ControlFailure && failure.requestId !== null && (
          <Text>{t("errors.requestId", { requestId: failure.requestId })}</Text>
        )}
      </Stack>
    );
  }

  const item = detailQuery.data;
  const metadata = item.metadata;
  const title =
    metadata.titles[session.metadata_locale] ??
    metadata.titles.en ??
    metadata.original_title ??
    item.external_id;
  const originalTitle = metadata.original_title?.trim() || null;
  const genres = metadata.genres.map((genre) => genre.trim()).filter(Boolean);
  const posterUrl =
    metadata.artwork.find((artwork) => artwork.kind.toLowerCase() === "poster")
      ?.url ?? null;

  return (
    <div className={styles.detailLayout}>
      <DetailPoster posterUrl={posterUrl} title={title} />
      <Stack className={styles.content} gap="lg">
        <div>
          <Title className={styles.wrappingText} order={1}>
            {title}
          </Title>
          <Group mt="xs">
            <Badge>{t(`mediaKind.${item.kind}`)}</Badge>
            {metadata.year !== null && metadata.year !== undefined && (
              <Text>{metadata.year}</Text>
            )}
            <Text c="dimmed">{item.provider_key}</Text>
          </Group>
        </div>
        {originalTitle !== null && (
          <div>
            <Text c="dimmed" fw={600} size="sm">
              {t("detail.originalTitle")}
            </Text>
            <Text className={styles.wrappingText}>{originalTitle}</Text>
          </div>
        )}
        {genres.length > 0 && (
          <div>
            <Text c="dimmed" fw={600} size="sm">
              {t("detail.genres")}
            </Text>
            <Group gap="xs" mt={4} wrap="wrap">
              {genres.map((genre, index) => (
                <Badge key={`${index}-${genre}`} variant="light">
                  {genre}
                </Badge>
              ))}
            </Group>
          </div>
        )}
        {metadata.plot === null ||
        metadata.plot === undefined ||
        metadata.plot.length === 0 ? (
          <Text>{t("detail.empty")}</Text>
        ) : (
          <Text className={styles.wrappingText}>{metadata.plot}</Text>
        )}
        <Button
          component={Link}
          to={`/items/${encodeURIComponent(item.id)}/releases`}
        >
          {t("routes.releases")}
        </Button>
        {item.provider_key === "manual" ? (
          <Button
            component={Link}
            to={`/items/${encodeURIComponent(item.id)}/edit`}
            variant="light"
          >
            {t("manual.edit.action")}
          </Button>
        ) : null}
      </Stack>
    </div>
  );
}
