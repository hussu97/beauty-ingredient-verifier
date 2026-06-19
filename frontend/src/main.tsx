import React from "react";
import ReactDOM from "react-dom/client";
import * as Sentry from "@sentry/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { initSentry } from "./lib/sentry";
import "./styles.css";

const sentryEnabled = initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
});

const app = (
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);

ReactDOM.createRoot(document.getElementById("root")!).render(
  sentryEnabled ? (
    <Sentry.ErrorBoundary fallback={<div role="alert">Something went wrong.</div>}>
      {app}
    </Sentry.ErrorBoundary>
  ) : (
    app
  ),
);
