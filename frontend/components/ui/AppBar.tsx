import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, type } from "@/constants/theme";

interface AppBarProps {
  title: string;
  onBack?: () => void;
  floating?: boolean;
}

interface IconButtonProps {
  name: keyof typeof Ionicons.glyphMap;
  onPress?: () => void;
  floating?: boolean;
}

function BarButton({ name, onPress, floating }: IconButtonProps) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={!onPress}
      style={[styles.button, floating && styles.buttonFloating]}
      activeOpacity={0.7}
    >
      <Ionicons name={name} size={20} color={colors.textPrimary} />
    </TouchableOpacity>
  );
}

export function AppBar({ title, onBack, floating = false }: AppBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.bar, { paddingTop: insets.top + spacing.sm }]}>
      <BarButton name="chevron-back" onPress={onBack} floating={floating} />
      {!floating && <Text style={styles.title}>{title}</Text>}
      <BarButton name="ellipsis-horizontal" floating={floating} />
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
  buttonFloating: {
    backgroundColor: "rgba(255,255,255,0.92)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
  },
  title: {
    flex: 1,
    ...type.title,
    color: colors.textPrimary,
  },
});
