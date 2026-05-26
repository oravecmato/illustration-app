export default {
  chat: {
    welcome:
      'Ahoj! Pomůžu ti vytvořit krátký ilustrovaný anime příběh. Řekni mi, o čem má být a jaké #postavy# v něm vystupují.',
    assistant_typing: 'Asistent píše…',
    send: 'Odeslat',
    message_placeholder: 'Napiš zprávu…',
    char_limit: 'znaků',
  },
  story: {
    illustration_n: 'Ilustrace {n}',
    building: 'Vytvářím příběh na téma: {topic}…',
    try_again: 'Zkusit znovu',
  },
  illustration: {
    state: {
      PENDING: 'Čeká',
      GENERATING_PROMPTS: 'Vytváření promptů',
      RENDERING: 'Vytváření obrázku',
      EVALUATING: 'Hodnocení',
      REVISING_PROMPTS: 'Úprava promptů',
      RETHINKING_CONCEPT: 'Přepracování konceptu',
      COMPLETED: 'Hotovo',
      FAILED: 'Selhalo',
      CANCELLED: 'Zrušeno',
    },
    currentConcept: 'Koncept',
    companion_subtitle: 'Ve scéně je také: {description}',
    attempt: 'pokus {current}/{max}',
  },
  run: {
    status: {
      RUNNING: 'Běží',
      COMPLETED: 'Hotovo',
      FAILED: 'Selhalo',
      CANCELLED: 'Zrušeno',
    },
    progress: 'Hotovo: {completed} z {total}',
    cancel: 'Zrušit',
  },
  nav: {
    change_language: 'Změnit jazyk',
  },
  language: {
    sk: 'Slovenčina',
    cs: 'Čeština',
    en: 'English',
  },
  errors: {
    session: {
      chat_failed: 'Asistent momentálně nedokáže odpovědět. Zkus to prosím za chvíli znovu.',
      story_build_failed:
        'Při tvorbě příběhu se něco pokazilo. Zkus prosím začít znovu a mírně upravit zadání.',
      translate_failed: 'Překlad se nepodařilo dokončit. Zkus to prosím znovu.',
      internal_error: 'Vyskytla se neočekávaná chyba. Zkontroluj log serveru pro detaily.',
    },
    run: {
      internal_error:
        'Vyskytla se neočekávaná chyba při generování ilustrací. Zkontroluj log serveru pro detaily.',
      translate_failed: 'Překlad ilustrací se nepodařilo dokončit.',
    },
  },
  toast: {
    language_switched: 'Jazyk byl změněn na {language}',
    translate_failed: 'Překlad se nepodařilo načíst',
  },
}
