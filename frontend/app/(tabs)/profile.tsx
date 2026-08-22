import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { StyleSheet, Text, View } from "react-native";
import { colors, spacing, type } from "@/constants/theme";

export default function ProfileScreen() {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.container, { paddingTop: insets.top + spacing.md }]}>
      <Text style={styles.title}>Profile</Text>
      <View style={styles.empty}>
        <Ionicons name="person-circle-outline" size={40} color={colors.textTertiary} />
        <Text style={styles.emptyTitle}>Travelling as guest</Text>
        <Text style={styles.emptyBody}>
          Accounts and saved places arrive with ticketing in a later release.
        </Text>
      </View>
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
  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
    paddingBottom: spacing.xxl + spacing.lg,
  },
  emptyTitle: {
    ...type.heading,
    color: colors.textPrimary,
  },
  emptyBody: {
    ...type.caption,
    color: colors.textSecondary,
    textAlign: "center",
    lineHeight: 19,
    maxWidth: 260,
  },
});
