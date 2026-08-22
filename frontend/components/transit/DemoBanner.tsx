import React from "react";
import { View, StyleSheet, ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { DEMO_MODE } from "../../constants/config";

export interface DemoBannerProps {
  forceShow?: boolean;
  style?: ViewStyle;
}

export const DemoBanner: React.FC<DemoBannerProps> = ({ forceShow = false, style }) => {
  if (!DEMO_MODE && !forceShow) return null;

  return (
    <View style={[styles.container, style]}>
      <Ionicons name="information-circle" size={14} color={colors.warningLive} style={styles.icon} />
      <Text variant="captionMedium" color={colors.warningLive}>
        Demo data — simulated realtime feed
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.warningLiveSoft,
    paddingVertical: spacing.xxs + 2,
    paddingHorizontal: spacing.sm + 2,
    borderRadius: radii.pill,
    alignSelf: "center",
    borderWidth: 1,
    borderColor: "rgba(255, 107, 53, 0.2)",
  },
  icon: {
    marginRight: spacing.xxs + 2,
  },
});
