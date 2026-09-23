# vendor/ — vendored third-party skills

Code here is **not** covered by this repository's MIT licence. Each subdirectory
carries its upstream licence and a `VENDORED.md` recording what was copied, from
where, when, and with which digest.

| Directory | Upstream | Licence | Used for |
|---|---|---|---|
| `lieflat-charts/` | `lieflat-charts` skill by 「躺在废墟里」([moxt.ai](https://moxt.ai)) | **PolyForm Noncommercial 1.0.0** | Selecting, building and exporting charts for the "self-drawn chart" step ([`references/lieflat-charts.md`](../references/lieflat-charts.md)) |

## Effect on licensing of this repository

Because `vendor/lieflat-charts/` redistributes PolyForm Noncommercial software, a
checkout that includes it is **noncommercial-use only**. The root `LICENSE` (MIT)
still covers everything else in the repository, but MIT cannot relicense the vendored
material, and the two cannot be merged into a single licence.

To use this repository commercially, remove `vendor/lieflat-charts/` — the
paper-reading flow itself (figure extraction, validation, bilingual pages, deployment)
has no other non-MIT dependency. The self-drawn-chart step would then need an
independently licensed chart library.

See [`lieflat-charts/VENDORED.md`](lieflat-charts/VENDORED.md) for provenance and
refresh instructions.