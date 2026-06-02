export function sessionErrorKey(errorCode: string | null | undefined): string {
  if (!errorCode) return ''

  const mapping: Record<string, string> = {
    CHAT_FAILED: 'errors.session.chat_failed',
    STORY_BUILD_FAILED: 'errors.session.story_build_failed',
    TRANSLATE_FAILED: 'errors.session.translate_failed',
    INTERNAL_ERROR: 'errors.session.internal_error',
    SESSION_USER_MESSAGE_LIMIT: 'chat.user_message_limit',
  }

  return mapping[errorCode] || 'errors.session.internal_error'
}
