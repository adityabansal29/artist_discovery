# Artist Onboarding & Matching/Recommendation — Visual Reference

---

## Part 1: Artist Onboarding

### 1.1 Three Onboarding Channels

```mermaid
flowchart TB
    subgraph channels["Three Supply Channels"]
        direction TB

        A["<b>Channel A: Restaurant-Nominated</b><br/>Merchant nominates artist from dashboard<br/><i>Highest quality — pre-validated supply</i>"]
        B["<b>Channel B: Artist Self-Serve</b><br/>Artist finds signup via bio-link,<br/>word of mouth, or social<br/><i>Standard inbound funnel</i>"]
        C["<b>Channel C: Ops-Seeded</b><br/>BD team creates skeleton from<br/>public data (Instagram, venue listings)<br/><i>Phase 0 bootstrap only</i>"]
    end

    A -->|"Creates Tier 0<br/>+ WhatsApp invite<br/>to artist"| T0
    B -->|"Artist starts<br/>signup directly"| T0
    C -->|"Creates unclaimed<br/>Tier 0 + claim invite"| T0

    T0["<b>Tier 0: Skeleton</b><br/>Name, phone, city, 1 genre tag,<br/>1 social link<br/><br/>❌ NOT BOOKABLE<br/>Visible as 'pending verification'"]

    T0 -->|"Artist completes<br/>KYC + rate card"| T1

    T1["<b>Tier 1: Verified</b><br/>Tier 0 + eKYC + bank penny-drop<br/>+ auto-pulled portfolio (2+ items)<br/>+ basic rate card<br/><br/>✅ BOOKABLE<br/>'Verified' badge in directory"]

    T1 -->|"Artist enriches<br/>profile over time"| T2

    T2["<b>Tier 2: Complete</b><br/>Full rate card + structured rider<br/>+ Google Calendar sync + Spotify<br/>+ detailed bio + multiple portfolio items<br/><br/>✅ BOOKABLE + HIGHER RANKING<br/>'Complete profile' visibility boost"]

    style A fill:#e8f5e9,stroke:#2e7d32
    style B fill:#e3f2fd,stroke:#1565c0
    style C fill:#fff3e0,stroke:#ef6c00
    style T0 fill:#ffebee,stroke:#c62828
    style T1 fill:#e8f5e9,stroke:#2e7d32
    style T2 fill:#e8f5e9,stroke:#1b5e20
```

### 1.2 Channel A Deep Dive: Restaurant-Nominated Flow

```mermaid
sequenceDiagram
    autonumber
    participant MX as Merchant
    participant DASH as Dashboard
    participant MKT as Marketplace Service
    participant AI as AI Gateway
    participant WA as WhatsApp (WABA)
    participant ART as Artist
    participant KYC as KYC Service
    participant PAY as Payment/Escrow

    MX->>DASH: Taps "Nominate an Artist"
    DASH-->>MX: Simple form: name, phone, genre, relationship

    MX->>DASH: Fills: "Priya Sharma, +91-XXXXX, Acoustic, regular act"
    DASH->>MKT: Create nominated artist
    MKT->>MKT: Create Tier 0 skeleton profile
    Note over MKT: Auto-tagged with:<br/>- Nominating restaurant's city<br/>- Nominating restaurant's venue type<br/>- Genre from merchant's input

    MKT->>WA: Send claim invite
    WA->>ART: "Hi Priya! [Restaurant X] nominated you<br/>on District. Claim your profile in 2 min<br/>to start getting bookings →"
    Note over ART: This converts much better than<br/>cold invite — existing relationship<br/>+ social proof from known venue

    ART->>DASH: Taps link → claim profile page
    DASH-->>ART: Pre-filled: name, city, genre (from nomination)

    ART->>DASH: Confirms basics, pastes Instagram link
    DASH->>AI: Portfolio Ingestion Worker
    AI->>AI: Fetch top 3-5 performance reels from Instagram
    AI-->>DASH: Thumbnails + embed URLs
    DASH-->>ART: "We found these videos — keep or swap?"
    ART->>DASH: Confirms portfolio

    DASH->>AI: Content Generation Agent
    AI-->>DASH: Auto-drafted bio from Instagram captions
    DASH-->>ART: "Here's a bio we drafted — edit or keep"
    ART->>DASH: Confirms bio

    DASH-->>ART: Rate card form (minimal)
    Note over DASH: Shows: "What do you charge<br/>for a typical 2-hour set?"<br/>+ AI suggested range if data exists
    ART->>DASH: Enters ₹15,000

    Note over ART,KYC: ═══ KYC (can defer to "before first payout") ═══

    ART->>KYC: Aadhaar OTP verification
    KYC-->>MKT: Aadhaar verified ✓
    ART->>KYC: PAN validation
    KYC-->>MKT: PAN verified ✓
    ART->>PAY: Bank account details
    PAY->>PAY: Penny-drop verification
    PAY-->>MKT: Bank account verified ✓

    MKT->>MKT: Profile → Tier 1 (BOOKABLE)
    MKT->>ART: "You're live! Restaurants can now book you."
    MKT->>MX: "Priya claimed her profile ✓ — you can now book her directly"
```

