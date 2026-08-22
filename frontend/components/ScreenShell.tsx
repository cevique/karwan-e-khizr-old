import { ReactNode } from "react";
import { Platform, StyleSheet, View } from "react-native";
import { colors } from "@/constants/theme";

const WEB_MAX_WIDTH = 480;

export function ScreenShell({ children }: { children: ReactNode }) {
  if (Platform.OS === "web") {
    return (
      <View style={styles.page}>
        <View style={[styles.shell, styles.shellWeb]}>{children}</View>
      </View>
    );
  }
  return <View style={styles.shell}>{children}</View>;
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: colors.divider,
  },
  shell: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  shellWeb: {
    width: "100%",
    maxWidth: WEB_MAX_WIDTH,
    alignSelf: "center",
  },
});
