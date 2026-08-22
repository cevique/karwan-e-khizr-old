import React from "react";
import {
  View,
  TextInput,
  TextInputProps,
  StyleSheet,
  Pressable,
  ViewStyle,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radii, spacing, elevation } from "../../constants/theme";

export interface SearchFieldProps extends TextInputProps {
  onClear?: () => void;
  onVoicePress?: () => void;
  onPressContainer?: () => void;
  readOnlyContainer?: boolean;
  containerStyle?: ViewStyle;
}

export const SearchField: React.FC<SearchFieldProps> = ({
  value,
  onChangeText,
  placeholder = "Where are you going?",
  onClear,
  onVoicePress,
  onPressContainer,
  readOnlyContainer = false,
  containerStyle,
  ...props
}) => {
  const content = (
    <View style={[styles.container, containerStyle]}>
      <Ionicons name="search" size={20} color={colors.textSecondary} style={styles.leftIcon} />
      {readOnlyContainer ? (
        <TextInput
          editable={false}
          value={value}
          placeholder={placeholder}
          placeholderTextColor={colors.textTertiary}
          style={styles.input}
          pointerEvents="none"
          {...props}
        />
      ) : (
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.textTertiary}
          style={styles.input}
          {...props}
        />
      )}
      {value && value.length > 0 && onClear && (
        <Pressable onPress={onClear} style={styles.rightIconButton}>
          <Ionicons name="close-circle" size={18} color={colors.textTertiary} />
        </Pressable>
      )}
      {onVoicePress && (!value || value.length === 0) && (
        <Pressable onPress={onVoicePress} style={styles.rightIconButton}>
          <Ionicons name="mic-outline" size={20} color={colors.textSecondary} />
        </Pressable>
      )}
    </View>
  );

  if (onPressContainer) {
    return (
      <Pressable onPress={onPressContainer} style={styles.pressableWrapper}>
        {content}
      </Pressable>
    );
  }

  return content;
};

const styles = StyleSheet.create({
  pressableWrapper: {
    width: "100%",
  },
  container: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md - 2,
    borderWidth: 1,
    borderColor: colors.divider,
    ...elevation.soft,
  },
  leftIcon: {
    marginRight: spacing.sm,
  },
  input: {
    flex: 1,
    fontSize: 15,
    color: colors.textPrimary,
    padding: 0,
  },
  rightIconButton: {
    padding: spacing.xxs,
    marginLeft: spacing.xs,
  },
});
