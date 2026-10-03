# Validation record

Date: 2026-10-03 UTC. Upstream: Presenton 0.9.11-beta at
`e158a014cc1e29da0a27fe539db08dcbcea5c69d`.
Reviewed exporter SHA256:
`f2e25ff4dd27b69d8d4f0a98dea6a51ff5e9d36133792230f47e99c7648034ae`.

## Passed in the declared experimental subset

- 108 Python tests on a clean installed package: 35 baseline exporter tests, 16 image/layout tests, 3 Native Editable template tests, 15 local-asset tests, 13 isolated native-export route tests, 16 temporary-download tests and 10 SSE tests
- Upstream schema validation, authentication and owner scoping, unsupported input paths, warnings and valid response bytes
- Local image reads restricted to approved raster roots and exact built-in Standard assets; no network fetches; symlink, hardlink, non-regular file, traversal, cross-owner and size/pixel-limit regressions
- 109 tests in the complete frontend Node suite after integration, including diagnostics, layout planning and UI language tests
- TypeScript no-emit check; focused ESLint had zero errors and one existing logo `<img>` warning
- Native text, one native table, three native charts and three embedded XLSX workbooks per five-page sample; zero raster image assets
- Long Chinese title and changed table/column/line/doughnut data preserved
- Reopen exported PPTX, change an existing table text run and chart data through python-pptx, save and reopen; original text styling preserved in the changed cell
- Initial, revised and native-API-edit variants rendered with LibreOffice, 15 pages reviewed. The unchanged roundtrip pages 1/4/5 match revised-page pixels. After the second-stage changes, all three files were regenerated and all 15 rendered pages matched the reviewed first-stage pixels exactly
- Chart labels beginning with `=` and URL strings stay literal text in the embedded workbook; no worksheet formulas or external relationships
- Explicit rejection of unsupported image backgrounds, SVG assets, clipping/manual layout variants, excessive input and overlong Excel labels; malformed supported-type inputs return path-specific validation errors. Supported raster-image opacity, cropping and transforms have separate regressions
- Existing PPTX/PDF/IPC export handlers preserved; native action adds an explicit save barrier, including in-flight saves and save failure handling
- Independently reviewed changes and reproduced issue fixes
- Source overlay dry-run and application on a clean pinned upstream checkout succeeded; all 108 packaged backend tests and 109 Node tests rerun. Existing first-stage upgrade, no-write preview, and repeat/no-op execution were also exercised
- Standalone example script reproduced the same native structures without the full application, model, account or network calls

The visual review initially found unwanted theme shadows and crowded line-chart
labels. Theme effects were removed. The synthetic line-chart input now explicitly
omits data labels while retaining axes, legend and every data value. These changes
are recorded rather than hidden as an untested original success.

## Bundled-template compatibility probes

These are raw layout prototypes, not real-model generated decks. The first-stage
strict exporter accepted Standard 2/11, Executive 1/32 and none of the other four
tested template families. Those failures motivated the bounded image/layout extension.

### Second stage with original Standard raster assets

The controlled loader read the actual bundled PNGs, without substitutions,
database/config access or provider requests. Standard accepted 10/11 prototypes;
one contains an SVG and was rejected. Four accepted layouts carry appearance
warnings (for example, unsupported shadows). Acceptance is a structure check,
not a pixel-perfect visual certificate. The original paths, errors and warning
counts are preserved in [the actual-assets report](evidence/standard-original-assets.json).
No upstream image bytes are redistributed by this add-on.

### Second stage with deliberately synthetic image placeholders

Every image reference in this separate matrix, including an SVG-named reference,
was supplied an explicitly synthetic PNG in memory. This isolates layout support.
It does not validate SVG conversion, actual-asset resolution or original pictures.
Do not report these results as real-image compatibility.

| Template | Prototype layouts accepted | Total checked |
| --- | ---: | ---: |
| Standard | 11 | 11 |
| General | 7 | 12 |
| Civic | 5 | 29 |
| Editorial | 0 | 24 |
| Executive | 5 | 32 |
| Swift | 5 | 9 |

[Full synthetic-assets matrix with failures and warnings](evidence/template-matrix-synthetic-assets.json).
Unsupported objects must not be silently deleted or substituted in real exports.

### Own Native Editable template

Five controlled layouts (cover, table, columns, lines, doughnut) pass the upstream
layout schema and the independent exporter with no warnings: five pages, one
native table, three native charts, three workbooks and no raster assets. The
standalone preview was rendered and each of the five pages visually reviewed.
The same template works with the first-stage deployed exporter. Real-model content
may still exceed a layout's capacity or make unexpected edits; review remains necessary.

## Runtime and browser status

