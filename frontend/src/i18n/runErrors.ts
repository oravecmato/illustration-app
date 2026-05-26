export function runErrorKey(errorCode: string | null | undefined): string {
  if (!errorCode) return ''

  const mapping: Record<string, string> = {
    INTERNAL_ERROR: 'errors.run.internal_error',
    TRANSLATE_FAILED: 'errors.run.translate_failed',
  }

  return mapping[errorCode] || 'errors.run.internal_error'
}
