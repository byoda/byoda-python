# YouTube Import via Scrape.Exchange

## Goal

Replace BYO.Tube's direct YouTube metadata scraping under `byoda/data_import`
with Scrape.Exchange metadata fetched through the public filter API. The pod may
still download media directly from YouTube when video media ingest is enabled.

This is a full metadata cutover: there is no fallback to direct YouTube metadata
scraping.

## Non-Goals

- Do not change the operator-facing `YOUTUBE_CHANNEL` configuration contract.
- Do not rename BYO.Tube semantic fields when an existing semantic equivalent
  already exists.
- Do not introduce fleet-wide rate limiting or shared coordination.
- Do not use Scrape.Exchange to fetch video media.

## Configuration

The importer reads the following environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `YOUTUBE_CHANNEL` | unset | Comma-separated list of channels to import, preserving the existing `:ingest` suffix behavior. |
| `SCRAPE_EXCHANGE_API_URL` | `https://scrape.exchange` | Scrape.Exchange API base URL. |
| `SCRAPE_EXCHANGE_YOUTUBE_SCHEMA_OWNER` | `boinko` | Schema owner used to pin filter results. |
| `SCRAPE_EXCHANGE_YOUTUBE_SCHEMA_VERSION` | `0.0.2` | YouTube schema version used to pin filter results. |

The importer does not set a filter page size. It lets Scrape.Exchange use its
default page size and follows cursors with `after`.

The existing `max_videos` / `max_videos_per_channel` behavior is deprecated for
this path and ignored as an import cap.

## Scrape.Exchange API Contract

BYODA calls:

```text
POST ${SCRAPE_EXCHANGE_API_URL}/api/v1/filter
```

Channel filter by handle:

```json
{
  "schema_username": "boinko",
  "platform": "youtube",
  "entity": "channel",
  "version": "0.0.2",
  "platform_creator_id": "historymatters"
}
```

Channel filter by YouTube channel ID:

```json
{
  "schema_username": "boinko",
  "platform": "youtube",
  "entity": "channel",
  "version": "0.0.2",
  "platform_content_id": "UC22BdTgxefuvUivrjesETjg"
}
```

Video filter by handle:

```json
{
  "schema_username": "boinko",
  "platform": "youtube",
  "entity": "video",
  "version": "0.0.2",
  "platform_creator_id": "historymatters"
}
```

The filter API returns envelope metadata and a `data_url`. BYODA fetches each
`data_url`, validates the payload against the matching Boinko YouTube JSON
Schema, and maps it into BYO.Tube data.

## Channel Input Resolution

`YOUTUBE_CHANNEL` remains the operator-facing channel configuration.

- `@Handle` and `Handle` values are normalized by stripping the leading `@` and
  lowercasing the handle.
- `UC...` values are treated as YouTube channel IDs. The importer first filters
  `entity=channel` by `platform_content_id`, fetches the channel payload, reads
  `channel_handle`, and then uses that handle for video filtering.
- If Scrape.Exchange has no matching channel metadata, the channel is skipped
  for that import cycle.

## Rate Limiting and Iteration

The importer keeps the implementation deliberately sequential:

1. Fetch one filter page.
2. For each edge, fetch its `data_url`.
3. Enforce a per pod worker process limit of at most 10 `data_url` fetches per
   second.
4. Validate, map, skip or persist.
5. Move to the next edge.
6. Continue with the next filter page when `pageInfo.hasNextPage` is true.

There is no concurrent `data_url` fetching and no whole-channel metadata
accumulation in memory.

## Validation and Error Handling

Scrape.Exchange is the only metadata source.

- Missing channel metadata: skip the configured channel for this cycle.
- Missing video metadata: skip the video.
- Invalid fetched payload: skip the record.
- Partial persistence of invalid payloads is not allowed.

Validation errors should be logged with enough context to diagnose:

- `entity`
- `platform_content_id`
- `platform_creator_id`
- `schema_owner`
- `version`
- `data_url`
- validation error details

## BYO.Tube Schema Alignment

`tests/collateral/byotube.json` keeps BYO.Tube's semantic field names when a
semantic equivalent already exists. Boinko-only fields are added using the
Boinko field names.

### Existing Semantic Mappings

Channel mappings:

| Boinko field | BYO.Tube field |
| --- | --- |
| `channel_handle` | `channel` |
| `channel_id` | `publisher_channel_id` |
| `joined_date` | `publisher_joined_date` |
| `rss_url` | `publisher_rss_url` |
| `verified` | `publisher_verified` |
| `subscriber_count` | `publisher_platform_followers` |
| `video_count` | `publisher_platform_videos` |
| `view_count` | `publisher_platform_views` |
| `country` | `country_code` after ISO2 conversion |

Video mappings:

| Boinko field | BYO.Tube field |
| --- | --- |
| `video_id` | `publisher_asset_id` |
| `channel_id` | `publisher_channel_id` |
| `channel_name` or `channel_handle` | `publisher_channel` |
| `channel_thumbnail` | `channel_thumbnail` |
| `view_count` | `publisher_views` |
| `like_count` | `publisher_likes` |
| `dislike_count` | `publisher_dislikes` |
| `comment_count` | `publisher_comment_count` |
| `description` | `contents` |
| `url` | `asset_url` until BYODA replaces it with local media URL after ingest |
| `thumbnails` | `video_thumbnails` |
| `chapters` | `video_chapters` |
| `subtitles` / `automatic_captions` | `video_captions` where compatible |

