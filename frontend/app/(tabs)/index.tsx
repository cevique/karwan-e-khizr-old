import React, { useRef, useMemo, useCallback } from "react";
import { View, StyleSheet, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import BottomSheet from "@gorhom/bottom-sheet";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radii, elevation } from "../../constants/theme";
import { Text } from "../../components/design-system/Text";
import { SearchField } from "../../components/design-system/SearchField";
import { MapView, MapControls } from "../../components/map";
import { NearbyBusList } from "../../components/transit/NearbyBusList";
import { DemoBanner } from "../../components/transit/DemoBanner";
import { useLocation } from "../../hooks/useLocation";
import { useRealtimeVehicles } from "../../hooks/useRealtimeVehicles";
import { useNearbyStops } from "../../hooks/useNearbyStops";
import { VehiclePositionRead, StopRead } from "../../types";

export default function HomeScreen() {
  const router = useRouter();
  const bottomSheetRef = useRef<BottomSheet>(null);
  const snapPoints = useMemo(() => ["28%", "55%", "85%"], []);

  const { location: userLocation, requestPermission: locateUser } = useLocation();
  const { vehicles } = useRealtimeVehicles();
  const { stops } = useNearbyStops();

  const handleSearchPress = () => {
    router.push("/journey/search");
  };

  const handleVehiclePress = (vehicle: VehiclePositionRead) => {
    // Open route search pre-filtered for vehicle route
    router.push({
      pathname: "/journey/search",
      params: { preselectRouteId: vehicle.route_id },
    });
  };

  const handleStopPress = (stop: StopRead) => {
    router.push({
      pathname: "/journey/search",
      params: { originName: stop.name },
    });
  };

  return (
    <View style={styles.container}>
      {/* 1. Map Canvas Background */}
      <MapView
        userLocation={userLocation}
        stops={stops}
        vehicles={vehicles}
        onStopPress={handleStopPress}
        onVehiclePress={handleVehiclePress}
      />

      {/* 2. Top Header & Search Overlay Container */}
      <SafeAreaView style={styles.topOverlayContainer} pointerEvents="box-none">
        {/* Branding & Notification Bar */}
        <View style={styles.headerBar}>
          <View style={styles.brandTitleCol}>
            <Text variant="display" color={colors.textAccent} weight="700">
              Karwan e Khizr
            </Text>
            <Text variant="subheading" color={colors.textUrdu} style={styles.urduTitle}>
              کاروانِ خِضر
            </Text>
          </View>

          {/* Notification Bell with Badge */}
          <Pressable
            style={({ pressed }) => [styles.iconBellButton, pressed && styles.pressed]}
            onPress={() => {}}
          >
            <Ionicons name="notifications-outline" size={22} color={colors.textPrimary} />
            <View style={styles.notificationDot} />
          </Pressable>
        </View>

        {/* Search Field */}
        <View style={styles.searchWrapper}>
          <SearchField
            placeholder="Where are you going?"
            readOnlyContainer
            onPressContainer={handleSearchPress}
            onVoicePress={() => {}}
          />
        </View>

        {/* Demo Mode Badge */}
        <View style={styles.demoBannerWrapper}>
          <DemoBanner />
        </View>
      </SafeAreaView>

      {/* 3. Floating Map Controls */}
      <MapControls
        onLocatePress={locateUser}
        onFilterPress={() => {}}
        onFullscreenPress={() => {}}
        style={styles.mapControlsPosition}
      />

      {/* 4. Bottom Sheet for Nearby Buses */}
      <BottomSheet
        ref={bottomSheetRef}
        index={0}
        snapPoints={snapPoints}
        handleComponent={null}
        backgroundStyle={styles.bottomSheetBackground}
      >
        <NearbyBusList
          vehicles={vehicles}
          onVehiclePress={handleVehiclePress}
          onViewAllPress={() => router.push("/journey/search")}
        />
      </BottomSheet>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  topOverlayContainer: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    paddingHorizontal: spacing.base,
  },
  headerBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: spacing.xs,
    paddingBottom: spacing.xs,
  },
  brandTitleCol: {
    flex: 1,
  },
  urduTitle: {
    marginTop: -2,
  },
  iconBellButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    ...elevation.soft,
  },
  notificationDot: {
    position: "absolute",
    top: 9,
    right: 9,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.error,
  },
  searchWrapper: {
    marginTop: spacing.xs,
  },
  demoBannerWrapper: {
    marginTop: spacing.sm,
    alignSelf: "center",
  },
  mapControlsPosition: {
    top: 150,
  },
  bottomSheetBackground: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    ...elevation.floating,
  },
  pressed: {
    opacity: 0.8,
  },
});
