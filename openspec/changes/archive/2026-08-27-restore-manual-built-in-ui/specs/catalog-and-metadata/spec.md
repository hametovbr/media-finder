## MODIFIED Requirements

### Requirement: TMDB metadata provider
The TMDB provider SHALL search and fetch movies and series in a requested metadata locale, fetch every advertised TV season including Season 00, preserve provider provenance, normalize real TMDB episode payloads and artwork URLs, and expose required attribution through its module declaration and the browser control attribution resource. Its authenticated transport SHALL accept only the canonical HTTPS `api.themoviedb.org/3` base and validated TMDB endpoint shapes and SHALL reject every alternative origin, plaintext scheme, credential, query, fragment, or path that could redirect or disclose its bearer token.

#### Scenario: Search TMDB in a locale
- **WHEN** a user searches TMDB with a supported metadata locale
- **THEN** results are returned separately as TMDB identities in that locale and are not merged with other providers

#### Scenario: Display attribution
- **WHEN** an interface requests browser control attribution with TMDB configured
- **THEN** the response includes the official TMDB attribution identity, notice, and allowed link supplied by the module without requiring a built-in About/Credits view

#### Scenario: Fetch a TV hierarchy
- **WHEN** TMDB advertises regular seasons and Season 00 for a series
- **THEN** the provider fetches each season detail and normalizes its real episode hierarchy and available poster and backdrop artwork