### 1.3 Channel B: Artist Self-Serve Flow

```mermaid
sequenceDiagram
    autonumber
    participant ART as Artist
    participant WEB as Signup Page
    participant MKT as Marketplace Service
    participant AI as AI Gateway
    participant KYC as KYC Service
    participant PAY as Payment/Escrow

    ART->>WEB: Lands on signup (via bio-link, referral, social)
    WEB-->>ART: Phone OTP verification
    ART->>WEB: Verifies phone (30 sec)

    WEB-->>ART: "Set up your profile"
    Note over WEB: Name, city (auto-detected if possible),<br/>pick 1-3 genre tags (visual chip picker),<br/>paste Instagram/YouTube link

    ART->>WEB: Fills basics (60 sec)

    WEB->>AI: Portfolio Ingestion Worker
    AI->>AI: Fetch videos from Instagram/YouTube
    AI-->>WEB: Portfolio items ready
    WEB-->>ART: "We pulled these — confirm or swap" (30 sec)

    WEB->>AI: Tag Suggestion Agent
    AI-->>WEB: "Based on your content, we suggest: Sufi, Bollywood"
    WEB-->>ART: Suggested L2 tags (accept/edit)

    WEB->>AI: Content Generation Agent
    AI-->>WEB: Auto-drafted bio
    WEB-->>ART: "Edit or keep this bio"

    WEB-->>ART: Minimal rate card
    Note over WEB: "What do you charge for a<br/>typical 2-hour set?"
    ART->>WEB: Enters price (30 sec)

    Note over ART: ═══ Tier 0 complete → KYC for Tier 1 ═══

    ART->>KYC: Aadhaar OTP + PAN
    KYC-->>MKT: Verified ✓
    ART->>PAY: Bank account
    PAY-->>MKT: Penny-drop verified ✓

    MKT->>MKT: Profile → Tier 1 (BOOKABLE)
    MKT->>ART: "You're live!"
```

### 1.4 AI Agents in Onboarding

```mermaid
flowchart LR
    subgraph onboarding["Artist Onboarding"]
        SOCIAL["Artist pastes<br/>Instagram/YouTube/<br/>Spotify link"]
        BASICS["Artist fills<br/>name, city,<br/>1 genre tag"]
        RATE["Artist enters<br/>one price"]
    end

    subgraph agents["AI Agents (via AI Gateway)"]
        PIW["<b>Portfolio Ingestion<br/>Worker</b><br/>Fetches + normalizes<br/>videos/media from<br/>social links"]
        CGA["<b>Content Generation<br/>Agent</b><br/>Drafts bio from<br/>Instagram captions<br/>+ video titles"]
        TSA["<b>Tag Suggestion<br/>Agent</b><br/>Suggests L2 tags<br/>from portfolio<br/>content analysis"]
        RCA["<b>Rate Card<br/>Suggestion Agent</b><br/>Suggests pricing<br/>from market data<br/><i>(Phase 2+ only)</i>"]
    end

    subgraph outputs["Profile Outputs"]
        PORT["Portfolio<br/>(2-5 embedded<br/>media items)"]
        BIO["Bio draft<br/>(editable)"]
        TAGS["L2 tag<br/>suggestions<br/>(editable)"]
        PRICE["Suggested<br/>price range<br/>(optional hint)"]
    end

    SOCIAL --> PIW --> PORT
    SOCIAL --> CGA --> BIO
    SOCIAL --> TSA --> TAGS
    BASICS --> TSA
    RATE --> RCA --> PRICE

    style PIW fill:#e3f2fd,stroke:#1565c0
    style CGA fill:#e3f2fd,stroke:#1565c0
    style TSA fill:#e3f2fd,stroke:#1565c0
    style RCA fill:#fff3e0,stroke:#ef6c00
```

