# DESIGN PRINCIPLES (overrides inspo screenshots' color usage)

1. Accent color (teal) is reserved for: primary buttons, active nav state,
   selected chips, live-indicator dots.
2. Warning/urgency color (orange) is reserved ONLY for time-sensitive live
   states (ETA < 5min, high occupancy, low seats). Never used decoratively on
   static badges, fares, or icons.
3. Route numbers use an outlined circle, not a filled colored square — one
   consistent motif across all screens.
4. Prefer whitespace + typographic weight over color and borders to establish
   hierarchy.
5. One shadow style, used sparingly. Prefer hairline dividers between list
   items over separate shadowed cards per row.
6. Any UI element in the inspo screenshots without a clear functional
   explanation (e.g. the avatar-stack icon) must be confirmed with the user
   before implementation — do not guess and build.

## Tokens

- bg-primary #FAFAFA · surface #FFFFFF · divider #EEEFF1
- text: primary #14181C · secondary #6B7280 · tertiary #9CA3AF
- accent #0A6E64 (actions/nav/live) · accent-soft 8% opacity
- warning-live #FF6B35 (ETA <5min / arriving-now only) · success #1B9E77
- Type scale: Display 28/34 SB −0.3 · Title 20/26 SB · Heading 17/22 SB ·
  Body 15/20 · Caption 13/16 secondary · Micro 11/14 Medium tertiary
  uppercase +0.5 tracking
- Spacing: 4/8/12/16/24/32/48 — card padding 20, stacked-card gap 16,
  screen margins 24 (16 inside sheets)
- Radius: cards 14 · buttons/inputs 12 · pill 999 (chips/status only)
- Elevation: one style `0 2px 12px rgba(0,0,0,0.06)` used sparingly;
  hairline dividers preferred between list rows
- Motion: 200–250ms ease-out; live marker/ETA interpolate smoothly
