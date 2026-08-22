import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, type } from "@/constants/theme";

interface AppBarProps {
  title: string;
  onBack?: () => void;
}

export function AppBar({ title, onBack }: AppBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.bar, { paddingTop: insets.top + spacing.sm }]}>
      <TouchableOpacity
        onPress={onBack}
        disabled={!onBack}
        style={styles.button}
        activeOpacity={0.7}
      >
        <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
      </TouchableOpacity>
      <Text style={styles.title}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.sm,
  },
  button: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    flex: 1,
    ...type.title,
    color: colors.textPrimary,
  },
});
