import React from "react";
import { Text as RNText, TextStyle, TextProps as RNTextProps, StyleSheet } from "react-native";
import { type as typography, colors } from "../../constants/theme";

export type TextVariant =
  | "display"
  | "title"
  | "heading"
  | "subheading"
  | "body"
  | "caption"
  | "captionMedium"
  | "micro";

export interface TextProps extends RNTextProps {
  variant?: TextVariant;
  color?: string;
  align?: TextStyle["textAlign"];
  weight?: TextStyle["fontWeight"];
  italic?: boolean;
  children: React.ReactNode;
}

export const Text: React.FC<TextProps> = ({
  variant = "body",
  color = colors.textPrimary,
  align = "left",
  weight,
  italic = false,
  style,
  children,
  ...props
}) => {
  const variantStyle = typography[variant] || typography.body;

  const combinedStyle: TextStyle = {
    ...variantStyle,
    color,
    textAlign: align,
    ...(weight ? { fontWeight: weight } : {}),
    ...(italic ? { fontStyle: "italic" } : {}),
  };

  return (
    <RNText style={[combinedStyle, style]} {...props}>
      {children}
    </RNText>
  );
};
