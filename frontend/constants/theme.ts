export const colors = {
  bgPrimary: "#FAFAFA",
  surface: "#FFFFFF",
  textPrimary: "#14181C",
  textSecondary: "#6B7280",
  textTertiary: "#9CA3AF",
  accent: "#0A6E64",
  accentSoft: "rgba(10, 110, 100, 0.08)",
  warningLive: "#FF6B35",
  success: "#1B9E77",
  divider: "#EEEFF1",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  base: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radii = {
  button: 12,
  card: 14,
  pill: 999,
} as const;

export const elevation = {
  soft: {
    shadowColor: "#000000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
} as const;

export const type = {
  display: { fontSize: 28, lineHeight: 34, fontWeight: "600" },
  title: { fontSize: 20, lineHeight: 26, fontWeight: "600" },
  heading: { fontSize: 17, lineHeight: 22, fontWeight: "600" },
  body: { fontSize: 15, lineHeight: 20, fontWeight: "400" },
  caption: { fontSize: 13, lineHeight: 16, fontWeight: "400" },
  micro: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: "500",
    textTransform: "uppercase" as const,
    letterSpacing: 0.5,
  },
} as const;

export const motion = {
  durationMs: 220,
  easing: "ease-out",
} as const;
