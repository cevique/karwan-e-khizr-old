import React from "react";
import {
  Pressable,
  PressableProps,
  StyleSheet,
  ViewStyle,
  TextStyle,
  ActivityIndicator,
  View,
} from "react-native";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "./Text";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends Omit<PressableProps, "style"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  title: string;
  icon?: React.ReactNode;
  iconPosition?: "left" | "right";
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  style?: ViewStyle;
  textStyle?: TextStyle;
}

export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  size = "md",
  title,
  icon,
  iconPosition = "left",
  loading = false,
  disabled = false,
  fullWidth = false,
  style,
  textStyle,
  ...props
}) => {
  const getContainerStyle = (pressed: boolean): ViewStyle => {
    let bg: string = colors.accent;
    let border: string = "transparent";

    switch (variant) {
      case "primary":
        bg = disabled ? colors.textTertiary : pressed ? colors.accentHover : colors.accent;
        break;
      case "secondary":
        bg = disabled ? colors.surfaceMuted : pressed ? "rgba(10, 110, 100, 0.15)" : colors.accentSoft;
        break;
      case "outline":
        bg = pressed ? colors.surfaceMuted : colors.surface;
        border = disabled ? colors.borderLight : colors.accentBorder;
        break;
      case "ghost":
        bg = pressed ? colors.surfaceMuted : "transparent";
        break;
      case "danger":
        bg = disabled ? colors.textTertiary : colors.error;
        break;
    }

    const paddingVertical = size === "sm" ? spacing.xs : size === "lg" ? spacing.md : spacing.sm;
    const paddingHorizontal = size === "sm" ? spacing.sm : size === "lg" ? spacing.lg : spacing.base;

    return {
      backgroundColor: bg,
      borderWidth: variant === "outline" ? 1.5 : 0,
      borderColor: border,
      borderRadius: radii.button,
      paddingVertical,
      paddingHorizontal,
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "center",
      opacity: disabled ? 0.6 : 1,
      width: fullWidth ? "100%" : undefined,
    };
  };

  const getTextColor = (): string => {
    if (disabled) return colors.textTertiary;
    switch (variant) {
      case "primary":
      case "danger":
        return colors.textInverse;
      case "secondary":
      case "outline":
      case "ghost":
        return colors.accent;
      default:
        return colors.textInverse;
    }
  };

  const textVariant = size === "sm" ? "captionMedium" : size === "lg" ? "heading" : "subheading";

  return (
    <Pressable
      disabled={disabled || loading}
      style={({ pressed }) => [getContainerStyle(pressed), style]}
      {...props}
    >
      {loading ? (
        <ActivityIndicator size="small" color={getTextColor()} />
      ) : (
        <View style={styles.contentRow}>
          {icon && iconPosition === "left" && <View style={styles.iconLeft}>{icon}</View>}
          <Text variant={textVariant} color={getTextColor()} style={textStyle}>
            {title}
          </Text>
          {icon && iconPosition === "right" && <View style={styles.iconRight}>{icon}</View>}
        </View>
      )}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  contentRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
  },
  iconLeft: {
    marginRight: spacing.xs,
  },
  iconRight: {
    marginLeft: spacing.xs,
  },
});
