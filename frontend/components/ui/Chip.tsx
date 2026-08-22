import { StyleSheet, Text, TouchableOpacity } from "react-native";
import { colors, radii, spacing, type } from "@/constants/theme";

interface ChipProps {
  label: string;
  selected?: boolean;
  onPress?: () => void;
}

export function Chip({ label, selected = false, onPress }: ChipProps) {
  return (
    <TouchableOpacity
      disabled={!onPress}
      onPress={onPress}
      style={[styles.chip, selected ? styles.selected : styles.unselected]}
      activeOpacity={0.7}
    >
      <Text style={[styles.label, { color: selected ? colors.accent : colors.textPrimary }]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  chip: {
    borderRadius: radii.pill,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.base,
  },
  unselected: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: colors.divider,
  },
  selected: {
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: "transparent",
  },
  label: {
    ...type.body,
    fontWeight: "500",
  },
});
