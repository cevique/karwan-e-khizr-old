import { StyleSheet, Text, View } from "react-native";
import { DEMO_MODE } from "@/constants/config";
import { colors, radii, spacing, type } from "@/constants/theme";

export function DemoChip() {
  if (!DEMO_MODE) return null;
  return (
    <View pointerEvents="none" style={styles.chip}>
      <Text style={styles.text}>Demo data — not live</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    position: "absolute",
    top: spacing.md,
    left: spacing.md,
    backgroundColor: "#B45309",
    borderRadius: radii.button,
    paddingVertical: 4,
    paddingHorizontal: spacing.md,
  },
  text: {
    ...type.caption,
    color: colors.surface,
    fontWeight: "700",
  },
});