### Boinko-Only Fields to Add

Channel fields:

- `courses`
- `playlists`
- `posts`
- `merch`
- `channel_links`
- `video_ids`

Video fields:

- `long_title`
- `availability`
- `channel_url`
- `channel_country`
- `channel_is_verified`
- `channel_follower_count`
- `available_country_codes`
- `embed_url`
- `media_type`
- `is_tv_film_video`
- `embedable`
- `aspect_ratio`
- `age_restricted`
- `heatmaps`
- `formats`
- `subtitles`
- `automatic_captions`
- `privacy_status`

The channel stat field mismatch in the current code must be fixed. The code
should emit and update:

- `publisher_platform_followers`
- `publisher_platform_videos`
- `publisher_platform_views`

not `publisher_followers`, `publisher_videos`, `publisher_views`, or
`thirdparty_platform_*`.

## Import Architecture

Add a Scrape.Exchange client, for example:

```text
byoda/data_import/scrape_exchange_youtube_client.py
```

Responsibilities:

- build pinned filter requests
- call `POST /api/v1/filter`
- follow `after` cursors
- fetch `data_url` payloads
- enforce the 10/sec per-process `data_url` rate limit
- expose parsed response envelopes to the importer
- use the repo's `httpx2` package for HTTP calls

Add adapter logic, either in the client module or dedicated modules:

```text
byoda/data_import/scrape_exchange_youtube_channel.py
byoda/data_import/scrape_exchange_youtube_video.py
```

Responsibilities:

- validate payloads against the Boinko YouTube schemas
- map Boinko channel payloads into `YouTubeChannel`
- map Boinko video payloads into `YouTubeVideo`
- convert thumbnail/banner structures into existing `YouTubeThumbnail`
  instances
- convert external links into existing `YouTubeExternalLink` instances
- preserve Boinko-only fields for BYO.Tube persistence

## Preserved BYODA Behavior

Keep:

- local datastore duplicate checks by `publisher_asset_id`
- channel persistence
- video persistence through BYODA data APIs
- thumbnail/banner ingest and cache
- media download from YouTube when `YOUTUBE_CHANNEL` enables ingest
- Bento4 packaging
- moderation claim flow
- `YOUTUBE_IMPORT_INTERVAL` delay between video persist/media ingest attempts

## Deleted Direct-Scraping Metadata Code

Delete direct YouTube metadata scraping and parsing helpers from
`youtube_channel.py` and `youtube_video.py`.

Examples of code to remove or replace:

- HTML / `ytInitialData` extraction
- YouTube page parsing helpers
- nested scrape dictionary search helpers used only for scraping
- channel video page scraping
- direct extraction of video IDs from YouTube pages
- direct video metadata scraping via yt-dlp or YouTube HTML

Keep direct YouTube code that is required for media download and packaging.

## Test Plan

Replace parser-centered tests with Scrape.Exchange-centered tests:

1. Config tests
   - default API URL, schema owner, and schema version
   - env override behavior

2. Client tests
   - channel filter body by handle
   - channel filter body by `UC...` channel ID
   - video filter body by handle
   - cursor pagination without explicit `first`
   - sequential `data_url` fetching rate-limited to 10/sec

3. Adapter tests
   - Boinko channel fixture maps to BYO.Tube semantic fields
   - Boinko video fixture maps to BYO.Tube semantic fields
   - Boinko-only fields are preserved with Boinko names
   - thumbnails, banners, captions, chapters, and external links map correctly
   - invalid payloads are skipped

4. Import loop tests
   - missing channel metadata skips the channel
   - invalid video payload skips the record
   - known `publisher_asset_id` skips persistence
   - valid new video persists
   - media ingest still uses direct YouTube download path when enabled

5. Schema tests
   - `tests/collateral/byotube.json` contains the added Boinko-only fields
   - channel stat names match the code
   - generated data from adapters validates against BYO.Tube schema classes

Obsolete direct-scraping tests should be removed or rewritten. In particular,
tests that assert HTML parsing helpers, `ytInitialData` traversal, YouTube page
video ID extraction, or direct metadata scrape behavior should not survive this
cutover.

## Implementation Order

1. Update `tests/collateral/byotube.json` with schema alignment and Boinko-only
   fields.
2. Fix existing channel stat field names in `YouTubeChannel.as_dict()` and
   `_update_channel_stats()`.
3. Add the Scrape.Exchange client and configuration defaults.
4. Add channel and video adapters with JSON Schema validation.
5. Rewire the import loop to use Scrape.Exchange filter pages and `data_url`
   payloads.
6. Preserve direct YouTube media download and thumbnail ingest paths.
7. Delete direct metadata scraping helpers and obsolete parser tests.
8. Add replacement tests for client, adapters, schema alignment, and import
   loop behavior.
9. Run focused unit tests, then the broader YouTube import test suite.
