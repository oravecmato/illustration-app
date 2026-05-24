const MESSAGES: Record<string, string> = {
  CHAT_FAILED:
    "Konverzácia s asistentom zlyhala. Skúste obnoviť stránku a začať novú reláciu.",
  STORY_BUILD_FAILED:
    "Tvorba príbehu zlyhala. Skúste prosím začať novú reláciu a opísať tému trochu inak.",
  INTERNAL_ERROR:
    "Vyskytla sa neočakávaná chyba. Skontrolujte log servera pre detaily.",
};

const FALLBACK = MESSAGES.INTERNAL_ERROR;

export function getRunErrorMessage(errorCode: string | null | undefined): string {
  if (!errorCode) return "";
  return MESSAGES[errorCode] ?? FALLBACK;
}
