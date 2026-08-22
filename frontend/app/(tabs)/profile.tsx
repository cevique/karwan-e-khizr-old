import React from "react";
import { View, StyleSheet, ScrollView, Image } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radii } from "../../constants/theme";
import { Text } from "../../components/design-system/Text";
import { Card } from "../../components/design-system/Card";
import { Chip } from "../../components/design-system/Chip";
import { Divider } from "../../components/design-system/Divider";

export default function ProfileScreen() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Brand Header */}
        <Card elevationVariant="soft" padding="lg" style={styles.brandCard}>
          <View style={styles.brandRow}>
            <Image
              source={require("../../assets/images/icon.png")}
              style={styles.brandLogo}
              resizeMode="contain"
            />
            <View style={styles.brandTextCol}>
              <Text variant="title" color={colors.textAccent} weight="700">
                Karwan e Khizr
              </Text>
              <Text variant="heading" color={colors.textUrdu} style={styles.urduText}>
                کاروانِ خِضر
              </Text>
              <Text variant="caption" color={colors.textSecondary}>
                Public Transit Journey Planner
              </Text>
            </View>
          </View>

          <Divider marginVertical="md" />

          <View style={styles.versionRow}>
            <Chip label="v0.1.0 Hackathon Edition" variant="accent" />
            <Chip label="Islamabad & Rawalpindi" variant="eco" />
          </View>
        </Card>

        {/* Network Statistics Card */}
        <View style={styles.sectionHeader}>
          <Text variant="heading" weight="700">
            Transit Coverage
          </Text>
        </View>

        <Card elevationVariant="soft" padding="base" style={styles.infoCard}>
          <View style={styles.statGrid}>
            <View style={styles.statItem}>
              <Text variant="display" color={colors.accent} weight="700">
                26
              </Text>
              <Text variant="caption" color={colors.textSecondary}>
                Transit Routes
              </Text>
            </View>

            <View style={styles.statDivider} />

            <View style={styles.statItem}>
              <Text variant="display" color={colors.accent} weight="700">
                122
              </Text>
              <Text variant="caption" color={colors.textSecondary}>
                Network Stops
              </Text>
            </View>

            <View style={styles.statDivider} />

            <View style={styles.statItem}>
              <Text variant="display" color={colors.accent} weight="700">
                2
              </Text>
              <Text variant="caption" color={colors.textSecondary}>
                Operators
              </Text>
            </View>
          </View>
        </Card>

        {/* System Info */}
        <View style={styles.sectionHeader}>
          <Text variant="heading" weight="700">
            About Karwan-e-Khizr
          </Text>
        </View>

        <Card elevationVariant="soft" padding="base" style={styles.infoCard}>
          <View style={styles.featureRow}>
            <Ionicons name="map-outline" size={20} color={colors.accent} style={styles.featureIcon} />
            <View style={styles.featureTextCol}>
              <Text variant="subheading">Interactive MapLibre Engine</Text>
              <Text variant="caption" color={colors.textSecondary}>
                Powered by OpenFreeMap vector tiles & native MapLibre SDK.
              </Text>
            </View>
          </View>

          <Divider marginVertical="sm" />

          <View style={styles.featureRow}>
            <Ionicons name="bus-outline" size={20} color={colors.accent} style={styles.featureIcon} />
            <View style={styles.featureTextCol}>
              <Text variant="subheading">Realtime Vehicle Telemetry</Text>
              <Text variant="caption" color={colors.textSecondary}>
                Simulated vehicle positions with live arrival time predictions.
              </Text>
            </View>
          </View>

          <Divider marginVertical="sm" />

          <View style={styles.featureRow}>
            <Ionicons name="analytics-outline" size={20} color={colors.accent} style={styles.featureIcon} />
            <View style={styles.featureTextCol}>
              <Text variant="subheading">Multi-Leg Journey Engine</Text>
              <Text variant="caption" color={colors.textSecondary}>
                Ranked recommendations by duration, transfers, and walking.
              </Text>
            </View>
          </View>
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  scrollContent: {
    padding: spacing.base,
    paddingBottom: spacing.xxl,
  },
  brandCard: {
    marginBottom: spacing.base,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  brandLogo: {
    width: 60,
    height: 60,
    borderRadius: radii.md,
    marginRight: spacing.md,
  },
  brandTextCol: {
    flex: 1,
  },
  urduText: {
    marginTop: -2,
    marginBottom: 2,
  },
  versionRow: {
    flexDirection: "row",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  sectionHeader: {
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  infoCard: {
    marginBottom: spacing.md,
  },
  statGrid: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
    paddingVertical: spacing.xs,
  },
  statItem: {
    alignItems: "center",
  },
  statDivider: {
    width: 1,
    height: 36,
    backgroundColor: colors.divider,
  },
  featureRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingVertical: spacing.xs,
  },
  featureIcon: {
    marginRight: spacing.md,
    marginTop: 2,
  },
  featureTextCol: {
    flex: 1,
  },
});
