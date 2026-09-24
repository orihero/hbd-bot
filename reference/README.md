# `reference/`

Somebody else's material, vendored so it can be read offline and diffed when it changes.
Nothing in here is ours, nothing here is built, imported, served or tested, and nothing in
`src/`, `tests/` or `deploy/` reads a file from this tree at runtime.

It exists because the alternative is worse. A vendor's API spec or a design tool's export is
the thing a module was *written against*, and when the module and the source disagree a year
later there is no way to tell which one moved unless the source is pinned in the repository at
the version that was read.

**The rule here is narrower than the one in `docs/`: a folder earns a place only if code or a
document cites it.** Material nobody cites is not reference, it is clutter, and it belongs in a
bookmark.

| Folder | What it is | Who cites it |
| --- | --- | --- |
| [`vibi-pro/`](vibi-pro/) | 34 endpoint specifications for vibi.pro — speech-to-text, text-to-speech, voice changer, AI dubbing, dialogue, voices, models. | Nothing yet. See below. |
| [`openpencil-export/`](openpencil-export/) | The Open Pencil design export the admin console was built from: four JSX component dumps and two OpenAPI descriptions. | Nine files in `admin-dashboard/src/`, by path, in their header comments. |

## `vibi-pro/` — kept against a decision that has not been made

These specs arrived in the repository root during the 2026-09-16 session and were committed at
the owner's request against possible later use. That commit said moving them was "a decision
about what they are FOR, and nobody has made it yet". **This folder is that decision, and it is
the smaller one:** they are reference material, not a document and not a product, so they live
here rather than under `docs/` with a row in its index.

What they are *for* is still open, and the research is unambiguous about the shape of it.
vibi.pro **cannot replace ElevenLabs** for this product: there is no music endpoint anywhere in
the 34 specs, and no Uzbek voice in the text-to-speech surface. Speech-to-text is a clean fit
and text-to-speech is usable for Russian and English only. Nothing has been wired up, and
picking any of it up is a decision for `docs/decisions/DECISIONS.md` with a cost line behind
it, not a change that starts in this folder.

The specs were checked for credentials before they were committed, not after. The only long
strings are placeholder UUIDs and a literal `sk_abc...` sample.

## `openpencil-export/` — the measured source for the console

This one is cited, heavily and by path. Nine files under `admin-dashboard/src/` open their
header comment by naming the export they were transcribed from — the nav rail from
`navbar-light.jsx`, the data table's metrics from `task-list.jsx`, the toolbar from
`projects-toolbar.jsx`, the detail panel's rules from `project-card.jsx`, and four API modules
from the two OpenAPI files.

Those comments say *measured*, and they mean it: the spacing, radii and weights in the console
were read off these files rather than chosen. Delete this folder and every one of those claims
becomes unverifiable. **It was `.openpencil-export/` at the repository root until 2026-09-21** —
a dotfolder, hidden from `ls`, holding the source of truth for a shipped interface. The leading
dot is gone and the citations were rewritten in the same change.
