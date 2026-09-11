# Vendored fonts

Four `.woff2` binaries, 199 KiB together, served from this origin and from nowhere else.
`../../styles/fonts.css` declares them and owns the three font stacks;
`../../../tools/build-fonts.py` regenerates them and documents every subsetting decision;
`../../../e2e/font-coverage.spec.ts` re-measures them in a real browser on every run.

| file | family | bytes | axes | what it draws |
| --- | --- | ---: | --- | --- |
| `mulish-latin-cyrillic-var.woff2` | Mulish | 85,732 | `wght 200–1000` | body, tables, all UI text |
| `urbanist-latin-var.woff2` | Urbanist | 34,132 | `wght 100–900` | headings and numerals |
| `noto-sans-mono-latin-cyrillic-var.woff2` | Noto Sans Mono | 81,168 | `wght 400–700` | ids, hashes, payloads |
| `bayram-status-symbols.woff2` | Bayram Status Symbols | 2,244 | static | §11.3's status glyphs |

## Coverage, read out of the binaries

| codepoint | Mulish | Urbanist | Noto Sans Mono | Bayram Status Symbols |
| --- | --- | --- | --- | --- |
| U+02BB `ʻ` MODIFIER LETTER TURNED COMMA | yes | yes (shares the `quoteleft` outline) | yes | – |
| U+02BC `ʼ` MODIFIER LETTER APOSTROPHE | yes | yes | yes | – |
| Cyrillic U+0400–04FF | 220 codepoints | **none** | 256 codepoints | – |
| Ў U+040E · Ғ U+0492 · Қ U+049A · Ҳ U+04B2 | yes | no | yes | – |
| ○ ◔ ◑ ◆ ◉ ✓ ✗ ⊘ ⚑ ↻ ■ 🔒 | none | none | none | all twelve |

**Urbanist has no Cyrillic.** That is why `--font-heading` names Mulish directly behind it,
and why the browser gate asserts both halves of it — that Urbanist draws `Oʻktam` and that it
does not draw `Дилноза`. Read the header of `../../styles/fonts.css` before changing a stack.

## Licences

Everything here is SIL Open Font License 1.1. None of the six upstream families reserves its
name: the phrase "Reserved Font Name" appears in these licence files only in the definitions
section, never in a copyright line. So the three text faces keep their own family names, and
only `Bayram Status Symbols` — which is a merge of three Noto faces and therefore none of them —
is renamed.

`licences/` carries the upstream `OFL.txt` for each source, unmodified:

| file | covers | upstream |
| --- | --- | --- |
| `OFL-mulish.txt` | Mulish | Copyright 2016 The Mulish Project Authors |
| `OFL-urbanist.txt` | Urbanist | Copyright 2021 The Urbanist Project Authors |
| `OFL-notosansmono.txt` | Noto Sans Mono | Copyright 2022 The Noto Project Authors |
| `OFL-notosanssymbols2.txt` | ○ ◔ ◑ ◆ ◉ ✓ ✗ ■ 🔒 ● ◐ ◕ ▲ ▼ ⚠ | Copyright 2022 The Noto Project Authors |
| `OFL-notosansmath.txt` | ⊘ ↻ | Copyright 2022 The Noto Project Authors |
| `OFL-notosanssymbols.txt` | ⚑ | Copyright 2022 The Noto Project Authors |

Nothing here comes from the site the reskin's design values were taken from. Mulish, Urbanist
and every Noto face are fetched from `github.com/google/fonts` by the build script, subset
locally, and committed.
