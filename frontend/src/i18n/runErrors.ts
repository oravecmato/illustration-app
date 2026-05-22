const MESSAGES: Record<string, string> = {
  NO_SUITABLE_SCENES:
    "Zadaný text nie je vhodný ako zdroj ilustrácií. Mal by obsahovať aspoň jednu jasnú scénu " +
    "s jednou postavou — chlapcom/mužom, dievčaťom/ženou alebo matkou — ktorá robí niečo konkrétne.",
  STEP0_FAILED:
    "Analýza textu zlyhala. Skúste prosím znova, prípadne upravte vstupný text.",
  INTERNAL_ERROR:
    "Vyskytla sa neočakávaná chyba. Skontrolujte log servera pre detaily.",
};

const FALLBACK = MESSAGES.INTERNAL_ERROR;

export function getRunErrorMessage(errorCode: string | null | undefined): string {
  if (!errorCode) return "";
  return MESSAGES[errorCode] ?? FALLBACK;
}
