# LinkedIn import inbox

Drop JSON files here (any `*.json` except already processed). Each file is a list of items:

```json
[
  {
    "title": "Optional title",
    "url": "https://www.linkedin.com/posts/...",
    "date": "2026-07-01",
    "content": "Post or article body text…",
    "kind": "post"
  }
]
```

After a successful import, files are moved to `processed/`.

Prefer configuring `feed_url` in `scripts/linkedin.config.json` (e.g. from [RSS.app](https://rss.app/)) so new posts arrive without manual drops.

Or paste post/article permalinks into `scripts/linkedin-urls.txt` (profile URLs are not enough).

See `demo-seed.example.json` for the inbox JSON shape (ignored by the importer). Cover images are downloaded into `assets/writing/`.
