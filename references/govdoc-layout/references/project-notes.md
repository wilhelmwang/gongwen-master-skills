# hehecat/gongwen project notes

## What it is

- React 19 + TypeScript + Vite app for GB/T 9704-style Chinese official-document layout.
- Converts plain text or imported `.docx/.txt` text into a parsed AST, A4 browser preview, and generated `.docx`.
- Uses `docx` for Word generation, `mammoth` for `.docx` text extraction, and `file-saver` for downloads.

## Main source areas

- `src/parser/`: identifies title, addressee, headings, attachments, signature, and date.
- `src/hooks/usePagination.ts`: DOM-measured preview pagination.
- `src/exporter/docxBuilder.ts`: Word document, page, footer, header, attachment, signature/date, and footer-note generation.
- `src/exporter/styleFactory.ts`: fonts, line spacing, character spacing, indent, and heading/body styles.
- `src/types/documentConfig.ts`: GB/T defaults and configurable layout options.
- `src/utils/fileImporter.ts`: `.docx`/`.txt` import.
- `src/utils/sanitize.ts`: punctuation and whitespace cleanup.

## Useful defaults

- A4 page.
- Margins default to top `3.46cm`, bottom `3.26cm`, left `2.8cm`, right `2.6cm`.
- Title defaults to `方正小标宋_GBK`, 22pt.
- Body defaults to `仿宋_GB2312`, 16pt, 29.6pt fixed line spacing.
- Page number default is national-standard mirrored style: odd right, even left.
- Supports configurable header/版头 and footer-note/版记.

## Privacy posture

The bundled source does not contain obvious upload calls (`fetch`, `XMLHttpRequest`, `axios`, `sendBeacon`). It stores draft text, config, custom fonts, and templates in browser `localStorage`.

## Local compatibility patch

Upstream commit `5a852a77e5c65134055abbe3c96d79ae8e871b6b` failed local macOS TypeScript builds because `src/contexts/DocumentConfigContext.tsx` and `src/contexts/documentConfigContext.ts` collide by casing during module resolution.

The vendored copy renames the provider component file to `src/contexts/DocumentConfigProvider.tsx` and updates `src/main.tsx`. Keep this patch when refreshing the vendored app unless upstream has fixed the collision.

## Known risks

- Browser preview pagination can differ from final Word/WPS pagination when fonts are missing or rendered differently.
- Parser is rule-based and can misclassify edge cases.
- `.docx` import uses raw text extraction; existing styles, tables, comments, tracked changes, and complex layout are not preserved.
- Formal documents still need manual Word/WPS inspection before delivery.
- On macOS, Vite/Rollup can fail with native `.node` code-signature errors. The bundled scripts ad-hoc sign Rollup/Rolldown native bindings after dependency installation.
- If local build still fails, `scripts/build_offline.sh` copies `assets/gongwen-release.html` to `assets/gongwen-offline.html` as a usable fallback.

## Validation commands

From `assets/gongwen/`:

```bash
npm ci || npm install
npm run lint
npx vitest run
npm run build
SINGLE_FILE=1 npm run build:single
```
