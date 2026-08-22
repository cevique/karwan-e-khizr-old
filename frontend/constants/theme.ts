export const colors = {
  // Backgrounds & Surfaces
  bgPrimary: "#FAFAFA",
  surface: "#FFFFFF",
  surfaceElevated: "#FFFFFF",
  surfaceMuted: "#F4F5F7",
  surfaceAccentSoft: "rgba(10, 110, 100, 0.08)",
  surfaceEco: "#EAF5EE",

  // Text Colors
  textPrimary: "#14181C",
  textSecondary: "#6B7280",
  textTertiary: "#9CA3AF",
  textInverse: "#FFFFFF",
  textAccent: "#0A6E64",
  textUrdu: "#0C5A3E",

  // Brand Accents
  accent: "#0A6E64",
  accentHover: "#08574F",
  accentSoft: "rgba(10, 110, 100, 0.08)",
  accentBorder: "rgba(10, 110, 100, 0.25)",

  // Status & Indicators
  success: "#1B9E77",
  successSoft: "#E6F4EE",
  warningLive: "#FF6B35",
  warningLiveSoft: "#FFF0EB",
  error: "#E53E3E",
  errorSoft: "#FDE8E8",

  // Borders & Dividers
  divider: "#EEEFF1",
  borderLight: "#E5E7EB",
  borderFocus: "#0A6E64",

  // Transit Line Colors (Islamabad / Rawalpindi Transit Network)
  routeRed: "#DC2626",      // Metrobus Red Line (Pak Secretariat - Saddar)
  routeOrange: "#F59E0B",   // Orange Line (Faiz Ahmed Faiz - Airport)
  routeBlue: "#2563EB",     // Blue Line (PIMS - Gulberg Green)
  routeGreen: "#0A6E64",    // Green Line & Feeder Electric (PIMS - Bhara Kahu)
  routeFeeder: "#7C3AED",   // Generic Feeder Routes (FR-*)
  routeWalk: "#9CA3AF",     // Walking segments
} as const;

export const spacing = {
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  base: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
  xxxl: 64,
} as const;

export const radii = {
  xs: 4,
  sm: 8,
  md: 12,
  button: 12,
  card: 14,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export const elevation = {
  flat: {
    shadowColor: "transparent",
    shadowOpacity: 0,
    shadowRadius: 0,
    shadowOffset: { width: 0, height: 0 },
    elevation: 0,
  },
  soft: {
    shadowColor: "#000000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  medium: {
    shadowColor: "#000000",
    shadowOpacity: 0.10,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  floating: {
    shadowColor: "#000000",
    shadowOpacity: 0.15,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
} as const;

export const type = {
  display: { fontSize: 26, lineHeight: 32, fontWeight: "700" as const },
  title: { fontSize: 20, lineHeight: 26, fontWeight: "600" as const },
  heading: { fontSize: 17, lineHeight: 22, fontWeight: "600" as const },
  subheading: { fontSize: 15, lineHeight: 20, fontWeight: "600" as const },
  body: { fontSize: 15, lineHeight: 20, fontWeight: "400" as const },
  caption: { fontSize: 13, lineHeight: 17, fontWeight: "400" as const },
  captionMedium: { fontSize: 13, lineHeight: 17, fontWeight: "500" as const },
  micro: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: "600" as const,
    textTransform: "uppercase" as const,
    letterSpacing: 0.5,
  },
} as const;

export const motion = {
  durationFastMs: 150,
  durationNormalMs: 220,
  durationSlowMs: 350,
  easing: "ease-out",
} as const;
