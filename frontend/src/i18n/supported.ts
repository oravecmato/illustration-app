export const SUPPORTED_LANGUAGES = ['sk', 'cs', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]
