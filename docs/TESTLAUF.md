# Testlauf: Randfälle

Programmatischer Testlauf gegen die echte Datenbank über `scripts/testlauf.py` (POST /submit + direkte DB-Prüfung, kein Mock, kein pytest-Ersatz - die reinen Funktionen bleiben in `tests/core/`). Erstellt am 16.08.2026. Testdaten wurden nach dem Lauf gelöscht (exakt getrackte IDs, kein Muster-Löschen).

**Ergebnis: 40/40 Fälle wie erwartet.** Keine Abweichungen.

Wo Erwartung und tatsächliches Verhalten auseinanderfallen, wurde NICHTS repariert - das ist zur Entscheidung vorgelegt, s. "Abweichungen" am Ende.

## Dedup

### ✅ F1 technische Dopplung (Token-Replay)

**Erwartet:** Beide Requests 303; genau 1 Lead-Zeile für den Token; Event- und email_attempts-Zahl nach dem zweiten Request unverändert (kein zweiter Insert, kein zweiter Mailversuch).

**Tatsächlich:** Request 1: 303, Request 2: 303; Zeilen für Token: 1; Events nach 1.: 2, nach 2.: 2; email_attempts nach 2.: 0

### ✅ F2 Duplikat (identischer Inhalt, neuer Token)

**Erwartet:** 2 eigenständige Zeilen; Original bleibt status='neu'; Duplikat hat status='duplikat' und duplicate_of=Original-ID; Original bekommt Event 'erneut_angefragt'; beide durchlaufen den Mail-Versuch, anders als F1 (Konzept §4: F2 -> Mail ja) - geprüft über 'mail_gesendet' ODER 'mail_fehlgeschlagen', da ein gemeinsames Tageslimit (usage_counters) bei intensivem Testen am selben Tag einen erfolgreichen Versand in einen regulären Fehlschlag verwandeln kann, ohne dass das ein Bug ist.

**Tatsächlich:** lead1.status='neu', lead2.status='duplikat', lead2.duplicate_of==2646d4d4-41ae-431f-ad03-70a0f1db0a94 (erwartet 2646d4d4-41ae-431f-ad03-70a0f1db0a94); erneut_angefragt auf Original: True; beide mit Mail-Versuch-Event: True (lead1: ['erstellt', 'mail_fehlgeschlagen', 'erneut_angefragt'], lead2: ['erstellt', 'mail_fehlgeschlagen'])

### ✅ F4 Kontakt bekannt (Person matcht, Adresse nicht)

**Erwartet:** 2 unabhängige aktive Leads (kein duplicate_of/superseded_by auf beiden Seiten); neuer Lead bekommt Event 'kontakt_bekannt' mit bekannter_lead_id == Original-ID; Original bleibt unangetastet.

**Tatsächlich:** lead1.status='neu' superseded_by=None; lead2.status='neu' duplicate_of=None; kontakt_bekannt-Events auf lead2: 1, payload={'bekannter_lead_id': '36d76c1d-18c1-42c7-80c0-56e55b6a1609'}

### ✅ F3 Kette Schritt 1->2 (Feld-Merge + R17-Vererbung)

**Erwartet:** T2.phone_raw='0170 2222222' (Konflikt, neu gewinnt), T2.message='Erste Nachricht' (Lücke, von T1 übernommen), T2.postal_code='20095'; T1.status='ersetzt', T1.superseded_by=T2.id; T2 erbt status='kontaktiert' und assigned_to='testlauf-anna' von T1 (R17).

**Tatsächlich:** T2.phone_raw='0170 2222222' message='Erste Nachricht' postal_code='20095' status='kontaktiert' assigned_to='testlauf-anna'; T1.status='ersetzt' superseded_by=7c74ad56-ae1a-4623-8585-4e08637d743f

**Hinweis:** T1 vor Korrektur: status='kontaktiert' assigned_to='testlauf-anna'

### ✅ F3 Kette Schritt 2->3 (Merge-Kette über 2 Sprünge)

**Erwartet:** T3.phone_raw='0170 2222222' (Lücke, von T2 geerbt - nicht von T1), T3.postal_code='20095' (Lücke, von T2 geerbt), T3.message='Dritte Nachricht' (Konflikt gegen T2s geerbten Wert, neu gewinnt); T2.status='ersetzt', T2.superseded_by=T3.id (Kandidaten-suche findet den AKTUELLEN Vorgänger T2, nicht den ursprünglichen T1).

**Tatsächlich:** T3.phone_raw='0170 2222222' postal_code='20095' message='Dritte Nachricht'; T2.status='ersetzt' superseded_by=02d55663-28ba-4cc3-b14b-4cf1746d8fa7

## Spam

### ✅ Honeypot gefüllt

**Erwartet:** is_spam=true, spam_reason='honeypot_gefuellt', status='spam' (Konzept §J + Fix aus der letzten Session), keine Mail (email_status='uebersprungen').

**Tatsächlich:** HTTP 303; is_spam=True, spam_reason='honeypot_gefuellt', status='spam', email_status='uebersprungen'

### ✅ Zu schnell abgesendet

