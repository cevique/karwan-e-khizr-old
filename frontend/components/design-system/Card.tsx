import React from "react";
import { View, ViewStyle, Pressable, PressableProps, StyleSheet } from "react-native";
import { colors, radii, spacing, elevation } from "../../constants/theme";

export type CardElevation = "flat" | "soft" | "medium" | "floating";

export interface CardProps extends PressableProps {
  elevationVariant?: CardElevation;
  padding?: keyof typeof spacing;
  borderRadius?: number;
  backgroundColor?: string;
  borderColor?: string;
  selected?: boolean;
  selectedBorderColor?: string;
  style?: ViewStyle | ViewStyle[];
  children: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  elevationVariant = "soft",
  padding = "base",
  borderRadius = radii.card,
  backgroundColor = colors.surface,
  borderColor = colors.divider,
  selected = false,
  selectedBorderColor = colors.accent,
  style,
  children,
  onPress,
  ...props
}) => {
  const shadowStyle = elevation[elevationVariant] || elevation.soft;
  const paddingValue = spacing[padding];

  const cardStyle: ViewStyle = {
    backgroundColor,
    borderRadius,
    padding: paddingValue,
    borderWidth: selected ? 2 : borderColor ? 1 : 0,
    borderColor: selected ? selectedBorderColor : borderColor,
    ...shadowStyle,
  };

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        style={({ pressed }) => [
          cardStyle,
          pressed && styles.pressed,
          style,
        ]}
        {...props}
      >
        {children}
      </Pressable>
    );
  }

  return <View style={[cardStyle, style]}>{children}</View>;
};

const styles = StyleSheet.create({
  pressed: {
    opacity: 0.94,
    transform: [{ scale: 0.99 }],
  },
});
