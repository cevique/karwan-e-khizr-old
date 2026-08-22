import React from "react";
import { View, ViewStyle, StyleSheet } from "react-native";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "../design-system/Text";

export interface RouteBadgeProps {
  shortName: string;
  color?: string | null;
  size?: "sm" | "md" | "lg";
  variant?: "filled" | "outlined" | "circle";
  icon?: React.ReactNode;
  style?: ViewStyle;
}

export function getRouteColor(shortName: string, backendColor?: string | null): string {
  if (backendColor && backendColor.startsWith("#")) {
    return backendColor;
  }
  const normalized = shortName.toUpperCase();
  if (normalized.includes("RED") || normalized.includes("RL-")) return colors.routeRed;
  if (normalized.includes("ORANGE") || normalized.includes("BRT")) return colors.routeOrange;
  if (normalized.includes("BLUE")) return colors.routeBlue;
  if (normalized.includes("GREEN") || normalized.includes("GL")) return colors.routeGreen;
  if (normalized.startsWith("FR")) return colors.routeFeeder;
  return colors.accent;
}

export const RouteBadge: React.FC<RouteBadgeProps> = ({
  shortName,
  color,
  size = "md",
  variant = "filled",
  icon,
  style,
}) => {
  const badgeColor = getRouteColor(shortName, color);

  if (variant === "circle") {
    const circleDimensions = size === "sm" ? 28 : size === "lg" ? 44 : 36;
    const textSize = size === "sm" ? "micro" : size === "lg" ? "heading" : "captionMedium";

    return (
      <View
        style={[
          styles.circleContainer,
          {
            width: circleDimensions,
            height: circleDimensions,
            borderRadius: circleDimensions / 2,
            backgroundColor: badgeColor,
          },
          style,
        ]}
      >
        <Text variant={textSize} color={colors.textInverse} weight="700" align="center">
          {shortName}
        </Text>
      </View>
    );
  }

  const isOutlined = variant === "outlined";
  const paddingV = size === "sm" ? spacing.xxs : size === "lg" ? spacing.sm : spacing.xs;
  const paddingH = size === "sm" ? spacing.xs + 2 : size === "lg" ? spacing.md : spacing.sm + 2;
  const textVariant = size === "sm" ? "micro" : size === "lg" ? "subheading" : "captionMedium";

  const containerStyle: ViewStyle = {
    backgroundColor: isOutlined ? colors.surface : badgeColor,
    borderWidth: isOutlined ? 1.5 : 0,
    borderColor: isOutlined ? badgeColor : "transparent",
    borderRadius: radii.sm,
    paddingVertical: paddingV,
    paddingHorizontal: paddingH,
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
  };

  return (
    <View style={[containerStyle, style]}>
      {icon && <View style={styles.iconMargin}>{icon}</View>}
      <Text
        variant={textVariant}
        color={isOutlined ? badgeColor : colors.textInverse}
        weight="700"
      >
        {shortName}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  circleContainer: {
    alignItems: "center",
    justifyContent: "center",
  },
  iconMargin: {
    marginRight: spacing.xxs + 2,
  },
});
