import React from "react";
import { View, ViewStyle, StyleSheet } from "react-native";
import { colors, spacing } from "../../constants/theme";

export interface DividerProps {
  color?: string;
  thickness?: number;
  marginVertical?: keyof typeof spacing | number;
  style?: ViewStyle;
}

export const Divider: React.FC<DividerProps> = ({
  color = colors.divider,
  thickness = 1,
  marginVertical = "sm",
  style,
}) => {
  const mv = typeof marginVertical === "number" ? marginVertical : spacing[marginVertical];

  return (
    <View
      style={[
        {
          height: thickness,
          backgroundColor: color,
          marginVertical: mv,
          width: "100%",
        },
        style,
      ]}
    />
  );
};
