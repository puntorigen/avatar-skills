# reel-discovery reference

Schema, scoring, provider quirks and Apify field mappings for the
`reel-discovery` skill. The SKILL.md is the operational guide; this is the
contract + internals.

## The `Reel` record

Defined in [`scripts/_common.py`](scripts/_common.py). Every searcher emits these
and `discover.py` writes them into `results.json` (each prefixed with `rank`).

| Field | Type | Notes |
|---|---|---|
| `platform` | str | `youtube` \| `tiktok` \| `instagram` \| `facebook` |
| `video_id` | str | Platform-native id (YT videoId, TikTok aweme id, IG shortcode, FB video id) |
| `url` | str | Canonical watch URL |
| `author` | str | Channel/handle/username |
| `title` | str | Title or caption |
| `views` | int? | Null when the platform hides it (often IG) |
| `likes` | int? | |
| `comments` | int? | |
| `shares` | int? | TikTok only (others null) |
| `published_at` | str? | ISO-8601 UTC |
| `duration_s` | float? | Seconds |
| `thumbnail` | str? | Cover/thumbnail URL |
| `media_url` | str? | Direct downloadable URL when known (tikwm play, IG video_url, Apify) |
| `query` | str | The query that produced the hit |
| `match_type` | str | `topic` \| `business` \| `handle` |
| `source` | str | Provider: `youtube-api`, `yt-dlp`, `tikwm`, `ig-web`, `apify-tiktok`, `apify-instagram`, `apify-facebook` |
| `description` | str? | Full description / caption text (YouTube; TikTok/IG keep the caption in `title`) |
| `tags` | list[str]? | Creator-set keywords (YouTube `snippet.tags`; not the public hashtags) |
| `hashtags` | list[str]? | `#tags` parsed from title + description/caption, case-insensitively de-duped (all platforms) |
| `category` | str? | Human-readable category name (YouTube `videoCategories` lookup) |
| `language` | str? | Default audio/text language, BCP-47 (`defaultAudioLanguage` \|\| `defaultLanguage`) |
| `metadata` | dict? | Platform-specific publishing extras (see "Publishing metadata" below) |
| `views_estimated` | bool | True when `views` was estimated from likes |
| `engagement_rate` | float? | `(likes+comments+shares)/effective_views` |
| `velocity` | float | `effective_views / days_since_publish` (views per day) |
| `score` | float | The value used for the active `--sort` (see below) |

`results.json` shape:

```json
{
  "meta": {"query": "...", "match_type": "topic", "platforms": ["youtube","tiktok"],
            "sort": "views", "filters": {...}, "raw_counts": {...},
            "credentials": {"yt_api_key": true, "apify_token": false},
            "generated_at": "...", "notes": ["..."]},
  "count": 30,
  "results": [{"rank": 1, "platform": "tiktok", "...": "..."}]
}
```

## Publishing metadata ("how was this published?")

Beyond reach/engagement, every record can carry **publishing metadata** that
explains *how* a video was packaged — useful when researching how winners are
published rather than just how big they are. It is populated for **YouTube,
TikTok and Instagram** across every path (Data API / tikwm / IG web / yt-dlp /
Apify). Facebook leaves the fields `null` for now (the schema is cross-platform,
so it is safe to extend later).

Top-level fields: `description`, `tags`, `hashtags`, `category`, `language`.
Everything else lives in the free-form `metadata` dict.

`hashtags` is always parsed from the title + description/caption (TikTok and
Instagram store their caption in `title`). `backfill_publishing_meta()` in
`_common.py` is the safety net: it fills `hashtags`, `hashtag_count` and
`description_length` for any record (e.g. Apify items) whose source did not set
them, without overwriting source-provided values.

### YouTube `metadata` keys

From the Data API path (`videos.list` parts `snippet,statistics,contentDetails,status,topicDetails`):

