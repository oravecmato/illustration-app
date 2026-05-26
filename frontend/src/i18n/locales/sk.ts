export default {
  chat: {
    welcome:
      'Ahoj! Pomôžem ti vytvoriť krátky ilustrovaný anime príbeh. Povedz mi, o čom má byť a aké #postavy# v ňom vystúpia.',
    assistant_typing: 'Asistent píše…',
    send: 'Odoslať',
    message_placeholder: 'Napíš správu…',
    char_limit: 'znakov',
  },
  story: {
    illustration_n: 'Ilustrácia {n}',
    building: 'Vytváram príbeh na tému: {topic}…',
    try_again: 'Skúsiť znova',
  },
  illustration: {
    state: {
      PENDING: 'Čaká',
      GENERATING_PROMPTS: 'Vytváranie promptov',
      RENDERING: 'Vytváranie obrázka',
      EVALUATING: 'Hodnotenie',
      REVISING_PROMPTS: 'Úprava promptov',
      RETHINKING_CONCEPT: 'Prepracovanie konceptu',
      COMPLETED: 'Hotovo',
      FAILED: 'Zlyhalo',
      CANCELLED: 'Zrušené',
    },
    currentConcept: 'Koncept',
    companion_subtitle: 'V scéne je tiež: {description}',
    attempt: 'pokus {current}/{max}',
  },
  run: {
    status: {
      RUNNING: 'Beží',
      COMPLETED: 'Hotovo',
      FAILED: 'Zlyhalo',
      CANCELLED: 'Zrušené',
    },
    progress: 'Hotové: {completed} z {total}',
    cancel: 'Zrušiť',
  },
  nav: {
    change_language: 'Zmeniť jazyk',
  },
  language: {
    sk: 'Slovenčina',
    cs: 'Čeština',
    en: 'English',
  },
  errors: {
    session: {
      chat_failed: 'Asistent momentálne nedokáže odpovedať. Skús to prosím o chvíľu znova.',
      story_build_failed:
        'Pri tvorbe príbehu sa niečo pokazilo. Skús prosím začať odznova a mierne upraviť zadanie.',
      translate_failed: 'Preklad sa nepodarilo dokončiť. Skús to prosím znova.',
      internal_error: 'Vyskytla sa neočakávaná chyba. Skontroluj log servera pre detaily.',
    },
    run: {
      internal_error:
        'Vyskytla sa neočakávaná chyba pri generovaní ilustrácií. Skontroluj log servera pre detaily.',
      translate_failed: 'Preklad ilustrácií sa nepodarilo dokončiť.',
    },
  },
  toast: {
    language_switched: 'Jazyk bol zmenený na {language}',
    translate_failed: 'Preklad sa nepodarilo načítať',
  },
}