---

## Part 2: Matching & Recommendations

### 2.1 Two Directions of Matching

```mermaid
flowchart TB
    subgraph demand["<b>Demand Side: Recommending Artists to Merchants</b>"]
        direction TB
        D1["Merchant browses<br/>artist directory"]
        D2["Merchant posts<br/>a gig"]
        D3["Merchant completes<br/>a booking"]
        D4["Merchant views<br/>specific artist"]
    end

    subgraph supply["<b>Supply Side: Recommending Gigs to Artists</b>"]
        direction TB
        S1["New gig posted<br/>matching artist"]
        S2["Artist browses<br/>open gigs"]
        S3["Artist inactive<br/>for 7+ days"]
    end

    subgraph engine["<b>Recommendation Engine</b>"]
        direction TB
        FS["Feature Store<br/>(Redis/DynamoDB)"]
        OS["OpenSearch<br/>(scored query)"]
        MA["Matching Agent<br/>(AI Gateway)"]
    end

    D1 --> OS
    D2 --> MA
    D3 --> OS
    D4 --> OS
    S1 --> MA
    S2 --> OS
    S3 --> MA

    FS --> OS
    FS --> MA

    style demand fill:#e3f2fd,stroke:#1565c0
    style supply fill:#e8f5e9,stroke:#2e7d32
    style engine fill:#f3e5f5,stroke:#7b1fa2
```

### 2.2 Artist-to-Merchant Matching: Ranking Signals

```mermaid
flowchart TB
    subgraph signals["Ranking Signals (by weight)"]
        direction TB

        H1["<b>HIGH WEIGHT</b>"]
        H1A["Tag overlap<br/>(artist genre tags ∩<br/>merchant venue type tags)<br/><b>boost: 3.0</b>"]
        H1B["Price alignment<br/>(rate card within merchant's<br/>historical P25–P75 range)<br/><b>boost: 2.0</b>"]

        M1["<b>MEDIUM WEIGHT</b>"]
        M1A["Same venue type<br/>experience<br/>(artist performed at<br/>similar venues before)<br/><b>boost: 1.5</b>"]
        M1B["Day-of-week<br/>alignment<br/><b>boost: 1.0</b>"]

        L1["<b>LOW WEIGHT</b>"]
        L1A["Artist rating<br/><b>boost: 0.5</b>"]
        L1B["Profile completeness<br/>(Tier 2 > Tier 1)<br/><b>boost: 0.5</b>"]

        N1["<b>NEGATIVE SIGNALS</b>"]
        N1A["Viewed 3+ times,<br/>never booked<br/><b>boost: -2.0</b>"]
        N1B["Flagged by this<br/>merchant in past<br/><b>HARD EXCLUDE</b>"]
    end

    H1 --- H1A
    H1 --- H1B
    M1 --- M1A
    M1 --- M1B
    L1 --- L1A
    L1 --- L1B
    N1 --- N1A
    N1 --- N1B

    style H1 fill:#c8e6c9,stroke:#2e7d32
    style M1 fill:#fff9c4,stroke:#f9a825
    style L1 fill:#e3f2fd,stroke:#1565c0
    style N1 fill:#ffcdd2,stroke:#c62828
    style N1B fill:#ff8a80,stroke:#c62828
```

### 2.3 Gig-to-Artist Matching (Matching Agent)

