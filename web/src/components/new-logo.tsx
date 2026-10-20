import { cn } from "@/lib/utils"

export const NewLogo = ({ className }: { className?: string }) => {

  return <img src="/icon.png" className={cn("size-4", className)} />

}