A no-credential two-process runtime returned the root page and auth status with HTTP
200; status was `configured=false, authenticated=false`. Telemetry reported false.
Unauthenticated presentation access returned 428. The packaged private-UI launcher was also exercised in a single isolated process with the same HTTP results; its venv interpreter path remains un-resolved so the correct dependencies load. Authentication was never disabled
and no account or model credentials were created by the test runner.

## Actual private UI and real-model test

A separate authenticated private host reached the real setup and presentation UI.
The user manually created the administrator and entered/saved provider credentials;
the test runner did not read or log them. The model was `deepseek-v4-flash`, selected
from the provider's actual model list. Image generation and web search were disabled.
The Native Editable template appeared and produced five Chinese slides using only
fictional source data. Provider token usage and actual charges were not measured.

The actual product chat changed a selected cover title, one table value 150→168,
and the selected column chart's Q4 value 32→41. A whole-canvas JSON comparison for
the chart edit found only changes in that selected chart: the final series value,
a matching compatibility `data` array and a redundant `color` field. All other
five-page fields were unchanged. A normal page refresh reproduced the same full
JSON, confirming persistence. The title/table edits have before/after screenshots;
they do not have the same full structural baseline, so no stronger claim is made.

The first chart-chat attempt ended in a network error and left the full canvas
identical. One bounded retry succeeded. Safe diagnostic extraction found one
frontend `ECONNRESET` and no listed provider-timeout class, but does not prove the
underlying cause. The added SSE heartbeat prevents an observed idle-stream risk;
it is not presented as proof of the incident's cause. No automatic model retry or
repeated mutation is introduced.

### Actual downloaded PowerPoint

The file was obtained through the real UI's session-authenticated HTTP download
link, not rebuilt from the diagnostic JSON. SHA256 of the before-layout-upgrade
file: `2575cdd03b82a93868be4e3719402d0153e9ef42475436a73de425c461bd01db`.
It contains five slides, one native table, three native charts, three embedded
workbooks and zero raster images. Full title text and its OOXML soft line break,
table value 168, column values 12/18/25/41, both line series and doughnut values
50/30/20 match the actual saved canvas. All five downloaded pages were rendered
and visually reviewed using LibreOffice.

A separately named control copy of this downloaded file was edited through native
PowerPoint object APIs (table 168→169 and chart 41→42), saved and reopened. It is
explicitly a derived editability test, not another product export. The original
file remains unchanged. Embedded workbook formulas and external relationships
were absent in this controlled fixture. Microsoft PowerPoint desktop UI is untested.

### Failures and interpretation

- The model added an incorrect sentence calling a +6 increment the largest when
  subsequent increments were +7. This is model-generated content, not an exporter
  arithmetic bug.
- The original web cover had overlapping summary/list content and a clipped
  circular note. Its template accepted much more text than the geometry could fit.
  Layout v2 retains every word and all five list items, adjusts bounded geometry
  and typography, and rejects content that still exceeds safe capacity.
- The original downloaded PPTX did **not** reproduce that same visible overflow:
  the native text boxes enable Office auto-fit, and LibreOffice reduced text to
  fit. This difference is why browser and exported-file visuals are checked separately.
- The chart-only instruction explicitly prohibited changing adjacent text. That
  text therefore still says 32 after the chart becomes 41. This is scoped-edit
  test evidence, not a consistent business-report deliverable.
- The final package was applied to the same authenticated host. The explicit
  layout action changed exactly the 73 properties predicted by the reviewed pure
  function across five slides; every original word, data value, color and other
  field was preserved. After save/reload and Chinese→EN→Chinese, the complete
  diagnostic JSON was byte-for-byte identical to the saved adjusted canvas.
- All five final web pages and exported PDF renders were visually reviewed. The
  supplied Lingzhiji logo, generator title, AI Assistant control, language switch
  and localized export/layout flow were verified in the actual UI. Two missed
  entry-point labels and generator metadata found during QA were corrected and
  rechecked without changing presentation content or provider values.
- Final actual HTTP-downloaded PPTX SHA256:
  `113e60181cfcb3f6410d3211887aa9b814b20729340dbcdb51b4fb7a361eb533`.
  It retains the same five-slide native object/data checks and displayed no
  export warnings. This file was not reconstructed from a JSON fixture.

## Not yet verified

- Provider bills, additional models or image-provider behavior beyond the one tested configuration
- The Microsoft PowerPoint application UI; rendering used LibreOffice
- Every possible Standard canvas object, arbitrary HTML, Smart presentations or arbitrary imported PowerPoint decks
- Production load, deployment hardening, or packaged-binary licensing
- nginx binary execution: native download rules received source/boundary review; the tested host uses the private Next proxy
- Atomic all-page persistence: layout application is locally all-or-nothing, but upstream saves pages individually; network failure may require retry and refresh verification

This record establishes the specific offline and real-UI scope above. It does
not certify every deployment or claim a production-ready replacement
for every upstream export feature. Final repository history must be scanned after
commits are created and again immediately before publication.
