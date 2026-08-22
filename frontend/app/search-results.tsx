import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppBar } from "@/components/ui/AppBar";
import { Chip } from "@/components/ui/Chip";
import { RouteCircle } from "@/components/ui/RouteCircle";
import {
  TransitMapView,
  type MapMarker,
} from "@/components/TransitMapView";
import { colors, radii, spacing, type } from "@/constants/theme";
import { describeApiError } from "@/services/api";
import { quoteJourney } from "@/services/fares";
import { searchJourneys } from "@/services/journeys";
import type {
  Coordinates,
  JourneyLegRead,
  JourneyRead,
  RoutingObjective,
} from "@/types/api";
import {
  formatDuration,
  journeyMapLines,
  legSignature,
  toJourneySummary,
} from "@/utils/journey";

const OBJECTIVES: RoutingObjective[] = [
  "fastest",
  "fewest_transfers",
  "least_walking",
];

interface ResultCard {
  journey: JourneyRead;
  fare: string | null;
}

export default function SearchResultsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams() as Partial<
    Record<string, string | undefined>
  >;

  const origin = useMemo<Coordinates | null>(
    () => (params.origin ? safeParse(params.origin) : null),
    [params.origin],
  );
  const destination = useMemo<Coordinates | null>(
    () => (params.destination ? safeParse(params.destination) : null),
    [params.destination],
  );

  const [results, setResults] = useState<ResultCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const selectedJourney = results?.[selectedIndex]?.journey ?? null;
  const selectedLines = useMemo(
    () => (selectedJourney ? journeyMapLines(selectedJourney) : []),
    [selectedJourney],
  );
  const fitCoordinates = useMemo(() => {
    if (!origin || !destination) return [];
    return [
      ...selectedLines.flatMap((line) => line.coordinates),
      [origin.longitude, origin.latitude] as [number, number],
      [destination.longitude, destination.latitude] as [number, number],
    ];
  }, [selectedLines, origin, destination]);
  const previewMarkers = useMemo<MapMarker[]>(
    () =>
      origin && destination
        ? [
            { id: "origin", coordinate: origin, kind: "origin" },
            { id: "destination", coordinate: destination, kind: "destination" },
          ]
        : [],
    [origin, destination],
  );

  useEffect(() => {
    if (!origin || !destination) return;
    const from = origin;
    const to = destination;
    let cancelled = false;

    async function load() {
      try {
        const searches = await Promise.all(
          OBJECTIVES.map((objective) =>
            searchJourneys({ origin: from, destination: to, objective }),
          ),
        );
        if (cancelled) return;

        const seen = new Set<string>();
        const unique: JourneyRead[] = [];
        for (const search of searches) {
          for (const journey of search.journeys) {
            const signature = legSignature(journey);
            if (!seen.has(signature)) {
              seen.add(signature);
              unique.push(journey);
            }
          }
        }
        unique.sort((a, b) => a.total_duration_s - b.total_duration_s);

        const cards = await Promise.all(
          unique.map(async (journey) => {
            try {
              const quote = await quoteJourney(
                toJourneySummary(journey, from, to),
              );
              return { journey, fare: `${quote.currency} ${quote.amount}` };
            } catch {
              return { journey, fare: null };
            }
          }),
        );
        if (!cancelled) {
          setResults(cards);
          setSelectedIndex(0);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(
            describeApiError(cause, "Couldn't find journeys between these stops."),
          );
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [origin, destination]);

  return (
    <View style={styles.container}>
      <AppBar title="Select Route" onBack={() => router.back()} />
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + spacing.xl },
        ]}
      >
        {origin && destination ? (
          <>
            <View style={styles.mapPreview}>
              <TransitMapView
                markers={previewMarkers}
                lines={selectedLines}
                fitCoordinates={fitCoordinates}
              />
            </View>
            <View style={styles.tripSummary}>
              <SummaryRow icon="radio-button-on-outline" label={params.originName ?? ""} />
              <View style={styles.summaryConnector}>
                <Ionicons name="arrow-down" size={14} color={colors.textTertiary} />
              </View>
              <SummaryRow icon="location-sharp" label={params.destinationName ?? ""} />
            </View>
          </>
        ) : (
          <Text style={styles.stateText}>No trip selected.</Text>
        )}

        {error ? (
          <>
            <Text style={styles.stateText}>{error}</Text>
            <TouchableOpacity onPress={() => router.replace("/plan")}>
              <Text style={styles.linkText}>Try different stops</Text>
            </TouchableOpacity>
          </>
        ) : results === null ? (
          <ActivityIndicator style={styles.loader} color={colors.accent} />
        ) : results.length === 0 ? (
          <Text style={styles.stateText}>
            No transit journeys found. These stops may not be connected yet.
          </Text>
        ) : (
          results.map((card, index) => (
            <TouchableOpacity
              key={`${legSignature(card.journey)}-${index}`}
              activeOpacity={0.85}
              onPress={() => setSelectedIndex(index)}
            >
              <ResultCardView
                card={card}
                isBest={index === 0}
                isSelected={index === selectedIndex}
              />
            </TouchableOpacity>
          ))
        )}
      </ScrollView>
    </View>
  );
}

