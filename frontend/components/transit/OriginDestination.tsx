import React from "react";
import { View, StyleSheet, Pressable, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radii, spacing, elevation } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { Card } from "../design-system/Card";
import { Divider } from "../design-system/Divider";

export interface OriginDestinationProps {
  originValue: string;
  destinationValue: string;
  onOriginChange?: (text: string) => void;
  onDestinationChange?: (text: string) => void;
  onSwapPress?: () => void;
  onLeaveNowPress?: () => void;
  onOptionsPress?: () => void;
  onOriginPress?: () => void;
  onDestinationPress?: () => void;
  readOnly?: boolean;
}

export const OriginDestination: React.FC<OriginDestinationProps> = ({
  originValue,
  destinationValue,
  onOriginChange,
  onDestinationChange,
  onSwapPress,
  onLeaveNowPress,
  onOptionsPress,
  onOriginPress,
  onDestinationPress,
  readOnly = false,
}) => {
  return (
    <View style={styles.outerContainer}>
      <Card elevationVariant="medium" padding="base" style={styles.card}>
        <View style={styles.rowWrapper}>
          {/* Dots & Connecting Line */}
          <View style={styles.indicatorCol}>
            <View style={styles.greenDot} />
            <View style={styles.dottedLine} />
            <View style={styles.redPinContainer}>
              <Ionicons name="location" size={14} color={colors.error} />
            </View>
          </View>

          {/* Input Fields */}
          <View style={styles.inputsCol}>
            {readOnly ? (
              <Pressable style={styles.inputPressable} onPress={onOriginPress}>
                <Text
                  variant="subheading"
                  color={originValue ? colors.textPrimary : colors.textTertiary}
                  numberOfLines={1}
                >
                  {originValue || "Choose origin stop..."}
                </Text>
              </Pressable>
            ) : (
              <TextInput
                value={originValue}
                onChangeText={onOriginChange}
                placeholder="Choose origin stop..."
                placeholderTextColor={colors.textTertiary}
                style={styles.input}
              />
            )}

            <Divider marginVertical={8} />

            {readOnly ? (
              <Pressable style={styles.inputPressable} onPress={onDestinationPress}>
                <Text
                  variant="subheading"
                  color={destinationValue ? colors.textPrimary : colors.textTertiary}
                  numberOfLines={1}
                >
                  {destinationValue || "Choose destination..."}
                </Text>
              </Pressable>
            ) : (
              <TextInput
                value={destinationValue}
                onChangeText={onDestinationChange}
                placeholder="Choose destination..."
                placeholderTextColor={colors.textTertiary}
                style={styles.input}
              />
            )}
          </View>

          {/* Swap Button */}
          {onSwapPress && (
            <Pressable
              style={({ pressed }) => [styles.swapButton, pressed && styles.pressed]}
              onPress={onSwapPress}
            >
              <Ionicons name="swap-vertical" size={20} color={colors.textPrimary} />
            </Pressable>
          )}
        </View>
      </Card>

      {/* Filter Row: Leave Now & Options */}
      <View style={styles.filterRow}>
        <Pressable
          style={({ pressed }) => [styles.filterDropdown, pressed && styles.pressed]}
          onPress={onLeaveNowPress}
        >
          <Text variant="captionMedium" color={colors.textPrimary}>
            Leave now
          </Text>
          <Ionicons name="chevron-down" size={14} color={colors.textPrimary} style={styles.dropIcon} />
        </Pressable>

        <Pressable
          style={({ pressed }) => [styles.optionsButton, pressed && styles.pressed]}
          onPress={onOptionsPress}
        >
          <Ionicons name="options-outline" size={16} color={colors.textPrimary} style={styles.dropIcon} />
          <Text variant="captionMedium" color={colors.textPrimary}>
            Options
          </Text>
        </Pressable>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  outerContainer: {
    width: "100%",
  },
  card: {
    borderRadius: radii.lg,
  },
  rowWrapper: {
    flexDirection: "row",
    alignItems: "center",
  },
  indicatorCol: {
    alignItems: "center",
    width: 24,
    marginRight: spacing.sm,
  },
  greenDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.success,
  },
  dottedLine: {
    height: 24,
    borderWidth: 1,
    borderColor: colors.textTertiary,
    borderStyle: "dashed",
    marginVertical: 2,
  },
  redPinContainer: {
    alignItems: "center",
    justifyContent: "center",
  },
  inputsCol: {
    flex: 1,
    justifyContent: "center",
  },
  inputPressable: {
    paddingVertical: spacing.xs,
  },
  input: {
    fontSize: 15,
    fontWeight: "600",
    color: colors.textPrimary,
    paddingVertical: spacing.xxs,
  },
  swapButton: {
    width: 36,
    height: 36,
    borderRadius: radii.md,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
    marginLeft: spacing.sm,
  },
  filterRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.md,
  },
  filterDropdown: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
  },
  dropIcon: {
    marginLeft: spacing.xxs,
    marginRight: spacing.xxs,
  },
  optionsButton: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
  },
  pressed: {
    opacity: 0.7,
  },
});
