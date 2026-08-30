## MODIFIED Requirements

### Requirement: TMDB metadata provider
The TMDB provider SHALL search and fetch movies and series in a requested metadata locale, fetch every advertised TV season including Season 00, preserve provider provenance, normalize real TMDB episode payloads and artwork URLs, and expose required attribution through its module declaration and the browser control attribution resource. For each search result, the module SHALL expose a non-empty TMDB `overview` as the optional plain-text description. It SHALL construct the optional complete poster URL only when `poster_path` is a string matching `^/[A-Za-z0-9._/-]+$` and contains no `..` sequence, using exactly `https://image.tmdb.org/t/p/original<poster_path>`. A missing or empty overview, missing or invalid poster path, or failure to validate the constructed URL SHALL make only that preview field absent and SHALL NOT remove an otherwise valid search result. Its authenticated transport SHALL accept only the canonical HTTPS `api.themoviedb.org/3` base and validated TMDB endpoint shapes and SHALL reject every alternative origin, plaintext scheme, credential, query, fragment, or path that could redirect or disclose its bearer token.

#### Scenario: Search TMDB in a locale
- **WHEN** a user searches TMDB with a supported metadata locale
- **THEN** results are returned separately as TMDB identities in that locale and are not merged with other providers

#### Scenario: Map complete TMDB search previews
- **WHEN** a valid TMDB search result has a non-empty overview and `poster_path` `/a/b.poster.jpg`
- **THEN** the TMDB module returns that overview as plain text and returns `https://image.tmdb.org/t/p/original/a/b.poster.jpg` as the complete poster URL

#### Scenario: Keep a result with absent previews
- **WHEN** an otherwise valid TMDB search result has a missing or empty overview and a missing, malformed, traversal-containing, or URL-invalid poster path
- **THEN** the result remains available with the affected preview fields absent

#### Scenario: Display attribution
- **WHEN** an interface requests browser control attribution with TMDB configured
- **THEN** the response includes the official TMDB attribution identity, notice, and allowed link supplied by the module without requiring a built-in About/Credits view

#### Scenario: Fetch a TV hierarchy
- **WHEN** TMDB advertises regular seasons and Season 00 for a series
- **THEN** the provider fetches each season detail and normalizes its real episode hierarchy and available poster and backdrop artwork
