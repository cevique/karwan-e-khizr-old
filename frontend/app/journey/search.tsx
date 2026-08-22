import React, { useState, useEffect } from "react";
import { View, StyleSheet, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radii } from "../../constants/theme";
import { Text } from "../../components/design-system/Text";
import { OriginDestination } from "../../components/transit/OriginDestination";
import { JourneyCard } from "../../components/transit/JourneyCard";
import { Skeleton } from "../../components/design-system/Skeleton";
import { useJourneySearch } from "../../hooks/useJourneySearch";
import { JourneyRead } from "../../types";

export default function JourneySearchScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ originName?: string }>();

  const [origin, setOrigin] = useState<string>(params.originName || "Ammar Chowk");
  const [destination, setDestination] = useState<string>("Saddar");
  const [favorite, setFavorite] = useState<boolean>(false);

  const { journeys, loading, executeSearch } = useJourneySearch();

  useEffect(() => {
    // Initial mock search trigger
    executeSearch({
      origin: { latitude: 33.585, longitude: 73.076 },
      destination: { latitude: 33.5975, longitude: 73.0547 },
      objective: "fastest",
    });
  }, [executeSearch]);

  const handleSwap = () => {
    const temp = origin;
    setOrigin(destination);
    setDestination(temp);
  };

  const handleJourneySelect = (journey: JourneyRead, index: number) => {
    router.push({
      pathname: "/journey/[id]",
      params: {
        id: `journey-${index + 1}`,
        originName: origin,
        destinationName: destination,
        duration: journey.total_duration_s,
      },
    });
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Top Navigation Header */}
      <View style={styles.topHeader}>
        <Pressable
          style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}
          onPress={() => router.back()}
        >
          <Ionicons name="chevron-back" size={24} color={colors.textPrimary} />
        </Pressable>

        <Text variant="title" color={colors.textPrimary} weight="700">
          Select Route
        </Text>

        <Pressable
          style={({ pressed }) => [styles.heartButton, pressed && styles.pressed]}
          onPress={() => setFavorite(!favorite)}
        >
          <Ionicons
            name={favorite ? "heart" : "heart-outline"}
            size={22}
            color={favorite ? colors.error : colors.textPrimary}
          />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.contentContainer} showsVerticalScrollIndicator={false}>
        {/* Origin / Destination Search Box */}
        <OriginDestination
          originValue={origin}
          destinationValue={destination}
          onOriginChange={setOrigin}
          onDestinationChange={setDestination}
          onSwapPress={handleSwap}
          onLeaveNowPress={() => {}}
          onOptionsPress={() => {}}
        />

        {/* Recommended Routes Section */}
        <View style={styles.sectionHeaderRow}>
          <Text variant="heading" color={colors.textPrimary} weight="700">
            Recommended Routes
          </Text>
        </View>

        {loading ? (
          <View style={styles.loadingCol}>
            <Skeleton height={110} borderRadius={radii.card} style={styles.skeletonItem} />
            <Skeleton height={110} borderRadius={radii.card} style={styles.skeletonItem} />
            <Skeleton height={110} borderRadius={radii.card} style={styles.skeletonItem} />
          </View>
        ) : (
          journeys.map((journey, idx) => (
            <JourneyCard
              key={`journey-${idx}`}
              journey={journey}
              onPress={() => handleJourneySelect(journey, idx)}
            />
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  topHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  backButton: {
    padding: spacing.xs,
  },
  heartButton: {
    padding: spacing.xs,
  },
  contentContainer: {
    padding: spacing.base,
    paddingBottom: spacing.xxl,
  },
  sectionHeaderRow: {
    marginTop: spacing.lg,
    marginBottom: spacing.md,
  },
  loadingCol: {
    gap: spacing.md,
  },
  skeletonItem: {
    marginBottom: spacing.sm,
  },
  pressed: {
    opacity: 0.7,
  },
});
