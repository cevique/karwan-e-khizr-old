import React from "react";
import { View, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { JourneyRead, RideLegRead, WalkLegRead } from "../../types";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { Card } from "../design-system/Card";
import { Chip } from "../design-system/Chip";
import { RouteBadge } from "./RouteBadge";
import { formatDuration, formatDistance, formatFare } from "../../utils/format";

export interface JourneyCardProps {
  journey: JourneyRead;
  onPress?: () => void;
}

export const JourneyCard: React.FC<JourneyCardProps> = ({ journey, onPress }) => {
  const isRecommended = journey.is_recommended || journey.objective === "fastest";

  return (
    <Card
      elevationVariant={isRecommended ? "medium" : "soft"}
      selected={isRecommended}
      selectedBorderColor={colors.accent}
      padding="base"
      style={styles.card}
      onPress={onPress}
    >
      {/* Best Match Badge */}
      {isRecommended && (
        <View style={styles.badgeWrapper}>
          <Chip label="Best match" variant="eco" />
        </View>
      )}

      {/* Main Content Row */}
      <View style={styles.mainRow}>
        {/* Left: Leg Itinerary Pipeline */}
        <View style={styles.itineraryCol}>
          <View style={styles.legsRow}>
            {journey.legs.map((leg, index) => {
              if (leg.type === "walk") {
                const walkLeg = leg as WalkLegRead;
                return (
                  <View key={`leg-${index}`} style={styles.legItemRow}>
                    <View style={styles.walkBadge}>
                      <Ionicons name="walk" size={14} color={colors.textSecondary} />
                      <Text variant="micro" color={colors.textSecondary} style={styles.walkDuration}>
                        {Math.round(walkLeg.duration_s / 60)} min
                      </Text>
                    </View>
                    {index < journey.legs.length - 1 && (
                      <Ionicons name="chevron-forward" size={10} color={colors.textTertiary} style={styles.arrow} />
                    )}
                  </View>
                );
              } else {
                const rideLeg = leg as RideLegRead;
                return (
                  <View key={`leg-${index}`} style={styles.legItemRow}>
                    <RouteBadge
                      shortName={rideLeg.route.short_name}
                      color={rideLeg.route.color}
                      variant="outlined"
                      size="sm"
                      icon={<Ionicons name="bus" size={12} color={rideLeg.route.color || colors.accent} />}
                    />
                    {index < journey.legs.length - 1 && (
                      <Ionicons name="chevron-forward" size={10} color={colors.textTertiary} style={styles.arrow} />
                    )}
                  </View>
                );
              }
            })}
          </View>

          {/* Subtext: Headway / Frequency */}
          {journey.headway_info && (
            <View style={styles.subtextRow}>
              <Ionicons name="time-outline" size={12} color={colors.textSecondary} style={styles.subIcon} />
              <Text variant="caption" color={colors.textSecondary}>
                {journey.headway_info}
              </Text>
            </View>
          )}
        </View>

        {/* Right: Duration & Fare Summary */}
        <View style={styles.summaryCol}>
          <Text variant="display" color={colors.textPrimary} weight="700" align="right">
            {formatDuration(journey.total_duration_s)}
          </Text>
          <Text variant="caption" color={colors.textSecondary} align="right">
            {formatFare(journey.fare_amount_pkr || 0)}
          </Text>
          <Text variant="caption" color={colors.textTertiary} align="right" style={styles.walkDistance}>
            {formatDistance(journey.total_walk_m)} walk
          </Text>
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginBottom: spacing.md,
  },
  badgeWrapper: {
    marginBottom: spacing.xs,
  },
  mainRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  itineraryCol: {
    flex: 1,
    marginRight: spacing.md,
  },
  legsRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.xs,
    marginBottom: spacing.xs + 2,
  },
  legItemRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  walkBadge: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.xs,
    paddingVertical: 2,
    paddingHorizontal: 6,
  },
  walkDuration: {
    marginLeft: 2,
  },
  arrow: {
    marginHorizontal: 4,
  },
  subtextRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: spacing.xxs,
  },
  subIcon: {
    marginRight: 4,
  },
  summaryCol: {
    alignItems: "flex-end",
  },
  walkDistance: {
    marginTop: 2,
  },
});
