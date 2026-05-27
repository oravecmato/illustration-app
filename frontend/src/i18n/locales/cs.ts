export default {
  app: {
    title: 'Anime ilustrátor',
    intro: 'Společně s asistentem vymyslete krátký ilustrovaný příběh.',
    new_story: '← Nový příběh',
  },
  chat: {
    welcome:
      'Ahoj! Pomůžu ti vytvořit krátký ilustrovaný anime příběh. Řekni mi, o čem má být a jaké postavy v něm vystupují.',
    assistant_typing: 'Asistent píše…',
    send: 'Odeslat',
    message_placeholder: 'Napiš zprávu…',
    confirmation_placeholder: 'Napiš „ano" pro potvrzení nebo navrhni změnu…',
    char_limit: 'znaků',
  },
  story: {
    illustration_n: 'Ilustrace {n}',
    illustration_failed: 'Tuto ilustraci se nepodařilo vytvořit.',
    illustration_not_ready: 'Ilustrace ještě není připravená…',
    building: 'Generuji příběh…',
    building_progress_label: 'Připravuji ilustrace…',
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
      translating: 'Překládá se do češtiny',
    },
    progress: 'Hotovo: {completed} z {total}',
    progress_unknown: 'Hotovo: {completed} z —',
    cancel: 'Zrušit',
    confirm_cancel: 'Opravdu zrušit?',
    yes: 'Ano',
    no: 'Ne',
  },
  nav: {
    change_language: 'Změnit jazyk',
  },
  language: {
    sk: 'Slovenčina',
    cs: 'Čeština',
    en: 'English',
  },
  a11y: {
    loading: 'Načítá se',
    show_concept: 'Zobrazit koncept ilustrace',
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
      sse_disconnected: 'Spojení přerušeno',
    },
  },
  toast: {
    language_switched: 'Jazyk byl změněn na {language}',
    translate_failed: 'Překlad se nepodařilo načíst',
  },
}
