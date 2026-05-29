import { TooltipProvider } from "@/components/ui/tooltip"

function App() {
  return (
    <TooltipProvider>
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-center space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight">
            loopAI Observability Dashboard
          </h1>
          <p className="text-muted-foreground">
            Frontend scaffold ready. Panels and data hooks to be added in subsequent plans.
          </p>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default App
