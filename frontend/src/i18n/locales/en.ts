export default {
  app: {
    title: 'Anime Illustrator',
    intro: 'Together with the assistant, create a short illustrated story.',
    new_story: '← New story',
  },
  chat: {
    welcome:
      "Hi! I'll help you create a short illustrated anime story. Tell me what it should be about and which characters should appear in it.",
    assistant_typing: 'Assistant is typing…',
    send: 'Send',
    message_placeholder: 'Type a message…',
    confirmation_placeholder: 'Write "yes" to confirm or suggest a change…',
    char_limit: 'characters',
    user_message_limit:
      "You've reached the maximum number of messages for this story. Start a new story to continue.",
  },
  access: {
    title: 'Access required',
    intro:
      'This is a private demo. Paste the access key you received from the operator, or follow the invite link they shared with you.',
    key_label: 'Access key',
    key_placeholder: 'Paste your access key…',
    submit: 'Continue',
    new_session: 'Start a new story',
    errors: {
      MISSING_ACCESS_KEY: 'Please paste the access key you received.',
      ACCESS_KEY_REVOKED:
        'This access key has been revoked. Contact the operator for a new one.',
      QUOTA_EXHAUSTED:
        "You've used up all stories on this access key. Contact the operator if you'd like more.",
    },
  },
  story: {
    illustration_n: 'Illustration {n}',
    illustration_failed: 'This illustration could not be created.',
    illustration_not_ready: 'Illustration is not ready yet…',
    building: 'Generating story…',
    building_progress_label: 'Preparing your illustrations…',
    try_again: 'Try again',
  },
  illustration: {
    state: {
      PENDING: 'Pending',
      GENERATING_PROMPTS: 'Generating prompts',
      RENDERING: 'Rendering image',
      EVALUATING: 'Evaluating',
      REVISING_PROMPTS: 'Revising prompts',
      RETHINKING_CONCEPT: 'Rethinking concept',
      RETHINKING_ENVIRONMENT: 'Rethinking environment',
      SALVAGE_REVIEW: 'Reviewing earlier attempts',
      MANUAL_CHATTING: 'Collaborative editing',
      MANUAL_GENERATING_PROMPTS: 'Preparing prompts (manual)',
      MANUAL_RENDERING: 'Rendering (manual)',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
      CANCELLED: 'Cancelled',
    },
    currentConcept: 'Concept',
    salvaged: 'This image was recovered from an earlier attempt by the AI.',
    salvagedParagraphPatched: 'The surrounding story paragraph was also adjusted to match this image.',
    entity_subtitle: 'Also in the scene: {label}',
    attempt: 'attempt {current}/{max}',
    manual: {
      title: 'Collaborative editing',
      budget: 'Attempt {used}/{max}',
      placeholder_concept: 'Describe what you want to see in the picture…',
      placeholder_feedback: 'Tell me what to change — be concrete (I can\'t see the picture)…',
      send: 'Send',
      sending: 'Sending…',
      error: 'Could not send the message. Try again.',
      attempt_alt: 'Manual attempt {n}',
      close_aria: 'Close chat',
      input_locked: 'Choose Accept or Iterate above to continue.',
      image_card: {
        attempt: 'Attempt {n}/{max}',
        accept: 'Accept',
        iterate: 'Iterate',
        use: 'Use',
        concept_aria: 'Show concept used for this attempt',
        prompts_aria: 'Show prompts used for this attempt',
        positive_label: 'Positive',
        negative_label: 'Negative',
        action_error: 'Action failed. Try again.',
      },
    },
    menu: {
      aria_label: 'Illustration options',
      regenerate: 'Regenerate image',
      show_chat: 'Show chat',
      hide_chat: 'Hide chat',
    },
  },
  run: {
    status: {
      RUNNING: 'Running',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
      CANCELLED: 'Cancelled',
      translating: 'Translating into English',
    },
    progress: 'Completed: {completed} of {total}',
    progress_unknown: 'Completed: {completed} of —',
    cancel: 'Cancel',
    confirm_cancel: 'Really cancel?',
    yes: 'Yes',
    no: 'No',
  },
  nav: {
    change_language: 'Change language',
  },
  language: {
    sk: 'Slovenčina',
    cs: 'Čeština',
    en: 'English',
  },
  a11y: {
    loading: 'Loading',
    show_concept: 'Show illustration concept',
  },
  errors: {
    session: {
      chat_failed: 'The assistant cannot respond at the moment. Please try again in a moment.',
      story_build_failed:
        'Something went wrong while building the story. Please start over and slightly adjust your brief.',
      translate_failed: 'Translation could not be completed. Please try again.',
      internal_error: 'An unexpected error occurred. Check the server log for details.',
    },
    run: {
      internal_error:
        'An unexpected error occurred while generating illustrations. Check the server log for details.',
      translate_failed: 'Translation of illustrations could not be completed.',
      sse_disconnected: 'Connection lost',
    },
  },
  toast: {
    language_switched: 'Language changed to {language}',
    translate_failed: 'Could not load translation',
  },
}
