# Brand assets

mantis's visual identity, part of a shared house system across the project family.
The SVGs are self-contained - every glyph and shape is an outlined path, so nothing
depends on an installed font or a network fetch - and they are the source of truth:
edit them as code rather than re-exporting from a design tool.

> The asset files are named `mantis-*` and the wordmark reads **mantis** - the family
> short name for this repo (`mantis-research`).

| File | What | Where it is used |
|---|---|---|
| `mantis-mark-{light,dark}.svg` | The mark alone: accent tile with the diamond-ring figure cut out as true transparency | Favicon / avatar; anything down to 16 px |
| `mantis-wordmark-{light,dark}.svg` | The wordmark alone | Inline naming |
| `mantis-lockup-{light,dark}.svg` | Mark + wordmark | Headers |
| `mantis-hero-{light,dark}.svg` | 1280x240 banner: framed, centered lockup | Top of [README.md](../README.md) |
| `mantis-social-card.svg` / `.png` | 1280x640 dark card: lockup over a figure watermark | GitHub Settings -> Social preview (upload the PNG) |

## Embedding

GitHub renders READMEs in both light and dark; embed the theme pair with `<picture>`:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/mantis-hero-dark.svg">
  <img alt="mantis" src="assets/mantis-hero-light.svg" width="100%">
</picture>
```

The same pattern applies to the mark and the lockup.

## Tokens and rules

- Accent (iridescent violet): tile `#8D59A3` on light, `#A973C0` on dark; the accent
  rule is `#6C407F` on light and `#C398D6` on dark. House neutrals: ink `#171B1F`, paper
  `#FBFBFA`, muted `#5C666E`, badge-label `#2A3238`.
- A two-tone rule sits under the wordmark - `#6C407F` over `#3E9AA3` on light,
  `#C398D6` over `#56BFC7` on dark. This second hue appears in no other kit.
- Badges: shields.io `flat-square`, always `labelColor=2A3238`; version and meta
  badges use `6C407F`; CI and status badges keep shields' semantic defaults; at most
  five in the row.
- The tile is never outlined, recolored per context, or rotated; minimum mark size
  16 px.
- The assets carry no text beyond the wordmark.
