import React from "react";
import { View, StyleSheet, ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing } from "../../constants/theme";
import { Text } from "./Text";
import { Button } from "./Button";

export interface EmptyStateProps {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  style?: ViewStyle;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = "bus-outline",
  title,
  description,
  actionLabel,
  onAction,
  style,
}) => {
  return (
    <View style={[styles.container, style]}>
      <View style={styles.iconCircle}>
        <Ionicons name={icon} size={36} color={colors.accent} />
      </View>
      <Text variant="heading" align="center" style={styles.title}>
        {title}
      </Text>
      {description && (
        <Text variant="body" color={colors.textSecondary} align="center" style={styles.description}>
          {description}
        </Text>
      )}
      {actionLabel && onAction && (
        <Button
          variant="primary"
          size="md"
          title={actionLabel}
          onPress={onAction}
          style={styles.button}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  iconCircle: {
    width: 68,
    height: 68,
    borderRadius: 34,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.base,
  },
  title: {
    marginBottom: spacing.xs,
  },
  description: {
    marginBottom: spacing.lg,
  },
  button: {
    minWidth: 140,
  },
});
