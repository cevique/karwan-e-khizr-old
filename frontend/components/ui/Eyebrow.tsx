import { StyleSheet, Text } from "react-native";
import { colors, type } from "@/constants/theme";

interface EyebrowProps {
  children: string;
}

export function Eyebrow({ children }: EyebrowProps) {
  return <Text style={styles.label}>{children}</Text>;
}

const styles = StyleSheet.create({
  label: {
    ...type.micro,
    color: colors.textTertiary,
  },
});
