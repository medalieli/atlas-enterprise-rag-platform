# Deterministic parsing and chunking

## Architecture

Milestone 5 extends the identifier-only Celery ingestion task with plain-Python layers:
parser selection, structured extraction, cleaning, chunking, and atomic publication.
`pypdf` 6 parses PDFs under its BSD license; `python-docx` 1.2 parses OOXML Word files
under its MIT license. No external API, LLM, LangChain, or LangGraph participates.

Parsing and checksum verification happen outside database transactions. A PostgreSQL
session advisory lock keyed by job ID excludes concurrent duplicate tasks and is released
automatically if a worker dies. A short final transaction replaces source units/chunks
and marks the document/job successful together. Permanent parser errors fail safely;
storage and database errors use the existing bounded Celery retries.

## Normalized source representation and traceability

A `document_source_units` row is the reproducible text coordinate system. A PDF page is
one source unit with a 1-based page number. A DOCX heading region is one source unit with
its heading path. Each row stores normalized text, stable unit index, source type, block
boundaries, and SHA-256 content hash.

Every chunk has a required source-unit foreign key, tenant/document key, global stable
chunk index, exact half-open character offsets, content SHA-256, and pipeline fingerprint.
Slicing `normalized_text[start_offset:end_offset]` must equal chunk content. Metadata also
records the immutable original checksum and parser, cleaner, and chunker versions.

## Cleaning rules (`clean-v1`)

Cleaning is pure and deterministic: CRLF/CR become LF; Unicode becomes NFC; unsafe control
characters are removed; horizontal runs collapse; excessive blank lines become one blank
line. Paragraph, heading, list, table, punctuation, number, and wording boundaries remain.
Lowercase word fragments separated by `-` plus a line break are conservatively joined.
No summarizing, spelling correction, translation, or rewriting occurs. Repeated headers
and footers are retained because no conservative corpus-tested removal threshold exists.

## Chunking rules (`chunk-v1`)

Structure is split first: PDF pages never mix; DOCX heading regions never mix. Within a
source unit, deterministic character windows prefer sentence endings, then whitespace,
then a hard maximum. Defaults are target 1,200 characters, maximum 1,800, and 150 overlap.
Overlap never crosses a source unit. Empty normalized units produce no chunks. The
fingerprint hashes parser/cleaner/chunker versions and all chunk-size configuration.

## Extraction behavior and limits

PDF pages retain order and page numbers. Layout extraction is cleaned to avoid excessive
whitespace. Corrupt and encrypted PDFs fail permanently; an entirely textless PDF reports
that OCR is required. Empty pages may remain as source units when other pages contain text.

DOCX top-level paragraphs and tables retain XML document order. Heading styles build a
hierarchical path, list styles receive a stable `- ` marker, and table rows/cells use a
deterministic ` | ` representation. Images are ignored.

Defaults: 500 PDF pages, 5,000,000 extracted characters, 50 MiB declared PDF content
streams, 120-second soft/150-second hard task limits, and a 512 MiB worker-container memory
ceiling. Upload and expanded-DOCX limits from Milestone 4 still apply. No extracted text is
logged.

Limitations: OCR/scanned images, text boxes, tracked revision semantics, floating objects,
headers/footers, footnote ordering, deeply nested tables, and exact visual PDF reading order
are not reconstructed. Complex Word fields may expose only the text represented by
`python-docx`. These cases require later, explicitly scoped work.
