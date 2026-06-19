import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import DirectoryPage from "../pages/DirectoryPage";

describe("DirectoryPage", () => {
  it("renders the unified PLP controls", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation((message?: unknown, ...rest: unknown[]) => {
      if (String(message).includes("useLayoutEffect does nothing on the server")) return;
      console.warn(message, ...rest);
    });
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    try {
      const markup = renderToStaticMarkup(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <DirectoryPage />
          </MemoryRouter>
        </QueryClientProvider>,
      );

      expect(markup).toContain("Products");
      expect(markup).toContain("Search products");
      expect(markup).toContain("Sort");
      expect(markup).toContain("Filters");
      expect(markup).toContain("Brands");
      expect(markup).toContain("Categories");
    } finally {
      errorSpy.mockRestore();
    }
  });
});
