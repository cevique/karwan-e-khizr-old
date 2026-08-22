import React from "react";
import { View, ViewStyle, StyleSheet, Pressable } from "react-native";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "./Text";

export type ChipVariant = "default" | "success" | "warning" | "error" | "accent" | "eco" | "outline";

export interface ChipProps {
  label: string;
  variant?: ChipVariant;
  icon?: React.ReactNode;
  onPress?: () => void;
  selected?: boolean;
  style?: ViewStyle;
}

export const Chip: React.FC<ChipProps> = ({
  label,
  variant = "default",
  icon,
  onPress,
  selected = false,
  style,
}) => {
  const getStyles = (): { bg: string; text: string; border: string } => {
    if (selected) {
      return { bg: colors.accent, text: colors.textInverse, border: colors.accent };
    }
    switch (variant) {
      case "success":
        return { bg: colors.successSoft, text: colors.success, border: "transparent" };
      case "warning":
        return { bg: colors.warningLiveSoft, text: colors.warningLive, border: "transparent" };
      case "error":
        return { bg: colors.errorSoft, text: colors.error, border: "transparent" };
      case "accent":
        return { bg: colors.accentSoft, text: colors.accent, border: "transparent" };
      case "eco":
        return { bg: colors.surfaceEco, text: colors.textUrdu, border: "transparent" };
      case "outline":
        return { bg: colors.surface, text: colors.textSecondary, border: colors.borderLight };
      default:
        return { bg: colors.surfaceMuted, text: colors.textSecondary, border: "transparent" };
    }
  };

  const { bg, text, border } = getStyles();

  const containerStyle: ViewStyle = {
    backgroundColor: bg,
    borderColor: border,
    borderWidth: border !== "transparent" ? 1 : 0,
    borderRadius: radii.pill,
    paddingVertical: spacing.xxs + 2,
    paddingHorizontal: spacing.sm + 2,
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
  };

  const content = (
    <View style={containerStyle}>
      {icon && <View style={styles.iconContainer}>{icon}</View>}
      <Text variant="captionMedium" color={text}>
        {label}
      </Text>
    </View>
  );

  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [pressed && styles.pressed, style]}>
        {content}
      </Pressable>
    );
  }

  return <View style={style}>{content}</View>;
};

const styles = StyleSheet.create({
  iconContainer: {
    marginRight: spacing.xxs + 2,
  },
  pressed: {
    opacity: 0.8,
  },
});