**Erwartet:** is_spam=true, spam_reason='zu_schnell_abgesendet', status='spam' (Konzept §J + Fix aus der letzten Session), keine Mail (email_status='uebersprungen').

**Tatsächlich:** HTTP 303; is_spam=True, spam_reason='zu_schnell_abgesendet', status='spam', email_status='uebersprungen'

### ✅ Zwei oder mehr Links in der Anmerkung

**Erwartet:** is_spam=true, spam_reason='zu_viele_links_in_anmerkung', status='spam' (Konzept §J + Fix aus der letzten Session), keine Mail (email_status='uebersprungen').

**Tatsächlich:** HTTP 303; is_spam=True, spam_reason='zu_viele_links_in_anmerkung', status='spam', email_status='uebersprungen'

### ✅ Fremdes Schriftsystem in der Anmerkung

**Erwartet:** is_spam=true, spam_reason='fremdes_schriftsystem_in_anmerkung', status='spam' (Konzept §J + Fix aus der letzten Session), keine Mail (email_status='uebersprungen').

**Tatsächlich:** HTTP 303; is_spam=True, spam_reason='fremdes_schriftsystem_in_anmerkung', status='spam', email_status='uebersprungen'

## Pflichtfelder

### ✅ Straße fehlt (einzeln)

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['street'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['street']; Lead in DB angelegt: False

### ✅ Ort fehlt (einzeln)

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['city'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['city']; Lead in DB angelegt: False

### ✅ E-Mail fehlt (einzeln)

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['email'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['email']; Lead in DB angelegt: False

### ✅ Datenschutz nicht akzeptiert (einzeln)

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['privacy_accepted'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['privacy_accepted']; Lead in DB angelegt: False

### ✅ E-Mail syntaktisch ungültig

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['email_invalid'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['email_invalid']; Lead in DB angelegt: False

### ✅ Straße + Ort + E-Mail + Datenschutz fehlen (kombiniert)

**Erwartet:** HTTP 422, Formular re-rendert MIT Fehlermeldungen für ['city', 'email', 'privacy_accepted', 'street'], kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, sondern ablehnen).

**Tatsächlich:** HTTP 422; gefundene Fehlermeldungen: ['city', 'email', 'privacy_accepted', 'street']; Lead in DB angelegt: False

## Auswahlfelder

### ✅ contact_time_preference='nachts' (nicht in Werteliste)

**Erwartet:** contact_time_preference wird gegen die feste Werteliste geprüft (app/core/validation.py) -> HTTP 422, Fehlermeldung 'Ungültige Auswahl.', kein Lead gespeichert.

**Tatsächlich:** HTTP 422; Fehlermeldung vorhanden: True; Lead angelegt: False

### ✅ heard_about='TikTok-Anzeige' (nicht in Optionsliste)

**Erwartet:** validate_submission() prüft heard_about NICHT gegen HEARD_ABOUT_OPTIONS (anders als contact_time_preference) -> ich erwarte HTTP 303, Lead wird mit heard_about='TikTok-Anzeige' (roh) gespeichert, derive_channel() kennt den Wert nicht und fällt auf channel='sonstiges' zurück. Das ist eine echte Lücke (Validierungs-Inkonsistenz), kein Absturz - Fund für Marco.

**Tatsächlich:** HTTP 303; heard_about='TikTok-Anzeige', channel='sonstiges', channel_source='selbstauskunft'

**Hinweis:** FUND: heard_about wird serverseitig gar nicht validiert (s. app/core/validation.py) - im Gegensatz zu contact_time_preference. Nicht selbst repariert.

### ✅ is_owner='vielleicht' (weder ja noch nein)

**Erwartet:** _parse_is_owner() kennt nur 'ja'/'nein', alles andere wird zu None (keine Validierung, kein Fehler) -> HTTP 303, is_owner wird NULL gespeichert statt eines Fehlers.

**Tatsächlich:** HTTP 303; is_owner=None

## Telefonformate

### ✅ +49 40 / 123 456

**Erwartet:** normalize_phone('+49 40 / 123 456') == ('+4940123456', True) - Formular soll dasselbe in der DB speichern.

**Tatsächlich:** HTTP 303; phone_e164='+4940123456', phone_valid=True

### ✅ 0170 5551234

**Erwartet:** normalize_phone('0170 5551234') == ('+491705551234', True) - Formular soll dasselbe in der DB speichern.

**Tatsächlich:** HTTP 303; phone_e164='+491705551234', phone_valid=True

### ✅ 040 55512345

**Erwartet:** normalize_phone('040 55512345') == ('+494055512345', True) - Formular soll dasselbe in der DB speichern.

**Tatsächlich:** HTTP 303; phone_e164='+494055512345', phone_valid=True

### ✅ 004940123456

**Erwartet:** normalize_phone('004940123456') == ('+4940123456', True) - Formular soll dasselbe in der DB speichern.

**Tatsächlich:** HTTP 303; phone_e164='+4940123456', phone_valid=True

### ✅ 0451 9988776

**Erwartet:** normalize_phone('0451 9988776') == ('+494519988776', True) - Formular soll dasselbe in der DB speichern.

**Tatsächlich:** HTTP 303; phone_e164='+494519988776', phone_valid=True

## Namen

### ✅ TOM AHRENS

**Erwartet:** normalize_name('TOM AHRENS') == ('Tom Ahrens', True) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name='Tom Ahrens', name_normalized=True, name_raw='TOM AHRENS'

### ✅ müller-lüdenscheidt

**Erwartet:** normalize_name('müller-lüdenscheidt') == ('Müller-Lüdenscheidt', True) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name='Müller-Lüdenscheidt', name_normalized=True, name_raw='müller-lüdenscheidt'

### ✅ van der berg

**Erwartet:** normalize_name('van der berg') == ('van der berg', False) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name='van der berg', name_normalized=False, name_raw='van der berg'

### ✅ McDonald

**Erwartet:** normalize_name('McDonald') == ('McDonald', False) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name='McDonald', name_normalized=False, name_raw='McDonald'

### ✅ O'Brien

**Erwartet:** normalize_name("O'Brien") == ("O'Brien", False) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name="O'Brien", name_normalized=False, name_raw="O'Brien"

### ✅ di Marco

**Erwartet:** normalize_name('di Marco') == ('di Marco', False) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten.

**Tatsächlich:** HTTP 303; name='di Marco', name_normalized=False, name_raw='di Marco'

## Lange Eingaben

### ✅ alle Textfelder gleichzeitig sehr lang (2000-10000 Zeichen)

**Erwartet:** Postgres text-Spalten sind längenunbegrenzt -> ich erwarte HTTP 303, alle langen Werte werden VOLLSTÄNDIG und unverändert gespeichert (kein Truncate, kein Absturz); die Telefon-Ziffernfolge ist zu lang für normalize_phone() -> phone_valid=false statt Fehler.

**Tatsächlich:** HTTP 303; street-Länge gespeichert=2018 (erwartet 2018); city-Länge=2000 (erwartet 2000); name_raw-Länge=5000 (erwartet 5000); message-Länge=10019 (erwartet 10019); phone_valid=False; exakte Übereinstimmung aller Felder: True

## Sonderzeichen

### ✅ Emoji + Umlaute + HTML-Sonderzeichen + Tab in Anmerkung

**Erwartet:** UTF-8 (inkl. 4-Byte-Emoji) und HTML-Sonderzeichen werden byteidentisch gespeichert und zurückgelesen; kein Absturz; NICHT als Spam erkannt (kyrillisch/CJK-Regex greift hier nicht, <2 Links).

**Tatsächlich:** HTTP 303; message identisch zurückgelesen: True; is_spam=False

## Kanal-Ableitung

### ✅ Stufe 1a: utm_source exakt ('google')

**Erwartet:** derive_channel(...) == ('google_ads', 'utm')

**Tatsächlich:** HTTP 303; channel='google_ads', channel_source='utm'

### ✅ Stufe 1b: utm_source Substring-Fallback ('google-partner-blog')

**Erwartet:** derive_channel(...) == ('google_ads', 'utm_unsicher')

**Tatsächlich:** HTTP 303; channel='google_ads', channel_source='utm_unsicher'

### ✅ Stufe 1c: utm_source unbekannt ('newsletter-mai')

**Erwartet:** derive_channel(...) == ('sonstiges', 'utm')

**Tatsächlich:** HTTP 303; channel='sonstiges', channel_source='utm'

### ✅ Stufe 2: gclid vorhanden, kein utm_source

**Erwartet:** derive_channel(...) == ('google_ads', 'gclid')

**Tatsächlich:** HTTP 303; channel='google_ads', channel_source='gclid'

### ✅ Stufe 3: fbclid vorhanden, kein utm_source/gclid

**Erwartet:** derive_channel(...) == ('meta_ads', 'fbclid')

**Tatsächlich:** HTTP 303; channel='meta_ads', channel_source='fbclid'

### ✅ Stufe 4a: referrer Google, nichts davor

**Erwartet:** derive_channel(...) == ('google_organisch', 'referrer')

**Tatsächlich:** HTTP 303; channel='google_organisch', channel_source='referrer'

### ✅ Stufe 4b: referrer Bing, nichts davor

**Erwartet:** derive_channel(...) == ('andere_suche', 'referrer')

**Tatsächlich:** HTTP 303; channel='andere_suche', channel_source='referrer'

### ✅ Stufe 5: heard_about, nichts davor

**Erwartet:** derive_channel(...) == ('empfehlung', 'selbstauskunft')

**Tatsächlich:** HTTP 303; channel='empfehlung', channel_source='selbstauskunft'

### ✅ Stufe 6: nichts von alledem -> direkt

**Erwartet:** derive_channel(...) == ('direkt', 'keine')

**Tatsächlich:** HTTP 303; channel='direkt', channel_source='keine'

## Sonstige Funde (Verhalten wie erwartet, aber bemerkenswert)

- **Auswahlfelder / heard_about='TikTok-Anzeige' (nicht in Optionsliste)** — FUND: heard_about wird serverseitig gar nicht validiert (s. app/core/validation.py) - im Gegensatz zu contact_time_preference. Nicht selbst repariert.
