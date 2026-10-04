# 🎨 Artist Onboarding via Scraped Profiles

> Bootstrap artist supply without requiring self-onboarding.
> Extends the **existing restaurant Apify scraping pipeline**.

---

## 🗺️ End-to-End Flow

```mermaid
flowchart TD
    A([🕷️ Apify Scrape\nInstagram & YouTube]) --> B[💾 Store as\nUNCLAIMED Draft]
    B --> C{Contact info\nfound in bio?}

    C -->|Email| D[📧 Send Email]
    C -->|Phone number| E[💬 WhatsApp\nBusiness API]
    C -->|No contact| F[💬 Comment on\nlatest IG post]
    C -->|Website/Linktree| G[🔍 Scrape that page\nfor email] --> D

    D & E & F --> H([🔗 Artist clicks\nClaim Link])

    H --> I{Which platform\nto verify?}

    I -->|Instagram| J[🔐 Instagram OAuth]
    I -->|YouTube| K[🔐 Google OAuth]

    J --> L{user_id\nmatch?}
    K --> M{channelId\nmatch?}

    L -->|✅ Match| N([🎉 Profile CLAIMED\n& goes Live])
    M -->|✅ Match| N
    L -->|❌ No match| O([🚫 Rejected])
    M -->|❌ No match| O
```

---

## 🕷️ Step 1 — Scraping via Apify

> Same pipeline as restaurants — new actors, same infra.

```mermaid
flowchart LR
    subgraph Apify Actors
        A1[apify/instagram-\nprofile-scraper]
        A2[streamers/youtube-\nchannel-scraper]
    end

    subgraph Fields to Store
        F1["📌 id — numeric user ID\n👤 username\n📝 biography\n📧 email from bio\n🔗 externalUrl\n👥 followersCount"]
        F2["📌 channelId\n🔗 customUrl @handle\n📝 description\n📧 email from About\n👥 subscriberCount"]
    end

    A1 --> F1
    A2 --> F2
    F1 & F2 --> DB[(Draft DB\nstatus: UNCLAIMED)]
```

**Key IDs to store — used for OAuth match later:**

| Platform | Field | Example |
|----------|-------|---------|
| Instagram | `id` | `"460563723"` |
| YouTube | `channelId` | `"UC_x5XG1OV2P6uZZ5FSM9Ttw"` |
| YouTube | `customUrl` | `"@artisthandle"` |

---

## 📢 Step 2 — Outreach Priority

```mermaid
flowchart TD
    S([Scraped Profile]) --> P1

    P1{Email in bio?}
    P1 -->|Yes| R1[📧 Send Email\n⭐ Best channel]
    P1 -->|No| P2

    P2{Phone number\nin bio?}
    P2 -->|Yes| R2[💬 WhatsApp Business API\nTemplate message]
    P2 -->|No| P3

    P3{Website /\nLinktree link?}
    P3 -->|Yes| R3[🔍 Scrape page\nfor email] --> R1
    P3 -->|No| R4[💬 Comment on\nlatest IG post\n⚠️ Last resort — max 1 comment]
```

**Sample message:**
```
Hi [Name] 👋

We've created a free artist profile for you on [Marketplace].
Event organizers across India discover artists here every month.

✨ Claim and customize your profile for free:
→ marketplace.com/artists/<your-slug>
```

---

## 🔐 Step 3 — Claim & Verification

### Instagram OAuth

```mermaid
sequenceDiagram
    actor Artist
    participant Marketplace
    participant Instagram

    Artist->>Marketplace: Clicks "Verify with Instagram"
    Marketplace->>Instagram: OAuth redirect (scope: instagram_basic)
    Artist->>Instagram: Approves access
    Instagram->>Marketplace: Returns access token
    Marketplace->>Instagram: GET /me
    Instagram->>Marketplace: { id: "460563723", username: "..." }
    Marketplace->>Marketplace: Match id vs scraped id
    Marketplace->>Artist: ✅ Profile unlocked!
```

### Google OAuth (YouTube)

```mermaid
sequenceDiagram
    actor Artist
    participant Marketplace
    participant Google
    participant YouTube API

    Artist->>Marketplace: Clicks "Verify with Google"
    Marketplace->>Google: OAuth redirect (scope: youtube.readonly)
    Artist->>Google: Approves access
    Google->>Marketplace: Returns access token
    Marketplace->>YouTube API: GET /channels?part=snippet&mine=true
    YouTube API->>Marketplace: { channelId: "UC_x5...", customUrl: "@handle" }
    Marketplace->>Marketplace: Match channelId vs scraped channelId
    Marketplace->>Artist: ✅ Profile unlocked!
```

### Fallback — Bio Token (if OAuth not ready)

```mermaid
flowchart LR
    A[Generate token\nsc-verify-a3f9bc] --> B[Ask artist to\npaste in bio]
    B --> C{Poll profile\nevery 5 min}
    C -->|Token found| D[✅ Verified\nAsk to remove token]
    C -->|Not found\nafter 24h| E[⏰ Expired\nResend outreach]
```

---

## 🔑 Verification Matrix

| Draft Source | Verify Via | API Call | Match Field |
|-------------|------------|----------|-------------|
| Instagram | Instagram OAuth | `GET /me` | `user_id` |
| YouTube | Google OAuth | `GET /channels?mine=true` | `channelId` or `@customUrl` |
| Both scraped | Either (one is enough) | — | Respective ID |

---

## 📋 Profile State Machine

```mermaid
stateDiagram-v2
    [*] --> UNCLAIMED: Apify scrape ingested

    UNCLAIMED --> OUTREACH_SENT: Contact found & messaged
    UNCLAIMED --> OUTREACH_SENT: Comment posted on IG

    OUTREACH_SENT --> CLAIM_INITIATED: Artist clicks claim link
    OUTREACH_SENT --> EXPIRED: No response in 30 days

    CLAIM_INITIATED --> CLAIMED: OAuth ID match ✅
    CLAIM_INITIATED --> REJECTED: OAuth ID mismatch ❌

    CLAIMED --> LIVE: Artist completes profile
    EXPIRED --> UNCLAIMED: Re-scrape & retry

    LIVE --> [*]
```

---

## ⚠️ Important Notes

| # | Note |
|---|------|
| 🔒 | **Privacy** — Keep all drafts private until claimed. Never expose scraped email/phone on the public page. |
| 🔑 | **Dedup key** — Use platform `user_id` / `channelId`, not name or username (both can change). |
| ♻️ | **Re-scrape** — Schedule periodic runs to refresh follower counts & bio on unclaimed drafts. |
| 🍽️ | **Reuse** — Scraping job, dataset schema, and ingestion pipeline = same pattern as restaurants. Extend, don't duplicate. |
| ⚖️ | **Legal** — One OAuth verification is sufficient. Artist doesn't need to verify all platforms. |
