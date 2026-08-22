import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { RouteCircle } from "@/components/ui/RouteCircle";
import { colors, spacing, type } from "@/constants/theme";
import { listRoutes } from "@/services/transit";
import type { RouteListItem } from "@/types/api";

export default function RoutesScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [routes, setRoutes] = useState<RouteListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listRoutes()
      .then((data) => {
        if (!cancelled) setRoutes(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load routes. Pull down to retry.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: RouteListItem }) => (
      <View>
        <TouchableOpacity
          style={styles.row}
          activeOpacity={0.6}
          onPress={() => router.push(`/routes/${item.id}`)}
        >
          <RouteCircle label={item.short_name} />
          <Text style={styles.longName} numberOfLines={2}>
            {item.long_name ?? "Name not available"}
          </Text>
          <Ionicons name="chevron-forward" size={16} color={colors.textTertiary} />
        </TouchableOpacity>
        <View style={styles.divider} />
      </View>
    ),
    [router],
  );

  return (
    <View style={[styles.container, { paddingTop: insets.top + spacing.md }]}>
      <Text style={styles.title}>All Routes</Text>
      {error ? (
        <StateBlock text={error} />
      ) : routes === null ? (
        <ActivityIndicator style={styles.loader} color={colors.accent} />
      ) : routes.length === 0 ? (
        <StateBlock text="No routes have been published yet." />
      ) : (
        <FlatList
          data={routes}
          keyExtractor={(route) => route.id}
          renderItem={renderItem}
          contentContainerStyle={{ paddingBottom: spacing.xxl }}
        />
      )}
    </View>
  );
}

function StateBlock({ text }: { text: string }) {
  return (
    <View style={styles.stateWrap}>
      <Text style={styles.stateText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.base,
  },
  title: {
    ...type.display,
    color: colors.textPrimary,
    paddingHorizontal: spacing.sm,
    marginBottom: spacing.base,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.base,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  longName: {
    ...type.body,
    color: colors.textPrimary,
    flex: 1,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.divider,
  },
  loader: {
    marginTop: spacing.xl,
  },
  stateWrap: {
    padding: spacing.lg,
  },
  stateText: {
    ...type.caption,
    color: colors.textSecondary,
    textAlign: "center",
    lineHeight: 19,
  },
});
