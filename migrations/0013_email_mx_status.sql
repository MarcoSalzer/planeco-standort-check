-- Marco, 2026-08-19 (Konzept §D/§K, zunächst als Scope-Cut zurückgestellt,
-- jetzt doch gebaut): serverseitige MX-Prüfung der E-Mail-Domain
-- (email-validator, check_deliverability=True). Nur zwei Werte, weil eine
-- bestätigt nicht zustellbare Domain den Submit ablehnt (422) und nie
-- gespeichert wird - 'nicht_pruefbar' hält fest, dass die Prüfung selbst
-- nicht möglich war (DNS-Dienst nicht erreichbar/Timeout), nicht dass die
-- Domain schlecht wäre. Ein ausgefallener DNS-Dienst darf keine Leads
-- kosten (Marco) - deshalb Default 'nicht_pruefbar' statt eines
-- optimistischen 'geprueft'.
alter table leads add column email_mx_status text not null default 'nicht_pruefbar'
  check (email_mx_status in ('geprueft', 'nicht_pruefbar'));
