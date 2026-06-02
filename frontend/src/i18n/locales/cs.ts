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
    user_message_limit:
      'Dosáhl jsi maximálního počtu zpráv pro tento příběh. Pro pokračování začni nový příběh.',
  },
  access: {
    title: 'Vyžadovaný přístup',
    intro:
      'Toto je soukromé demo. Vlož přístupový klíč, který ti dal provozovatel, nebo použij pozvánkový odkaz.',
    key_label: 'Přístupový klíč',
    key_placeholder: 'Vlož svůj přístupový klíč…',
    submit: 'Pokračovat',
    new_session: 'Začít nový příběh',
    errors: {
      MISSING_ACCESS_KEY: 'Prosím, vlož přístupový klíč, který jsi dostal.',
      ACCESS_KEY_REVOKED:
        'Tento přístupový klíč byl zrušen. Kontaktuj provozovatele pro nový.',
      QUOTA_EXHAUSTED:
        'Vyčerpal jsi všechny příběhy tohoto klíče. Pokud chceš více, ozvi se provozovateli.',
    },
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
      RETHINKING_ENVIRONMENT: 'Přepracování prostředí',
      SALVAGE_REVIEW: 'Přehodnocení dřívějších pokusů',
      MANUAL_CHATTING: 'Společná tvorba',
      MANUAL_GENERATING_PROMPTS: 'Připravuji prompty (manuál)',
      MANUAL_RENDERING: 'Kreslím (manuál)',
      RENDERING_QUEUED: 'Ve frontě na GPU',
      MANUAL_RENDERING_QUEUED: 'Ve frontě na GPU (manuál)',
      COMPLETED: 'Hotovo',
      FAILED: 'Selhalo',
      CANCELLED: 'Zrušeno',
    },
    currentConcept: 'Koncept',
    salvaged: 'Tento obrázek AI obnovila z dřívějšího pokusu.',
    salvagedParagraphPatched: 'Také okolní odstavec příběhu byl upraven, aby obrázku odpovídal.',
    entity_subtitle: 'Ve scéně je také: {label}',
    attempt: 'pokus {current}/{max}',
    manual: {
      title: 'Společná tvorba',
      budget: 'Pokus {used}/{max}',
      placeholder_concept: 'Popiš, co chceš v obrázku vidět…',
      placeholder_feedback: 'Řekni mi konkrétně, co změnit (obrázek nevidím)…',
      send: 'Odeslat',
      sending: 'Posílám…',
      error: 'Zprávu se nepodařilo odeslat. Zkus to znovu.',
      attempt_alt: 'Manuální pokus {n}',
      close_aria: 'Zavřít konverzaci',
      input_locked: 'Pokračujte volbou Akceptovat nebo Iterovat výše.',
      image_card: {
        attempt: 'Pokus {n}/{max}',
        accept: 'Akceptovat',
        iterate: 'Iterovat',
        use: 'Použít',
        concept_aria: 'Zobrazit koncept použitý pro tento pokus',
        prompts_aria: 'Zobrazit prompty použité pro tento pokus',
        positive_label: 'Pozitivní',
        negative_label: 'Negativní',
        action_error: 'Akce selhala. Zkus to znovu.',
      },
    },
    menu: {
      aria_label: 'Možnosti ilustrace',
      regenerate: 'Vygenerovat obrázek znovu',
      show_chat: 'Zobrazit konverzaci',
      hide_chat: 'Skrýt konverzaci',
    },
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