```mermaid
sequenceDiagram
    autonumber
    participant MX as Merchant
    participant MKT as Marketplace Service
    participant TAG as Tag Service
    participant CAL as Calendar Service
    participant AI as AI Gateway<br/>(Matching Agent)
    participant OS as OpenSearch
    participant ART as Matched Artists

    MX->>MKT: Posts gig (date, genre, budget, venue)

    par Parallel lookups
        MKT->>TAG: Fetch artists matching genre tags + city
        TAG-->>MKT: 45 candidates (tag match)

        MKT->>CAL: Check availability on gig date
        CAL-->>MKT: 28 available (calendar filter)
    end

    MKT->>OS: Query: artist_id IN [28 available]<br/>+ budget alignment filter
    OS-->>MKT: 22 candidates with base scores

    MKT->>AI: Rank 22 candidates for this gig
    Note over AI: Matching Agent considers:<br/><br/>1. Rate card vs gig budget fit<br/>   (within range = high score,<br/>    above range = low score)<br/><br/>2. Past ratings at similar<br/>   venue types<br/><br/>3. Completed booking count<br/>   (reliability signal)<br/><br/>4. Historical acceptance rate<br/>   (no point notifying artists<br/>    who decline 90% of gigs)<br/><br/>5. Response time<br/>   (fast responders ranked<br/>    higher for urgent gigs)

    AI-->>MKT: Top 15 ranked artists

    par Notify top matches
        MKT->>ART: Push notification: "New gig matching your profile"
        MKT->>ART: WhatsApp: "Acoustic gig at [Venue],<br/>27 Dec, ₹12K–18K — interested?"
    end

    Note over ART: Each artist who applies creates a<br/>booking_request(initiated_by=artist,<br/>for_review_by=merchant) — existing flow
```

### 2.4 Homepage Assembly Flow

```mermaid
flowchart TB
    MX["Merchant opens<br/>artist directory"]

    MX --> P["<b>Parallel lookups</b><br/>(all fire simultaneously)"]

    P --> R1["<b>Redis</b><br/>Previously booked<br/>artist IDs<br/>(for pinned section)"]
    P --> R2["<b>DynamoDB</b><br/>Merchant affinity<br/>profile<br/>(genre, price, day<br/>patterns)"]
    P --> R3["<b>Postgres</b><br/>Blocked/flagged<br/>artist IDs<br/>(hard exclude list)"]

    R1 --> ASM["<b>Response Assembler</b>"]
    R2 --> OSQ["<b>OpenSearch Query</b><br/><br/>Filters:<br/>• city = merchant city<br/>• NOT IN blocked list<br/>• profile_tier ≥ 1<br/><br/>Boosts (from affinity):<br/>• genre match: +3.0<br/>• price fit: +2.0<br/>• venue type match: +1.5<br/>• day alignment: +1.0<br/>• rating: +0.5<br/>• completeness: +0.5<br/>• viewed-not-booked: -2.0"]
    R3 --> OSQ

    OSQ --> ASM

    ASM --> SEC1["<b>Section 1: Your Artists</b><br/>(from Redis — pinned top,<br/>sorted by recency,<br/>bypasses OpenSearch)<br/><br/><i>Only shows after ≥1<br/>completed booking</i>"]

    ASM --> SEC2["<b>Section 2: Recommended</b><br/>(from OpenSearch —<br/>personalized ranking,<br/>deduplicated against Sec 1)<br/><br/><i>Falls back to default sort<br/>if no affinity data yet</i>"]

    ASM --> SEC3["<b>Section 3: New on District</b><br/>(recently onboarded artists,<br/>same city, sorted by<br/>created_at DESC)<br/><br/><i>Helps new supply<br/>get initial visibility</i>"]

    style R1 fill:#ffcdd2,stroke:#c62828
    style R2 fill:#fff9c4,stroke:#f9a825
    style R3 fill:#e8eaf6,stroke:#283593
    style OSQ fill:#f3e5f5,stroke:#7b1fa2
    style SEC1 fill:#c8e6c9,stroke:#2e7d32
    style SEC2 fill:#e3f2fd,stroke:#1565c0
    style SEC3 fill:#fff3e0,stroke:#ef6c00
```
