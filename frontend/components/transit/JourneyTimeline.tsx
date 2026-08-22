import React from "react";
import { View, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { JourneyRead, RideLegRead, WalkLegRead } from "../../types";
import { colors, radii, spacing } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { Card } from "../design-system/Card";
import { Chip } from "../design-system/Chip";
import { RouteBadge } from "./RouteBadge";
import { formatDuration, formatDistance } from "../../utils/format";

export interface JourneyTimelineProps {
  journey: JourneyRead;
  originName: string;
  destinationName: string;
}

export const JourneyTimeline: React.FC<JourneyTimelineProps> = ({
  journey,
  originName,
  destinationName,
}) => {
  return (
    <Card elevationVariant="soft" padding="lg" style={styles.container}>
      <View style={styles.headerRow}>
        <Text variant="title">Route Details</Text>
        <Chip
          label="Live tracking"
          variant="success"
          icon={<Ionicons name="radio-outline" size={12} color={colors.success} />}
        />
      </View>

      <View style={styles.timelineWrapper}>
        {/* Origin Step */}
        <View style={styles.stepItem}>
          <View style={styles.dotContainer}>
            <View style={styles.originDot} />
            <View style={styles.verticalLine} />
          </View>
          <View style={styles.stepContent}>
            <Text variant="heading" weight="700">
              {originName}
            </Text>
          </View>
        </View>

        {/* Journey Legs */}
        {journey.legs.map((leg, index) => {
          if (leg.type === "walk") {
            const walkLeg = leg as WalkLegRead;
            return (
              <View key={`timeline-leg-${index}`} style={styles.stepItem}>
                <View style={styles.dotContainer}>
                  <View style={styles.dashedLine} />
                </View>
                <View style={styles.stepContent}>
                  <View style={styles.walkMetaRow}>
                    <Ionicons name="walk-outline" size={14} color={colors.textSecondary} style={styles.stepIcon} />
                    <Text variant="caption" color={colors.textSecondary}>
                      Walk {formatDuration(walkLeg.duration_s)} ({formatDistance(walkLeg.distance_m)})
                    </Text>
                  </View>
                </View>
              </View>
            );
          } else {
            const rideLeg = leg as RideLegRead;
            return (
              <View key={`timeline-leg-${index}`} style={styles.stepItem}>
                <View style={styles.dotContainer}>
                  <View style={styles.busDotCircle}>
                    <Ionicons name="bus" size={10} color={colors.textInverse} />
                  </View>
                  <View style={styles.verticalLineGreen} />
                </View>
                <View style={styles.stepContent}>
                  <View style={styles.rideBadgeRow}>
                    <RouteBadge
                      shortName={rideLeg.route.short_name}
                      color={rideLeg.route.color}
                      variant="outlined"
                      size="sm"
                    />
                  </View>

                  <Text variant="captionMedium" color={colors.textSecondary} style={styles.towardsText}>
                    Towards {rideLeg.alight_stop.name}
                  </Text>

                  <View style={styles.stopDetailsRow}>
                    <Ionicons name="git-commit-outline" size={14} color={colors.textTertiary} style={styles.stepIcon} />
                    <Text variant="caption" color={colors.textTertiary}>
                      {rideLeg.intermediate_stops.length + 1} stops • {formatDuration(rideLeg.duration_s)}
                    </Text>
                  </View>
                </View>
              </View>
            );
          }
        })}

        {/* Destination Step */}
        <View style={styles.stepItem}>
          <View style={styles.dotContainer}>
            <View style={styles.destinationDot} />
          </View>
          <View style={styles.stepContent}>
            <Text variant="heading" weight="700">
              {destinationName}
            </Text>
          </View>
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  container: {
    marginTop: spacing.md,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.base,
  },
  timelineWrapper: {
    paddingLeft: spacing.xs,
  },
  stepItem: {
    flexDirection: "row",
    minHeight: 48,
  },
  dotContainer: {
    width: 24,
    alignItems: "center",
  },
  originDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.textPrimary,
    marginTop: 4,
  },
  destinationDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.textPrimary,
    marginTop: 4,
  },
  busDotCircle: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  verticalLine: {
    width: 2,
    flex: 1,
    backgroundColor: colors.divider,
    marginVertical: 4,
  },
  verticalLineGreen: {
    width: 3,
    flex: 1,
    backgroundColor: colors.accent,
    marginVertical: 4,
  },
  dashedLine: {
    width: 2,
    flex: 1,
    borderWidth: 1,
    borderColor: colors.textTertiary,
    borderStyle: "dashed",
    marginVertical: 4,
  },
  stepContent: {
    flex: 1,
    marginLeft: spacing.md,
    paddingBottom: spacing.md,
  },
  walkMetaRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  stepIcon: {
    marginRight: 4,
  },
  rideBadgeRow: {
    marginBottom: spacing.xxs,
  },
  towardsText: {
    marginBottom: 2,
  },
  stopDetailsRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: spacing.xxs,
  },
});
