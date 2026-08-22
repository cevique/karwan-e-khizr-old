import React from "react";
import { View, StyleSheet, Pressable, ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radii, spacing, elevation } from "../../constants/theme";

export interface MapControlsProps {
  onLocatePress?: () => void;
  onFilterPress?: () => void;
  onFullscreenPress?: () => void;
  style?: ViewStyle;
}

export const MapControls: React.FC<MapControlsProps> = ({
  onLocatePress,
  onFilterPress,
  onFullscreenPress,
  style,
}) => {
  return (
    <View style={[styles.container, style]}>
      {onFullscreenPress && (
        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.pressed]}
          onPress={onFullscreenPress}
        >
          <Ionicons name="expand-outline" size={20} color={colors.textPrimary} />
        </Pressable>
      )}

      {onFilterPress && (
        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.pressed]}
          onPress={onFilterPress}
        >
          <Ionicons name="options-outline" size={20} color={colors.textPrimary} />
        </Pressable>
      )}

      {onLocatePress && (
        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.pressed]}
          onPress={onLocatePress}
        >
          <Ionicons name="locate-outline" size={20} color={colors.accent} />
        </Pressable>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    right: spacing.base,
    top: spacing.base,
    gap: spacing.sm,
  },
  button: {
    width: 44,
    height: 44,
    borderRadius: radii.card,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    ...elevation.medium,
  },
  pressed: {
    backgroundColor: colors.surfaceMuted,
    transform: [{ scale: 0.96 }],
  },
});
