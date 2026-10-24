import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { bootApi } from "@/api/boot";
import { queryClient } from "@/api/queries";
import { ErrorBoundary } from "@/app/ErrorBoundary";
import { router } from "@/app/routes";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./index.css";

// The transport (http / mock / recorded) is wired before the first query runs.
void bootApi().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <ErrorBoundary label="StormCheck">
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={250}>
            <RouterProvider router={router} />
            <Toaster position="bottom-right" />
          </TooltipProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
});