| Key | Source | Meaning |
|---|---|---|
| `category_id` | `snippet.categoryId` | Raw category id (the human name is `category`) |
| `default_language` / `default_audio_language` | `snippet` | Declared text/audio language |
| `live_broadcast_content` | `snippet` | `none` \| `live` \| `upcoming` |
| `definition` | `contentDetails.definition` | `hd` \| `sd` |
| `dimension` / `projection` | `contentDetails` | `2d`/`3d`, `rectangular`/`360` |
| `caption` | `contentDetails.caption == "true"` | Whether captions/subtitles exist |
| `licensed_content` | `contentDetails` | Claimed/licensed content |
| `license` | `status.license` | `youtube` \| `creativeCommon` |
| `privacy_status` / `embeddable` | `status` | Publishing posture |
| `made_for_kids` | `status.madeForKids` | COPPA "made for kids" flag |
| `topic_categories` | `topicDetails` | Wikipedia topic slugs (algorithmic categorization) |
| `channel_id` | `snippet.channelId` | Owning channel |
| `tags_count` / `description_length` | derived | Quick packaging signals |
| `thumbnails` | `snippet.thumbnails` | `{size: url}` for available sizes |
| `subscribers` / `channel_video_count` / `channel_view_count` / `channel_country` / `channel_created_at` | `channels.list` | Channel size & context (best-effort) |

The yt-dlp fallback fills a leaner subset (`subscribers` from
`channel_follower_count`, `categories`, `definition` inferred from `height`,
`width`/`height`/`fps`, `availability`, `live_status`, `age_limit`,
`tags_count`, `description_length`).

### TikTok `metadata` keys

From tikwm (`_video_from_tikwm`); the caption itself is in `title`:

| Key | Source | Meaning |
|---|---|---|
| `music_title` / `music_author` | `music_info` | The **sound** used (key TikTok discovery signal) |
| `music_original` | `music_info.original` | Whether it's an original sound |
| `region` | `region` | Creator/upload region (e.g. `US`, `CL`) |
| `is_ad` | `is_ad` | Branded/ad post flag |
| `saves` / `downloads` | `collect_count` / `download_count` | Bookmarks & downloads |
| `hashtag_count` / `description_length` | derived | Packaging signals |

The yt-dlp fallback fills `music_title`/`music_author` (from `track`/`artist`)
plus the derived counts. The Apify path maps `musicMeta.*`, `region` and
`collectCount` into the same keys.

### Instagram `metadata` keys

From the IG web endpoints (`_node_to_reel` / `_media_v1_to_reel`); caption in `title`:

| Key | Source | Meaning |
|---|---|---|
| `product_type` | `product_type` / `media_type` | `clips` (reel), `image`, `carousel`, ... |
| `is_video` | `is_video` | Whether the post is a video |
| `hashtag_count` / `description_length` | derived | Packaging signals |

The Apify path maps `productType`/`type` into `product_type`.

`results.md` renders a **"Cómo están publicados"** section grouped **per
platform** so platform-specific signals never get mixed: each platform gets an
aggregate block (YouTube: category/language/definition/captions/made-for-kids/
description length/subscriber range/top tags; TikTok: regions/top sounds; IG:
post types) plus top hashtags and a platform-tailored per-video table. The
section is omitted when no record carries publishing metadata.

## Scoring + ranking

`rank()` in `_common.py`:

