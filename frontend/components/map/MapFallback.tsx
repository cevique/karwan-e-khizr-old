import { Ionicons } from "@expo/vector-icons";
import { Component, type ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { colors, spacing, type } from "@/constants/theme";

export const mapContainerStyle = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#E8EAE6",
    overflow: "hidden",
  },
});

export function MapFallback() {
  return (
    <View style={[mapContainerStyle.container, styles.fallback]}>
      <Ionicons name="map-outline" size={24} color={colors.textSecondary} />
      <Text style={styles.fallbackTitle}>Map unavailable here</Text>
      <Text style={styles.fallbackBody}>
        The live map needs the development build. Nearby buses are listed below.
      </Text>
    </View>
  );
}

interface MapErrorBoundaryProps {
  children: ReactNode;
}

export class MapErrorBoundary extends Component<
  MapErrorBoundaryProps,
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) return <MapFallback />;
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  fallback: {
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
  },
  fallbackTitle: {
    ...type.heading,
    color: colors.textPrimary,
  },
  fallbackBody: {
    ...type.caption,
    color: colors.textSecondary,
    textAlign: "center",
  },
});
