-- Standort-Check: initiales Schema
-- Konsolidiert Konzept §2 (Basis) + Ergänzungen v4 §F + v5 §M in einem Stand,
-- plus DB-geführte Kontingent-Zähler (Chat vom 2026-08-15, Nutzung folgt Phase 2).
-- Quelle: docs/KONZEPT.md

create extension if not exists pgcrypto;

create table leads (
  id                  uuid primary key default gen_random_uuid(),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  submission_token    uuid not null unique,

  -- Kontakt (raw bleibt unangetastet, s. CLAUDE.md Regel 4)
  name                text,                          -- Anzeigewert (ggf. normalisiert)
  name_raw            text,                          -- wie eingegeben, nie verändert [v5 §I]
  name_normalized     boolean not null default false, -- [v5 §I]
  email               text not null,
  email_normalized    text not null,
  phone_raw           text,
  phone_e164          text,
  phone_valid         boolean not null default false,

  -- Grundstücksadresse (die einzige Adresse im System, Konzept K1)
  street              text not null,
  postal_code         text,
  city                text not null,

  -- Fachliche Felder [v2/v3]
  is_owner            boolean,
  contact_time_preference text
                      check (contact_time_preference in
                             ('vormittags','nachmittags','flexibel')
                             or contact_time_preference is null),
  message             text,
  heard_about         text,

  -- Attribution: automatisch erfasst
  utm_source          text, utm_medium text, utm_campaign text,
  utm_term            text, utm_content text,
  gclid               text, fbclid text,
  referrer            text, landing_page text,

  -- Kanal-Ableitung beim INSERT [v5 §H]
  channel             text,
  channel_source      text,

  -- Dedup / Versionierung [v2/v3 §4]
  content_hash        text not null,
  duplicate_of        uuid references leads(id),
  superseded_by       uuid references leads(id),

  -- Sales-Workflow
  status              text not null default 'neu'
                      check (status in ('neu','kontaktiert','qualifiziert',
                                        'disqualifiziert','duplikat','ersetzt',
                                        'spam','ausland')),               -- 'ausland' [v4 §A]
  assigned_to         text,
  contacted_at        timestamptz,
  disqualify_reason   text,

  -- Spam (Konzept §J) — nie abgewiesen, nur markiert
  is_spam             boolean not null default false,
  spam_reason         text,

  -- Nebenwirkung Mail
  email_status        text not null default 'offen'
                      check (email_status in ('offen','gesendet','fehlgeschlagen','skipped')),
                      -- 'skipped': Konzept §2-Fließtext nennt den Wert für Spam-Fälle,
                      -- fehlte aber im ursprünglichen CHECK — hier ergänzt.
  email_attempts      int not null default 0,
  email_last_error    text,
  email_sent_at       timestamptz,

  -- Auslandspfad: zweite, separate Mail [v4 §A]
  ausland_hinweis_status text not null default 'nicht_noetig'
                      check (ausland_hinweis_status in
                             ('nicht_noetig','offen','gesendet','fehlgeschlagen')),
  expansion_opt_in    boolean default false,

  -- Nebenwirkung Geocoding
  geocode_status      text not null default 'offen'
                      check (geocode_status in ('offen','ok','mehrdeutig',
                                                'nicht_gefunden','fehlgeschlagen',
                                                'entfaellt')),            -- 'entfaellt' [v5 §G]
  geocode_attempts    int not null default 0,
  lat numeric, lon numeric,
  geo_municipality    text,
  geo_state           text,
  geo_country         text,                          -- [v4 §F]
  geocode_raw         jsonb,
  in_service_area     boolean,

  -- Ampel, gecacht und bei jedem Schreibvorgang neu berechnet [v4 §B/§F]
  traffic_light       text,
  traffic_light_reason text,

  -- Verzögerte Verarbeitung: 1h Korrekturfenster [v5 §G]
  process_after       timestamptz not null default now() + interval '1 hour',

  privacy_accepted_at timestamptz not null
);

create index on leads (created_at desc);
create index on leads (status);
create index on leads (email_normalized);
create index on leads (phone_e164);
create index on leads (content_hash);
create index on leads (process_after) where geocode_status = 'offen';  -- [v5 §M]

create table lead_events (
  id          bigint generated always as identity primary key,
  lead_id     uuid not null references leads(id),
  event_type  text not null,
  payload     jsonb,
  created_at  timestamptz not null default now()
);

-- Kontingent-Schutz für Free-Tier-Dienste (Brevo Mails/Tag, Nominatim
-- Geocoding/Minute). DB-geführt statt Prozessspeicher: jede Serverless-
-- Instanz hätte sonst ihren eigenen Zähler. Nutzung folgt in Phase 2.
--
-- Erwartete counter_key-Werte: 'email_sent_day' (window_start = Tagesanfang
-- UTC), 'geocode_minute' (window_start = Minutenanfang UTC).
create table usage_counters (
  counter_key   text not null,
  window_start  timestamptz not null,
  count         int not null default 0,
  updated_at    timestamptz not null default now(),
  primary key (counter_key, window_start)
);
