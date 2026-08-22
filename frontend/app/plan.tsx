import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppBar } from "@/components/ui/AppBar";
import { Button } from "@/components/ui/Button";
import { colors, elevation, radii, spacing, type } from "@/constants/theme";
import { useLocation } from "@/hooks/useLocation";
import { listStops } from "@/services/transit";
import type { Coordinates, StopRead } from "@/types/api";

interface Endpoint {
  name: string;
  location: Coordinates;
}

export default function PlanScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { location, granted } = useLocation();
  const [stops, setStops] = useState<StopRead[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [originQuery, setOriginQuery] = useState("");
  const [destinationQuery, setDestinationQuery] = useState("");
  const [origin, setOrigin] = useState<Endpoint | null>(null);
  const [destination, setDestination] = useState<Endpoint | null>(null);
  const [activeField, setActiveField] = useState<"origin" | "destination">("origin");

  useEffect(() => {
    let cancelled = false;
    listStops({ limit: 200 })
      .then((result) => {
        if (!cancelled) setStops(result);
      })
      .catch(() => {
        if (!cancelled) setLoadError("Can't load the stop list right now.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const query = activeField === "origin" ? originQuery : destinationQuery;
  const suggestions = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (!trimmed) return [];
    return stops
      .filter((stop) => stop.name.toLowerCase().includes(trimmed))
      .slice(0, 6);
  }, [query, stops]);

  const selectStop = useCallback(
    (stop: StopRead) => {
      if (!stop.location) return;
      const selected: Endpoint = { name: stop.name, location: stop.location };
      if (activeField === "origin") {
        setOrigin(selected);
        setOriginQuery(stop.name);
      } else {
        setDestination(selected);
        setDestinationQuery(stop.name);
      }
    },
    [activeField],
  );

  const useMyLocation = () => {
    if (!location) return;
    setOrigin({ name: "My location", location });
    setOriginQuery("My location");
  };

  const swap = () => {
    setOrigin(destination);
    setDestination(origin);
    setOriginQuery(destination?.name ?? "");
    setDestinationQuery(origin?.name ?? "");
  };

  const canSearch = origin !== null && destination !== null;

  const search = () => {
    if (!canSearch) return;
    router.push({
      pathname: "/search-results",
      params: {
        origin: JSON.stringify(origin.location),
        destination: JSON.stringify(destination.location),
        originName: origin.name,
        destinationName: destination.name,
      },
    });
  };

  const showUseLocation =
    activeField === "origin" && granted && location !== null && !origin;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <AppBar title="Plan your journey" onBack={() => router.back()} />
      <View style={[styles.body, { paddingBottom: insets.bottom + spacing.base }]}>
        <View style={styles.fieldCard}>
          <Text style={styles.label}>FROM</Text>
          <TextInput
            style={styles.input}
            placeholder="Start typing a stop name"
            placeholderTextColor={colors.textTertiary}
            value={originQuery}
            onChangeText={(text) => {
              setOrigin((current) =>
                current !== null && current.name === text ? current : null,
              );
              setOriginQuery(text);
              setActiveField("origin");
            }}
            onFocus={() => setActiveField("origin")}
          />
          <TouchableOpacity
            style={styles.swapButton}
            onPress={swap}
            activeOpacity={0.7}
          >
            <Ionicons name="swap-vertical" size={16} color={colors.accent} />
            <Text style={styles.swapText}>Swap</Text>
          </TouchableOpacity>
          <Text style={styles.label}>TO</Text>
          <TextInput
            style={styles.input}
            placeholder="Start typing a stop name"
            placeholderTextColor={colors.textTertiary}
            value={destinationQuery}
            onChangeText={(text) => {
              setDestination((current) =>
                current !== null && current.name === text ? current : null,
              );
              setDestinationQuery(text);
              setActiveField("destination");
            }}
            onFocus={() => setActiveField("destination")}
          />
        </View>

        {showUseLocation && (
          <TouchableOpacity
            style={styles.useLocationRow}
            onPress={useMyLocation}
            activeOpacity={0.6}
          >
            <Ionicons name="locate" size={18} color={colors.accent} />
            <Text style={styles.useLocationText}>Use my location</Text>
          </TouchableOpacity>
        )}

        {loadError ? (
          <Text style={styles.stateText}>{loadError}</Text>
        ) : suggestions.length > 0 ? (
          <FlatList
            data={suggestions}
            keyExtractor={(stop) => stop.id}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => (
              <View>
                <TouchableOpacity
                  style={[
                    styles.suggestionRow,
                    !item.location && styles.suggestionDisabled,
                  ]}
                  disabled={!item.location}
                  onPress={() => selectStop(item)}
                >
                  <Ionicons name="location-outline" size={16} color={colors.textSecondary} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.suggestionName}>{item.name}</Text>
                    {!item.location && (
                      <Text style={styles.suggestionMeta}>
                        No coordinates yet — can&apos;t be used in search
                      </Text>
                    )}
                  </View>
                </TouchableOpacity>
                <View style={styles.divider} />
              </View>
            )}
          />
        ) : null}

        <View style={{ marginTop: "auto" }}>
          <Button label="Find journeys" onPress={search} disabled={!canSearch} />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  body: {
    flex: 1,
    padding: spacing.base,
    gap: spacing.md,
  },
  fieldCard: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: spacing.base,
    ...elevation.soft,
  },
  label: {
    ...type.micro,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  input: {
    ...type.body,
    color: colors.textPrimary,
    paddingVertical: spacing.sm,
  },
  swapButton: {
    alignSelf: "flex-end",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radii.pill,
    backgroundColor: colors.accentSoft,
    marginBottom: spacing.sm,
  },
  swapText: {
    ...type.caption,
    fontWeight: "600",
    color: colors.accent,
  },
  useLocationRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radii.card - 4,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.base,
  },
  useLocationText: {
    ...type.body,
    color: colors.accent,
    fontWeight: "500",
  },
  suggestionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radii.button,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.base,
  },
  suggestionDisabled: {
    opacity: 0.5,
  },
  suggestionName: {
    ...type.body,
    color: colors.textPrimary,
  },
  suggestionMeta: {
    ...type.caption,
    color: colors.textSecondary,
    marginTop: 2,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.divider,
    marginHorizontal: spacing.base,
  },
  stateText: {
    ...type.caption,
    color: colors.textSecondary,
    lineHeight: 19,
  },
});