1. `compute_derived()` fills `engagement_rate` and `velocity` for every record.
2. Filters applied: `min_views` (on effective views), `max_duration` (if known),
   `since_days` (records with an **unknown** date are kept - we can't disprove them).
3. `score` per `--sort`:
   - `views` (default): `effective_views`.
   - `engagement`: `engagement_rate`.
   - `velocity`: `views/day` (best for spotting current breakouts; pair with `--since`).
   - `recent`: `-days_since_publish` (unknown dates sink to the bottom).
4. Sort by score desc; optional `per_platform` cap; truncate to `limit`.

`effective_views = views if views is not None else likes * LIKES_TO_VIEWS_MULT
(default 25) else 0`. Tune the multiplier at the top of `_common.py`. Estimated
views are flagged (`views_estimated`) and rendered with a `*` in `results.md`.

## Provider quirks

### YouTube (`search_youtube.py`)
- Data API path: `search.list` (part=snippet, type=video) -> collect `videoId`s
  -> `videos.list` (part=`snippet,statistics,contentDetails,status,topicDetails`)
  for exact counts + ISO-8601 duration + publishing metadata. Business mode also
  resolves the channel (`search.list type=channel`) and pulls its top videos,
  then merges with a brand keyword search.
- Publishing enrichment (cheap quota): one `videoCategories.list` per region
  (cached, maps `categoryId` -> `category` name) and one `channels.list` per 50
  channels (adds `subscribers` and channel size to each record's `metadata`).
  Both cost 1 unit each and are best-effort — failures are swallowed so the core
  search never breaks. Note: `videos.list` is 1 unit regardless of how many
  `part`s you request, so the richer parts are effectively free.
- `--max-duration` maps to the API `videoDuration` param: `<=240s` -> `short`
  (best Shorts proxy), `<=1200s` -> `medium`, else `any`. YouTube search has no
  true "Shorts-only" filter; short duration is the proxy.
- `--sort` chooses the API `order`: `viewCount` (views/velocity), `date`
  (recent), else `relevance`.
- No-key fallback: `yt-dlp "ytsearchN:<q>" -J` with full extraction (slower;
  N capped ~25) - still yields `view_count`/`like_count`/`duration`.

### TikTok (`search_tiktok.py`) - free via tikwm
- `topic`: `GET /api/feed/search?keywords=...` (real keyword search). If thin,
  falls back to `/api/challenge/posts?challenge_name=<hashtag>` for each derived
  hashtag (`"ai tools"` -> `aitools`, `ai`, `tools`).
- `business/handle`: `/api/user/posts?unique_id=<handle>` + a brand keyword search.
- tikwm video fields used: `video_id`, `title`, `play_count`, `digg_count`
  (likes), `comment_count`, `share_count`, `create_time`, `author.unique_id`,
  `duration`, `cover`, `play` (no-watermark URL -> `media_url`). Publishing
  metadata also reads `music_info` (the sound), `region`, `collect_count`
  (saves) and parses `#hashtags` from the caption (`title`).
- Throttled to ~1 req/sec. If tikwm is down/blocked for a handle, falls back to
  `yt-dlp https://www.tiktok.com/@<handle>` full extraction.

### Instagram (`search_instagram.py`) - hardest
- `business/handle`: `GET /api/v1/users/web_profile_info/?username=<h>` with
  header `x-ig-app-id: 936619743392459`. Parses
  `edge_owner_to_timeline_media.edges[].node` -> `video_view_count`,
  `edge_liked_by.count`, `edge_media_to_comment.count`, `taken_at_timestamp`,
  `shortcode`, `is_video`, `video_url`.
- `topic`: `GET /api/v1/tags/web_info/?tag_name=<tag>` (same header). Handles
  both the newer `data.top/recent.sections[].layout_content.medias[].media`
  shape and the older `graphql.hashtag.edge_hashtag_to_media` shape. Frequently
  gated without a login -> degrades to `[]` with a note.
- Both endpoints rate-limit aggressively. For reliability use `APIFY_TOKEN`, or
  the browser-based `instagram-scraper` skill for a deep profile pull.
- Publishing metadata parses `#hashtags` from the caption (`title`) and records
  `product_type` (`clips` for reels) plus the derived counts.

### Facebook (`search_facebook.py`) - no free path
- **There is no free anonymous discovery for Facebook.** yt-dlp's Facebook
  extractor only resolves an *individual* video/watch/reel URL; a Page or its
  `/videos` tab returns `Unsupported URL`, so it cannot list a page's videos.
  There is no tikwm/web_profile_info equivalent, and `facebook.com/search`
  requires login.
- Discovery is therefore `APIFY_TOKEN`-only (`providers/apify.facebook_search`):
  `topic` -> keyword search; `business` -> the Page's videos/reels. Without a
  token the searcher returns `[]` plus a note (it never guesses).
- Opt-in: `facebook` is a valid `--platforms` value but is **not** in the default
  list, so existing runs are unchanged.
- Downloading still works for any *known* FB URL: `--download-top` calls yt-dlp
  with format `hd/b/bv*+ba/sd`. Facebook's best renditions are the progressive
  `hd`/`sd` formats whose height is reported as "unknown", so a naive `bv*+ba`
  selector would instead grab a smaller height-tagged DASH stream - hence the
  explicit `hd`-first preference (shared with the `facebook-videos` skill).

## Apify (optional, PAID) - `providers/apify.py`

Gated on `APIFY_TOKEN`. Uses the synchronous run endpoint:

```
POST https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token=...
```

Default actors (override via env):
- `APIFY_TIKTOK_ACTOR` (default `clockworks~tiktok-scraper`) - input
  `{searchQueries:[q]}` for topics or `{profiles:[handle]}` for business.
- `APIFY_IG_ACTOR` (default `apify~instagram-scraper`) - input
  `{search, searchType: hashtag|user, directUrls, resultsType: posts}`.
- `APIFY_FACEBOOK_ACTOR` (default `apify~facebook-search-scraper`) - input
  `{query/search/searchQueries:[q]}` for topics or
  `{startUrls:[{url}], directUrls:[pageUrl]}` for business. FB actor schemas vary
  widely; output is mapped defensively across
  `videoId/postId`, `videoViewCount/viewsCount/playCount`,
  `likesCount/reactionsCount`, `commentsCount`, `sharesCount`,
  `time/timestamp/publishedTime`, `pageName/authorName`, `videoUrl`. If results
  look wrong, set `APIFY_FACEBOOK_ACTOR` to an actor you trust and adjust the
  mapping in `facebook_search()`.

Returns plain dicts using `Reel` field names (defensive `.get` with fallbacks,
since actor schemas drift between versions); the searchers wrap them via
`Reel.from_dict`. TikTok mapping reads `playCount/diggCount/commentCount/
shareCount/createTimeISO/webVideoUrl/authorMeta.name/videoMeta.duration`; IG
mapping reads `videoViewCount/likesCount/commentsCount/caption/url/
ownerUsername/timestamp/videoDuration/videoUrl`. Both also emit a `metadata`
dict (TikTok: `musicMeta.*`, `region`, `collectCount`; IG: `productType`);
`hashtags`/`hashtag_count`/`description_length` are filled afterwards by
`backfill_publishing_meta()`.

If a chosen actor's fields don't map cleanly, set `APIFY_TIKTOK_ACTOR` /
`APIFY_IG_ACTOR` to an actor you trust and adjust the mapping in
`providers/apify.py`.

## Download (`--download-top N`)

`discover.py:download_top()` writes `discovery/<slug>/videos/<rank>_<platform>_<id>.mp4`:
- YouTube/TikTok: `yt-dlp` (TikTok falls back to tikwm no-watermark).
- Facebook: `yt-dlp` with format `hd/b/bv*+ba/sd` (prefers the `hd` progressive),
  falling back to a direct `media_url` if Apify supplied one.
- Instagram: direct `media_url` when present, else best-effort `yt-dlp` (often 401).
- Writes `videos/download_manifest.json` with per-item status. These MP4s are the
  input contract for `video-scene-analysis`.

## Output locations

- `discovery/<slug>/results.json`, `discovery/<slug>/results.md`
- `discovery/<slug>/videos/*.mp4` + `download_manifest.json` (only with `--download-top`)
- `<slug>` defaults to a slug of the query; override with `--slug`.
- `discovery/` is gitignored (raw research artifacts + media).
