import React from "react";
import { View, StyleSheet, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radii } from "../../constants/theme";
import { Text } from "../../components/design-system/Text";
import { MapView } from "../../components/map";
import { JourneyTimeline } from "../../components/transit/JourneyTimeline";
import { DemoBanner } from "../../components/transit/DemoBanner";
import { MOCK_JOURNEYS } from "../../mocks/journeys";
import { MOCK_STOPS } from "../../mocks/stops";

export default function JourneyDetailScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    id?: string;
    originName?: string;
    destinationName?: string;
  }>();

  const journey = MOCK_JOURNEYS[0]; // Primary recommended journey
  const originName = params.originName || "Ammar Chowk";
  const destinationName = params.destinationName || "Saddar";

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          style={({ pressed }) => [styles.iconButton, pressed && styles.pressed]}
          onPress={() => router.back()}
        >
          <Ionicons name="chevron-back" size={24} color={colors.textPrimary} />
        </Pressable>

        <Text variant="title" color={colors.textPrimary} weight="700">
          Journey Summary
        </Text>

        <Pressable
          style={({ pressed }) => [styles.iconButton, pressed && styles.pressed]}
          onPress={() => {}}
        >
          <Ionicons name="share-social-outline" size={22} color={colors.textPrimary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Map Preview */}
        <View style={styles.mapContainer}>
          <MapView
            center={[73.065, 33.615]}
            zoom={12.5}
            stops={MOCK_STOPS.slice(6, 11)}
          />
        </View>

        <View style={styles.demoWrapper}>
          <DemoBanner />
        </View>

        {/* Detailed Timeline */}
        <JourneyTimeline
          journey={journey}
          originName={originName}
          destinationName={destinationName}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  iconButton: {
    padding: spacing.xs,
  },
  scrollContent: {
    padding: spacing.base,
    paddingBottom: spacing.xxl,
  },
  mapContainer: {
    height: 220,
    borderRadius: radii.lg,
    overflow: "hidden",
    marginBottom: spacing.md,
  },
  demoWrapper: {
    alignSelf: "center",
    marginBottom: spacing.xs,
  },
  pressed: {
    opacity: 0.7,
  },
});