function SummaryRow({ icon, label }: { icon: keyof typeof Ionicons.glyphMap; label: string }) {
  return (
    <View style={styles.summaryRow}>
      <Ionicons name={icon} size={16} color={colors.textSecondary} />
      <Text style={styles.summaryLabel}>{label}</Text>
    </View>
  );
}

function ResultCardView({
  card,
  isBest,
  isSelected,
}: {
  card: ResultCard;
  isBest: boolean;
  isSelected: boolean;
}) {
  const rideLegs = card.journey.legs.filter(
    (leg): leg is Extract<JourneyLegRead, { type: "ride" }> => leg.type === "ride",
  );
  const walkMeters = card.journey.total_walk_m;
  return (
    <View
      style={[
        styles.card,
        (isBest || isSelected) && styles.cardSelected,
      ]}
    >
      {isBest && (
        <View style={styles.bestTagWrap}>
          <Chip label="Best match" selected />
        </View>
      )}
      <View style={styles.cardTopRow}>
        <View style={styles.routeCircles}>
          {rideLegs.length === 0 ? (
            <Ionicons name="walk-outline" size={22} color={colors.textSecondary} />
          ) : (
            rideLegs.map((leg, i) => (
              <RouteCircle key={`${leg.route.id}-${i}`} label={leg.route.short_name} size={34} />
            ))
          )}
        </View>
        <View style={styles.durationWrap}>
          <Text style={styles.duration}>{formatDuration(card.journey.total_duration_s)}</Text>
          {card.fare && <Text style={styles.fare}>{card.fare}</Text>}
        </View>
      </View>
      <View style={styles.metaRow}>
        {!!walkMeters && walkMeters > 0 && (
          <MetaPill
            icon="footsteps-outline"
            text={`${Math.round(walkMeters)} m walk`}
          />
        )}
        {rideLegs.length > 1 && (
          <MetaPill
            icon="swap-horizontal"
            text={`${rideLegs.length - 1} transfer${rideLegs.length > 2 ? "s" : ""}`}
          />
        )}
        {!card.fare && rideLegs.length > 0 && (
          <MetaPill icon="information-circle-outline" text="Fare unavailable" />
        )}
      </View>
    </View>
  );
}

function MetaPill({
  icon,
  text,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  text: string;
}) {
  return (
    <View style={styles.metaPill}>
      <Ionicons name={icon} size={13} color={colors.textSecondary} />
      <Text style={styles.metaPillText}>{text}</Text>
    </View>
  );
}

function safeParse(json: string): Coordinates | null {
  try {
    const parsed = JSON.parse(json);
    if (
      parsed &&
      typeof parsed.latitude === "number" &&
      typeof parsed.longitude === "number"
    ) {
      return parsed as Coordinates;
    }
    return null;
  } catch {
    return null;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  content: {
    padding: spacing.base,
    gap: spacing.md,
  },
  tripSummary: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: spacing.base,
    gap: spacing.xs,
  },
  summaryRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.xs,
  },
  summaryLabel: {
    ...type.body,
    color: colors.textPrimary,
    flex: 1,
  },
  summaryConnector: {
    paddingLeft: 15,
  },
  loader: {
    marginTop: spacing.xl,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: 1.5,
    borderColor: colors.divider,
    padding: spacing.base,
    gap: spacing.md,
  },
  cardSelected: {
    borderColor: colors.accent,
  },
  mapPreview: {
    height: 240,
    borderRadius: radii.card,
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
  },
  bestTagWrap: {
    position: "absolute",
    top: -spacing.md,
    left: spacing.base,
  },
  cardTopRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  routeCircles: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexShrink: 1,
  },
  durationWrap: {
    alignItems: "flex-end",
  },
  duration: {
    ...type.title,
    color: colors.textPrimary,
  },
  fare: {
    ...type.caption,
    color: colors.textSecondary,
  },
  metaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  metaPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.bgPrimary,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
  },
  metaPillText: {
    ...type.micro,
    color: colors.textSecondary,
  },
  stateText: {
    ...type.caption,
    color: colors.textSecondary,
    lineHeight: 19,
    textAlign: "center",
    marginTop: spacing.lg,
  },
  linkText: {
    ...type.body,
    color: colors.accent,
    fontWeight: "600",
    textAlign: "center",
    marginTop: spacing.md,
  },
});
