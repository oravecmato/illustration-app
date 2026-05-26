import { toast as sonner } from 'vue-sonner'

const DEFAULT_DURATION = 5000

export function useToast() {
  return {
    info: (message: string) => {
      sonner.info(message, { duration: DEFAULT_DURATION })
    },
    success: (message: string) => {
      sonner.success(message, { duration: DEFAULT_DURATION })
    },
    error: (message: string) => {
      sonner.error(message, { duration: DEFAULT_DURATION })
    },
  }
}
