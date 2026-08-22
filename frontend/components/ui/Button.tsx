import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View, ViewStyle } from "react-native";
import { colors, radii, spacing, type } from "@/constants/theme";

interface ButtonProps {
  label: string;
  onPress?: () => void;
  variant?: "filled" | "ghost";
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
}

export function Button({
  label,
  onPress,
  variant = "filled",
  disabled = false,
  loading = false,
  style,
}: ButtonProps) {
  const filled = variant === "filled";
  return (
    <TouchableOpacity
      activeOpacity={0.8}
      onPress={onPress}
      disabled={disabled || loading}
      style={[styles.base, filled ? styles.filled : styles.ghost, disabled && styles.disabled, style]}
    >
      {loading ? (
        <ActivityIndicator color={filled ? colors.surface : colors.accent} />
      ) : (
        <View>
          <Text style={[styles.label, { color: filled ? colors.surface : colors.accent }]}>
            {label}
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    borderRadius: radii.button,
    paddingVertical: 14,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  filled: {
    backgroundColor: colors.accent,
  },
  ghost: {
    backgroundColor: "transparent",
  },
  disabled: {
    opacity: 0.4,
  },
  label: {
    ...type.body,
    fontWeight: "600",
  },
});
