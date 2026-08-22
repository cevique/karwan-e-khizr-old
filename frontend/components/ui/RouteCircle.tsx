import { StyleSheet, Text, View, ViewStyle } from "react-native";
import { colors, radii, spacing, type } from "@/constants/theme";

interface RouteCircleProps {
  label: string;
  size?: number;
  style?: ViewStyle;
}

export function RouteCircle({ label, size = 40, style }: RouteCircleProps) {
  return (
    <View
      style={[
        styles.circle,
        { width: size, height: size },
        label.length > 3 && { paddingHorizontal: spacing.sm, width: undefined },
        style,
      ]}
    >
      <Text style={[styles.label, label.length > 3 && { fontSize: 13 }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  circle: {
    borderRadius: radii.pill,
    borderWidth: 1.5,
    borderColor: colors.textPrimary,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  label: {
    ...type.body,
    fontWeight: "700",
    color: colors.textPrimary,
  },
});
