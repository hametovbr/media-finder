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
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";

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

  return (
    <Stack gap="lg">
      <div>
        <Title order={1}>{title}</Title>
        <Group mt="xs">
          <Badge>{t(`mediaKind.${item.kind}`)}</Badge>
          {metadata.year !== null && metadata.year !== undefined && (
            <Text>{metadata.year}</Text>
          )}
          <Text c="dimmed">{item.provider_key}</Text>
        </Group>
      </div>
      {metadata.plot === null ||
      metadata.plot === undefined ||
      metadata.plot.length === 0 ? (
        <Text>{t("detail.empty")}</Text>
      ) : (
        <Text>{metadata.plot}</Text>
      )}
      <Button
        component={Link}
        to={`/items/${encodeURIComponent(item.id)}/releases`}
      >
        {t("routes.releases")}
      </Button>
    </Stack>
  );
}
