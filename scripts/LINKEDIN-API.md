# LinkedIn API import (portfolio)

This repo can pull Writing posts via LinkedIn’s **Posts API** when your app has
post-read permissions. Until then, keep using `linkedin-urls.txt` / inbox /
RSS (see `import-linkedin.py`).

## Hard limit (personal profile)

To list **your** posts, LinkedIn requires `r_member_social`.

LinkedIn’s Marketing FAQ currently states that **`r_member_social` is closed**
and they are **not accepting access requests**. Without that scope, any
“get my posts” API call fails even with a valid developer app.

- [Marketing API FAQ — r_member_social](https://learn.microsoft.com/en-us/linkedin/marketing/lms-faq)
- [Posts API — Find posts by author](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api)

**Long-form LinkedIn articles (Pulse)** are also largely outside the Posts API;
article *shares* may appear as posts with article metadata when you do have read access.

## What does work without closed scopes

| Capability | Scope | Status |
|------------|--------|--------|
| Sign in / member id | `openid` `profile` | Open |
| Publish as you | `w_member_social` | Open (write, not read) |
| Read **company page** posts | `r_organization_social` | Needs Community Management approval + page admin |
| Read **personal** posts | `r_member_social` | Closed |

If you run posts mainly as a **company Page** you admin, set
`api.author_mode` to `organization` and `api.organization_urn` after LinkedIn
approves Community Management for your app.

## Setup

1. Create an app at [LinkedIn Developers](https://www.linkedin.com/developers/apps).
2. Add products you can get (Sign In with LinkedIn using OpenID Connect; Share on LinkedIn;
   Community Management if applying for org reads).
3. Auth → OAuth 2.0 redirect URL: `http://127.0.0.1:8765/callback`
4. Copy secrets:

```bash
cp scripts/linkedin.secrets.example.json scripts/linkedin.secrets.json
# edit client_id + client_secret
```

5. Authorize and probe:

```bash
python3 scripts/linkedin-oauth.py
python3 scripts/linkedin-oauth.py --probe
```

6. Enable API source in `scripts/linkedin.config.json`:

```json
"api": {
  "enabled": true,
  "author_mode": "member",
  "organization_urn": "",
  "api_version": "202502",
  "count": 50
}
```

7. Import (API is tried first; URLs/inbox/RSS still run as fallbacks):

```bash
./scripts/import-linkedin.sh
```

Tokens live in `scripts/linkedin-tokens.json` (gitignored). Never commit secrets.

## Probe outcomes

- **Posts API OK** — importer can pull commentary, timestamps, media URNs → images, permalinks.
- **403 / member permissions** — keep using `scripts/linkedin-urls.txt` until LinkedIn grants read access.
