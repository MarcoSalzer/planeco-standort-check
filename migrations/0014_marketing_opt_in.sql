-- Marco, 2026-08-19: expansion_opt_in umbenannt. Der ursprüngliche Text
-- ("Bitte informieren Sie mich über neue Regionen") setzte voraus, dass der
-- Interessent schon weiß, dass seine Adresse außerhalb des Einzugsgebiets
-- liegt - das weiß beim Ausfüllen so gut wie niemand. Das Häkchen ist jetzt
-- ein allgemeines Marketing-Opt-in ("neue Angebote und Entwicklungen"); nur
-- die Auslandsmail (Konzept §A) reflektiert weiterhin gezielt den
-- Regionsbezug, wenn das Häkchen gesetzt war - dort ist der Kontext klar.
-- Reiner Rename, keine Datenänderung: bestehende Werte bleiben erhalten.
alter table leads rename column expansion_opt_in to marketing_opt_in;
