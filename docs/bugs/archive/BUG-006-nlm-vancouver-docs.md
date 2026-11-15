# BUG-006: Documentation names the Zotero style as "Vancouver" only

- **Status:** fixed
- **Severity:** low
- **Area:** docs
- **Found:** 2026-11-14
- **Audit:** A4-6
- **Related:** README, `docs/how-it-works.md`, `docs/troubleshooting.md`

## Observed

The docs and hints pointed at https://www.zotero.org/styles/vancouver and called the file "Vancouver". The page now serves the NLM/Vancouver style with id `nlm-citation-sequence`, and a Zotero forum thread reported a rename.

## Expected

The documentation names the style that the URL actually serves, while keeping the working download path.

## Evidence

Fetched https://www.zotero.org/styles/vancouver on 2026-11-14. It served `<title>NLM/Vancouver: Citing Medicine 2nd edition (citation-sequence)</title>` and `<id>http://www.zotero.org/styles/nlm-citation-sequence</id>`.

## Fix

README, `docs/how-it-works.md`, `docs/troubleshooting.md` and the style hints now say NLM/Vancouver and name the id. The URL is unchanged because it still serves the file.

## Verification

Documentation review against the fetched CSL on 2026-11-14.
