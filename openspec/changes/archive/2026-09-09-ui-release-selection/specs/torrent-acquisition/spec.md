## ADDED Requirements

### Requirement: Ephemeral release comparison facts
Search SHALL preserve valid optional size and seeder facts through selection and browser projection without adding them to persisted Acquisition snapshots. The first-party Prowlarr adapter SHALL normalize each optional metric independently: absent, null or invalid values become unknown without discarding an otherwise valid torrent result. Prowlarr size zero SHALL be unknown; zero seeders SHALL remain zero. Metrics SHALL obey the portable release SDK bounds and SHALL NOT imply availability, download progress or a recommended selection.

#### Scenario: Prowlarr supplies comparison facts
- **WHEN** a torrent result contains a positive portable byte size and zero seeders
- **THEN** the browser search result receives that size and zero seeders through the SDK and core pipeline

#### Scenario: Optional upstream metric is unusable
- **WHEN** a torrent has an absent, malformed, negative, fractional, boolean, string, non-finite or over-limit metric, or size zero
- **THEN** only that metric becomes unknown, the other valid metric is preserved and the otherwise valid release remains selectable

#### Scenario: Acquire a result with metrics
- **WHEN** a selected result with known metrics is submitted
- **THEN** the persisted release snapshot remains limited to its existing safe identity fields and no metric or private resolution artifact is persisted
