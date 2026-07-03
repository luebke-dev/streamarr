# Suchbackend-Bewertung: Elasticsearch vs. Postgres FTS (Roadmap 3.10)

**Datum:** 2026-07-03 · **Entscheidung:** Elasticsearch beibehalten (jetzt repariert), Postgres-FTS als dokumentierte Zukunftsoption.

## Kontext

Roadmap-Punkt 3.10 fragte, ob Elasticsearch durch Postgres Full-Text-Search (`tsvector`) + `pg_trgm` ersetzt werden sollte, um einen JVM-schweren Single-Point-of-Failure und Betriebs-/Kostenaufwand zu eliminieren. Der Punkt war ausdrücklich als **Evaluation** formuliert („falls Suchanforderungen es zulassen").

Wichtig: In **Tier 1** wurde ES gerade repariert — inkrementeller PG→ES-Sync, korrekte Facetten-Indizierung (Genres/External-IDs), Entfernung des toten Indexer-Codes. Ein sofortiges Herausreißen von ES würde diese Arbeit rückgängig machen. Diese Bewertung entscheidet daher bewusst **gegen** einen Rip-and-Replace jetzt und **für** eine klare Zukunftsoption.

## Was ES hier tatsächlich leistet

- Volltextsuche über `title`/`original_title` mit Tokenisierung/Analyzer.
- Facetten: `nested genres.name`, `external_ids`, Filter nach Typ/Verfügbarkeit/Alter.
- Getrennte Indizes `_movies`/`_shows`/`_books` (Musik/Games/Audiobooks fehlen aktuell — DB-Fallback).
- Relevanz-Scoring über Provider-übergreifende Ergebnisse.

Die tatsächliche Datenmenge eines self-hosted Media-Servers liegt typischerweise bei 10³–10⁵ Items — **weit** unterhalb dessen, wofür ein ES-Cluster nötig wäre.

## Postgres-FTS + pg_trgm: Eignung

| Anforderung | Postgres-Äquivalent | Bewertung |
|---|---|---|
| Volltext Titel | `to_tsvector` + GIN-Index, `websearch_to_tsquery` | ✅ voll ausreichend bei dieser Größe |
| Fuzzy/Typo-Toleranz | `pg_trgm` (`%`-Operator, `similarity()`) | ✅ deckt „ungefähre" Titelsuche ab |
| Genre-/Typ-/Alters-Facetten | bestehende Relationen (`media_genre`) + `WHERE` | ✅ nativ, **konsistent** (kein Sync nötig) |
| Relevanz-Ranking | `ts_rank` / `similarity` + Gewichtung | ⚠️ gröber als ES-BM25, für diese Größe ausreichend |
| Multi-Sprach-Analyzer | `regconfig` pro Sprache | ⚠️ weniger flexibel als ES-Analyzer, aber machbar |
| Musik/Games/Books-Suche | dieselbe Query über alle Typen | ✅ **besser** als heute (ES deckt sie gar nicht ab) |

## Vor-/Nachteile eines Umstiegs

**Pro Postgres-FTS:**
- Eliminiert einen JVM-Dienst (Default nur 512 MB Heap konfiguriert) als SPOF und RAM-/Betriebskosten.
- **Keine Sync-Ebene mehr** — die in Tier 1 reparierte PG↔ES-Drift entfällt komplett (Suche ist immer konsistent mit der DB, transaktional).
- Ein Datenspeicher weniger im Backup-/DR-Pfad (siehe `deployment/backup/`).
- Deckt Musik/Games/Books automatisch mit ab (heute ES-Lücke).

**Contra / Aufwand:**
- Umbau von `services/elasticsearch.py` + `services/search.py` (lokaler Zweig) auf FTS-Queries; neue Migration für `tsvector`-Spalte(n) + GIN/`pg_trgm`-Indizes + Trigger/`generated column` zur Pflege.
- Relevanz-Tuning (Gewichtung Titel vs. Original-Titel, Sprache) muss neu kalibriert werden.
- Der gerade gebaute inkrementelle Sync + Reindex-Worker würde obsolet (Wegwerf-Arbeit).
- Größeres, risikoreiches Refactoring an einem gerade stabilisierten Pfad.

## Entscheidung

**Kurzfristig: ES beibehalten.** Es ist jetzt funktional korrekt (Tier 1), und ein sofortiger Austausch hätte hohes Risiko + Wegwerf-Arbeit. Empfohlene ES-Härtung stattdessen (kleiner Aufwand):
- Musik/Games/Audiobooks-Indizes ergänzen (schließt die einzige echte Funktionslücke).
- ES-Heap/Ressourcen für die reale Datenmenge klein halten (bereits 512 MB).

**Mittelfristig: Postgres-FTS ist die empfohlene Zielarchitektur** für dieses Produkt, weil die Datenmenge klein und die Konsistenz-/Betriebsvorteile groß sind. Sinnvoller Migrationspfad, wenn Kapazität da ist:
1. `tsvector`-Spalte (generated column aus `title`/`original_title`) + GIN-Index + `pg_trgm`-Extension + Trigram-Index auf `title` per Alembic-Migration.
2. `LocalSearchService` um eine FTS-Implementierung erweitern (parallel zu ES, hinter einem Setting `SEARCH_BACKEND=es|postgres`).
3. Feature-Flag-gesteuert umschalten, ES-Ergebnisse gegen FTS vergleichen (Relevanz-Kalibrierung).
4. Nach Bestätigung: ES-Dienst, `elasticsearch.py`, Sync-Worker und ES aus allen Deployment-Modellen entfernen.

Dieser Stufenplan macht den Wechsel risikoarm und reversibel — im Gegensatz zu einem Big-Bang jetzt. Bis dahin bleibt ES die (nun konsistente) Suchebene.

## Fazit

3.10 ist als **bewusste Entscheidung** umgesetzt: ES bleibt (repariert), Postgres-FTS ist als konkreter, gestufter Migrationspfad dokumentiert und als mittelfristige Zielarchitektur empfohlen. Das war die einzige Roadmap-Position, die explizit als Evaluation formuliert war und im direkten Konflikt zur Tier-1-Reparatur stand.
