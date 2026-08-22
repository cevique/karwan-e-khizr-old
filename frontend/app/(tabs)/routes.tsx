import React, { useState } from "react";
import { View, StyleSheet, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radii } from "../../constants/theme";
import { Text } from "../../components/design-system/Text";
import { Card } from "../../components/design-system/Card";
import { SearchField } from "../../components/design-system/SearchField";
import { RouteBadge } from "../../components/transit/RouteBadge";
import { MOCK_ROUTES, MOCK_AGENCIES } from "../../mocks/routes";
import { RouteListItem } from "../../types";

export default function RoutesScreen() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState<string>("");

  const filteredRoutes = MOCK_ROUTES.filter((r) =>
    r.short_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (r.long_name && r.long_name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const handleRouteSelect = (route: RouteListItem) => {
    router.push({
      pathname: "/journey/search",
      params: { preselectRouteId: route.id },
    });
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Header */}
      <View style={styles.header}>
        <Text variant="display" color={colors.textPrimary} weight="700">
          Transit Network
        </Text>
        <Text variant="caption" color={colors.textSecondary}>
          Islamabad & Rawalpindi Routes
        </Text>
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Search */}
        <View style={styles.searchContainer}>
          <SearchField
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search routes or lines..."
            onClear={() => setSearchQuery("")}
          />
        </View>

        {/* Agency Sections */}
        {MOCK_AGENCIES.map((agency) => {
          const agencyRoutes = filteredRoutes.filter((r) => r.agency_id === agency.id);
          if (agencyRoutes.length === 0) return null;

          return (
            <View key={agency.id} style={styles.agencySection}>
              <Text variant="heading" color={colors.textPrimary} weight="700" style={styles.agencyTitle}>
                {agency.name}
              </Text>
              <Text variant="caption" color={colors.textTertiary} style={styles.agencySubtitle}>
                {agency.network_type}
              </Text>

              <View style={styles.routesList}>
                {agencyRoutes.map((route) => (
                  <Card
                    key={route.id}
                    elevationVariant="soft"
                    padding="md"
                    style={styles.routeCard}
                    onPress={() => handleRouteSelect(route)}
                  >
                    <View style={styles.routeRow}>
                      <RouteBadge
                        shortName={route.short_name}
                        color={route.color}
                        variant="filled"
                        size="md"
                      />
                      <View style={styles.routeInfoCol}>
                        <Text variant="heading" numberOfLines={1}>
                          {route.short_name}
                        </Text>
                        <Text variant="caption" color={colors.textSecondary} numberOfLines={1}>
                          {route.long_name}
                        </Text>
                      </View>
                      <Ionicons name="chevron-forward" size={18} color={colors.textTertiary} />
                    </View>
                  </Card>
                ))}
              </View>
            </View>
          );
        })}
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
    paddingHorizontal: spacing.base,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  scrollContent: {
    padding: spacing.base,
    paddingBottom: spacing.xxl,
  },
  searchContainer: {
    marginBottom: spacing.lg,
  },
  agencySection: {
    marginBottom: spacing.lg,
  },
  agencyTitle: {
    marginBottom: 2,
  },
  agencySubtitle: {
    marginBottom: spacing.sm,
  },
  routesList: {
    gap: spacing.sm,
  },
  routeCard: {
    marginBottom: spacing.xs,
  },
  routeRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  routeInfoCol: {
    flex: 1,
    marginLeft: spacing.md,
    marginRight: spacing.sm,
  },
});
